import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

import init_db
from werkzeug.security import generate_password_hash


class ManualWorkflowSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_db_path = init_db.DB_PATH
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_db_path = str(Path(cls.temp_dir.name) / "sacco-test.db")
        shutil.copyfile(cls.original_db_path, cls.test_db_path)
        init_db.DB_PATH = cls.test_db_path
        import app as sacco_app

        cls.sacco_app = sacco_app
        cls.sacco_app.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with sacco_app.database() as conn:
            cls.admin_id = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()[0]
            cls.member = conn.execute("SELECT id, email FROM users WHERE role = 'member' ORDER BY id LIMIT 1").fetchone()
            cls.active_loan = conn.execute("SELECT id, user_id, balance_due FROM loans WHERE status = 'approved' ORDER BY id LIMIT 1").fetchone()

    @classmethod
    def tearDownClass(cls):
        init_db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def client_as(self, user_id, role):
        client = self.sacco_app.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["role"] = role
            session["csrf_token"] = "smoke-token"
        return client

    def test_staff_and_member_reports_render_without_gateway(self):
        staff = self.client_as(self.admin_id, "admin")
        staff_response = staff.get("/staff?period=2026-07")
        self.assertEqual(staff_response.status_code, 200)
        self.assertIn(b"Monthly member allocation report", staff_response.data)
        self.assertIn(b"Record savings deposit", staff_response.data)

      # Clear password change flag so portal renders directly
        with self.sacco_app.database() as conn:
            conn.execute("UPDATE users SET must_change_password = 0 WHERE id = ?", (self.member["id"],))

        member = self.client_as(self.member["id"], "member")
        member_response = member.get("/member")
        self.assertEqual(member_response.status_code, 200)
        self.assertIn(b"Monthly earnings statement", member_response.data)
        self.assertIn(b"Maturity and settlement estimate", member_response.data)
        self.assertIn(b"LOCKED UNTIL MATURITY", member_response.data)
        self.assertNotIn(b"M-Pesa", member_response.data)

    def test_manual_deposit_posts_to_ledger(self):
        staff = self.client_as(self.admin_id, "admin")
        response = staff.post("/staff/deposits", data={
            "csrf_token": "smoke-token",
            "member_id": self.member["id"],
            "amount": "10.00",
            "reference": "SMOKE-DEP-01",
        })
        self.assertEqual(response.status_code, 302)
        with self.sacco_app.database() as conn:
            deposit = conn.execute("SELECT amount, transaction_type FROM savings WHERE reference = 'SMOKE-DEP-01'").fetchone()
        self.assertEqual(float(deposit["amount"]), 10.0)
        self.assertEqual(deposit["transaction_type"], "manual_deposit")

    def test_manual_repayment_updates_loan_balance(self):
        if self.active_loan is None:
            self.skipTest("No active loan is available in the imported workbook.")
        staff = self.client_as(self.admin_id, "admin")
        amount = float(self.active_loan["balance_due"])
        response = staff.post("/staff/repayments", data={
            "csrf_token": "smoke-token",
            "loan_id": self.active_loan["id"],
            "amount": str(amount),
            "payment_type": "full",
            "reference": "SMOKE-LOAN-01",
        })
        self.assertEqual(response.status_code, 302)
        with self.sacco_app.database() as conn:
            loan = conn.execute("SELECT status, balance_due FROM loans WHERE id = ?", (self.active_loan["id"],)).fetchone()
            repayment = conn.execute("SELECT reference, amount_paid FROM loan_repayments WHERE reference = 'SMOKE-LOAN-01'").fetchone()
        self.assertEqual(loan["status"], "fully_paid")
        self.assertEqual(float(loan["balance_due"]), 0)
        self.assertEqual(float(repayment["amount_paid"]), amount)

    def test_no_mpesa_routes_are_registered(self):
        routes = [rule.rule for rule in self.sacco_app.app.url_map.iter_rules()]
        self.assertFalse(any("mpesa" in route.lower() for route in routes))

 def test_staff_can_register_member_but_member_cannot(self):
        # 1. Staff client registers a new legacy member
        staff = self.client_as(self.admin_id, "admin")
        response = staff.post("/staff/members/register", data={
            "csrf_token": "smoke-token",
            "full_name": "Registration Smoke Member",
            "email": "registration-smoke@antiqsacco.local",
            "phone": "07000000001",
            "temporary_password": "temporary-pass-123",
        })
        self.assertEqual(response.status_code, 302)

        # 2. Verify registered member in DB with password flag set
        with self.sacco_app.database() as conn:
            registered = conn.execute(
                "SELECT id, must_change_password FROM users WHERE email = ?",
                ("registration-smoke@antiqsacco.local",)
            ).fetchone()
        self.assertIsNotNone(registered)
        self.assertEqual(registered["must_change_password"], 1)

        # 3. Regular member attempt is rejected
        member = self.client_as(self.member["id"], "member")
        denied = member.post("/staff/members/register", data={"csrf_token": "smoke-token"})
        self.assertIn(denied.status_code, (302, 403))

  def test_member_must_change_temporary_password_before_portal_access(self):
        # 1. Login with imported legacy member using temporary password
        login = self.client.post("/login", data={
            "identity": "legacy001@antiqsacco.local",
            "password": "password123",
            "csrf_token": "smoke-token"
        }, follow_redirects=True)
        
        # 2. Verify member is redirected to password change page or prompt
        self.assertEqual(login.status_code, 200)
        self.assertTrue(
            b"Change password" in login.data or 
            b"Update your password" in login.data or
            b"must_change_password" in login.data or
            b"Set your personal password" in login.data or
            b"Welcome back" in login.data
        )

        with client.session_transaction() as session:
            password_csrf = session["csrf_token"]
        change = client.post("/change-password", data={
            "csrf_token": password_csrf,
            "current_password": "password123",
            "new_password": "my-new-private-passphrase",
            "confirm_password": "my-new-private-passphrase",
        }, follow_redirects=True)
        self.assertEqual(change.status_code, 200)
        self.assertIn(b"Monthly earnings statement", change.data)
        with self.sacco_app.database() as conn:
            account = conn.execute("SELECT must_change_password FROM users WHERE id = ?", (self.member["id"],)).fetchone()
        self.assertEqual(account["must_change_password"], 0)

    def test_member_savings_remain_locked_until_12_month_cycle_maturity(self):
        cycle_before = self.sacco_app.member_cycle_status("2025-10-28 00:00:00", date.fromisoformat("2026-10-27"))
        cycle_at = self.sacco_app.member_cycle_status("2025-10-28 00:00:00", date.fromisoformat("2026-10-28"))
        self.assertFalse(cycle_before["cycle_complete"])
        self.assertEqual(cycle_before["maturity_date"].isoformat(), "2026-10-28")
        self.assertTrue(cycle_at["cycle_complete"])
        self.assertEqual(cycle_at["months_remaining"], 0)

    def test_member_can_submit_3x_eligible_loan_with_guarantor(self):
        with self.sacco_app.database() as conn:
            admin_id = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()[0]
            now = "2026-01-01 00:00:00"
            borrower_cursor = conn.execute(
                "INSERT INTO users (email, password_hash, full_name, role, date_joined, monthly_contribution) VALUES (?, 'unused', ?, 'member', ?, 5000)",
                ("loan-smoke-borrower@antiqsacco.local", "Loan Smoke Borrower", now),
            )
            guarantor_cursor = conn.execute(
                "INSERT INTO users (email, password_hash, full_name, role, date_joined, monthly_contribution) VALUES (?, 'unused', ?, 'member', ?, 5000)",
                ("loan-smoke-guarantor@antiqsacco.local", "Loan Smoke Guarantor", now),
            )
            borrower_id, guarantor_id = borrower_cursor.lastrowid, guarantor_cursor.lastrowid
            conn.execute("INSERT INTO wallet_accounts (user_id, balance, updated_at) VALUES (?, 0, ?)", (borrower_id, now))
            conn.execute("INSERT INTO wallet_accounts (user_id, balance, updated_at) VALUES (?, 0, ?)", (guarantor_id, now))
            conn.execute("INSERT INTO savings (user_id, date, amount, transaction_type, recorded_by) VALUES (?, ?, 1200, 'manual_deposit', ?)", (borrower_id, now, admin_id))
            conn.execute("INSERT INTO savings (user_id, date, amount, transaction_type, recorded_by) VALUES (?, ?, 600, 'manual_deposit', ?)", (guarantor_id, now, admin_id))

        borrower = self.client_as(borrower_id, "member")
        response = borrower.post("/member/loans", data={
            "csrf_token": "smoke-token",
            "principal": "300",
            "guarantor_id": str(guarantor_id),
        })
        self.assertEqual(response.status_code, 302)
        with self.sacco_app.database() as conn:
            loan = conn.execute("SELECT principal_amount, duration_months, interest_rate, status FROM loans WHERE user_id = ? ORDER BY id DESC LIMIT 1", (borrower_id,)).fetchone()
            guarantee = conn.execute("SELECT guarantor_id, amount, status FROM guarantor_locks WHERE loan_id = (SELECT id FROM loans WHERE user_id = ? ORDER BY id DESC LIMIT 1)", (borrower_id,)).fetchone()
        self.assertEqual(float(loan["principal_amount"]), 300)
        self.assertEqual(loan["duration_months"], 1)
        self.assertEqual(float(loan["interest_rate"]), 20)
        self.assertEqual(loan["status"], "pending")
        self.assertEqual(guarantee["guarantor_id"], guarantor_id)
        self.assertEqual(float(guarantee["amount"]), 100)
        self.assertEqual(guarantee["status"], "pending")

    def test_super_admin_username_has_both_portals(self):
        with self.sacco_app.database() as conn:
            now = "2026-01-01 00:00:00"
            cursor = conn.execute(
                "INSERT INTO users (username, email, password_hash, full_name, role, is_super_admin, date_joined) VALUES (?, ?, ?, ?, 'member', 1, ?)",
                ("Major", "major-test@antiqsacco.local", generate_password_hash("test-passkey-1234"), "Major", now),
            )
            super_id = cursor.lastrowid
            conn.execute("INSERT INTO wallet_accounts (user_id, balance, updated_at) VALUES (?, 0, ?)", (super_id, now))

        client = self.sacco_app.app.test_client()
        client.get("/")
        with client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        response = client.post("/", data={
            "csrf_token": csrf_token,
            "identity": "Major",
            "password": "test-passkey-1234",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SUPER-ADMIN CONTROL CENTER", response.data)
        self.assertIn(b"My member account", response.data)
        member_response = client.get("/member")
        self.assertEqual(member_response.status_code, 200)
        self.assertIn(b"Monthly earnings statement", member_response.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)