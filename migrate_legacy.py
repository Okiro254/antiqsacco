import argparse
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from pyxlsb import open_workbook
from werkzeug.security import generate_password_hash

from init_db import DB_PATH, get_conn

SOURCE = Path(r"C:\Users\Godigs\Downloads\ANTIQ SACCO FORMULA.xlsb")
IMPORT_YEAR = 2026
DIVIDEND_YEAR = 2026
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def get_sheet_rows(workbook, name):
    with workbook.get_sheet(name) as sheet:
        return [[cell.v for cell in row] for row in sheet.rows(sparse=True)]


def number(row, column):
    if len(row) <= column or row[column] is None:
        return 0.0
    try:
        return round(float(row[column]), 2)
    except (TypeError, ValueError):
        return 0.0


def indexed_rows(rows):
    return {
        int(row[0]): row
        for row in rows
        if row and isinstance(row[0], (int, float))
    }


def build_preview():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Workbook not found: {SOURCE}")
    workbook = open_workbook(str(SOURCE))
    member_rows = indexed_rows(get_sheet_rows(workbook, "Members")[1:])
    savings_rows = indexed_rows(get_sheet_rows(workbook, "Savings")[1:])
    summary_rows = indexed_rows(get_sheet_rows(workbook, "Summary")[1:])
    loan_rows = indexed_rows(get_sheet_rows(workbook, "Loans (2)")[1:])
    repayment_rows = indexed_rows(get_sheet_rows(workbook, "Repayments")[1:])

    for member_number in sorted(set(savings_rows) - set(member_rows)):
        row = savings_rows[member_number]
        if len(row) > 1 and row[1]:
            member_rows[member_number] = [member_number, row[1]]

    members = []
    totals = {
        "savings_total": 0.0,
        "summary_savings": 0.0,
        "declared_dividends": 0.0,
        "loan_principal": 0.0,
        "loan_payable": 0.0,
        "loan_paid": 0.0,
        "loan_due": 0.0,
        "wallet_credits": 0.0,
    }

    for member_number, member_row in sorted(member_rows.items()):
        name = str(member_row[1]).strip()
        savings_row = savings_rows.get(member_number, [])
        monthly = []
        for month_number, month_name in enumerate(MONTHS, start=1):
            amount = number(savings_row, month_number + 1)
            if amount > 0:
                monthly.append({"month": month_number, "name": month_name, "amount": amount})
                totals["savings_total"] += amount

        summary_row = summary_rows.get(member_number, [])
        summary_savings = number(summary_row, 2)
        declared_dividend = number(summary_row, 4)
        totals["summary_savings"] += summary_savings
        totals["declared_dividends"] += declared_dividend

        loan_row = loan_rows.get(member_number)
        if loan_row is None:
            loan_row = next((
                row for row in get_sheet_rows(workbook, "Loans (2)")[1:]
                if len(row) > 1 and str(row[1]).strip().casefold() == name.casefold()
                and not (row and isinstance(row[0], (int, float)))
            ), [])

        principal = number(loan_row, 2)
        interest = number(loan_row, 4)
        payable = number(loan_row, 5)
        paid = max(0, number(loan_row, 6))
        applied_paid = min(paid, payable)
        due = max(0, round(payable - applied_paid, 2))
        credit = max(0, round(paid - payable, 2))
        totals["loan_principal"] += principal
        totals["loan_payable"] += payable
        totals["loan_paid"] += applied_paid
        totals["loan_due"] += due
        totals["wallet_credits"] += credit

        members.append({
            "legacy_id": member_number,
            "name": name,
            "monthly_savings": monthly,
            "savings_total": round(sum(item["amount"] for item in monthly), 2),
            "summary_savings": summary_savings,
            "declared_dividend": declared_dividend,
            "loan": {
                "principal": principal,
                "interest": interest,
                "payable": payable,
                "paid": applied_paid,
                "due": due,
                "credit": credit,
            },
        })

    totals = {key: round(amount, 2) for key, amount in totals.items()}
    totals["repayments_sheet_total"] = round(sum(number(row, 3) for row in repayment_rows.values()), 2)
    totals["savings_by_month"] = {
        month_name: round(sum(item["amount"] for member in members for item in member["monthly_savings"] if item["name"] == month_name), 2)
        for month_name in MONTHS
    }
    totals["member_count"] = len(members)
    return members, totals


def make_backup():
    db_file = Path(DB_PATH)
    if not db_file.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db_file.with_name(f"sacco-before-excel-import-{stamp}.db")
    with sqlite3.connect(db_file) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    return backup


def import_records(members):
    backup = make_backup()
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        admin = conn.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
        if admin is None:
            raise RuntimeError("The database needs an admin account before import.")
        admin_id = admin["id"]
        existing_ids = [row[0] for row in conn.execute("SELECT id FROM users WHERE role = 'member'")]
        if existing_ids:
            marks = ",".join("?" for _ in existing_ids)
            loan_ids = [row[0] for row in conn.execute(f"SELECT id FROM loans WHERE user_id IN ({marks})", existing_ids)]
            if loan_ids:
                loan_marks = ",".join("?" for _ in loan_ids)
                conn.execute(f"DELETE FROM mpesa_payments WHERE user_id IN ({marks}) OR loan_id IN ({loan_marks})", [*existing_ids, *loan_ids])
                for table in ("loan_approvals", "loan_rollovers", "loan_fines", "guarantor_locks", "loan_repayments"):
                    conn.execute(f"DELETE FROM {table} WHERE loan_id IN ({loan_marks})", loan_ids)
                conn.execute(f"DELETE FROM mpesa_receipts WHERE user_id IN ({marks})", existing_ids)
                conn.execute(f"DELETE FROM loans WHERE id IN ({loan_marks})", loan_ids)
            conn.execute(f"DELETE FROM guarantor_locks WHERE guarantor_id IN ({marks})", existing_ids)
            conn.execute(f"DELETE FROM mpesa_payments WHERE user_id IN ({marks})", existing_ids)
            for table in ("notifications", "dividend_allocations", "monthly_obligations", "wallet_transactions", "wallet_accounts", "savings"):
                conn.execute(f"DELETE FROM {table} WHERE user_id IN ({marks})", existing_ids)
            conn.execute(f"DELETE FROM users WHERE id IN ({marks})", existing_ids)

        password_hash = generate_password_hash("password123")
        imported_at = f"{date.today().isoformat()} 00:00:00"
        for member in members:
            email = f"legacy{member['legacy_id']:03d}@antiqsacco.local"
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash, full_name, phone, role, date_joined, monthly_contribution) VALUES (?, ?, ?, NULL, 'member', ?, 5000)",
                (email, password_hash, member["name"], imported_at),
            )
            user_id = cursor.lastrowid
            conn.execute("INSERT INTO wallet_accounts (user_id, balance, updated_at) VALUES (?, 0, ?)", (user_id, imported_at))

            for entry in member["monthly_savings"]:
                next_month = date(IMPORT_YEAR + (entry["month"] == 12), 1 if entry["month"] == 12 else entry["month"] + 1, 1)
                month_end = (next_month - date.resolution).isoformat()
                conn.execute(
                    "INSERT INTO savings (user_id, date, amount, transaction_type, recorded_by) VALUES (?, ?, ?, 'legacy_monthly_contribution', ?)",
                    (user_id, f"{month_end} 23:59:59", entry["amount"], admin_id),
                )

            if member["declared_dividend"] > 0:
                conn.execute(
                    "INSERT INTO dividend_allocations (user_id, year, amount, status, created_at) VALUES (?, ?, ?, 'declared', ?)",
                    (user_id, DIVIDEND_YEAR, member["declared_dividend"], imported_at),
                )

            loan = member["loan"]
            if loan["principal"] > 0 and loan["payable"] > 0:
                interest_rate = round(loan["interest"] * 100 / loan["principal"], 4)
                interest_paid = min(loan["paid"], loan["interest"])
                principal_paid = min(loan["principal"], max(0, loan["paid"] - interest_paid))
                principal_due = round(max(0, loan["principal"] - principal_paid), 2)
                interest_due = round(max(0, loan["interest"] - interest_paid), 2)
                status = "approved" if loan["due"] > 0 else "fully_paid"
                loan_cursor = conn.execute(
                    "INSERT INTO loans (user_id, principal_amount, interest_rate, duration_months, total_payable, balance_due, status, applied_date, reviewed_by, principal_balance, interest_due, cycle_due_date) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, loan["principal"], interest_rate, loan["payable"], loan["due"], status, imported_at, admin_id, principal_due, interest_due, date.today().isoformat()),
                )
                if loan["paid"] > 0:
                    conn.execute(
                        "INSERT INTO loan_repayments (loan_id, date, amount_paid, recorded_by, interest_paid, principal_paid, payment_type) VALUES (?, ?, ?, ?, ?, ?, 'legacy_import')",
                        (loan_cursor.lastrowid, imported_at, loan["paid"], admin_id, interest_paid, principal_paid),
                    )
                if loan["due"] == 0:
                    conn.execute("UPDATE loans SET principal_balance = 0, interest_due = 0 WHERE id = ?", (loan_cursor.lastrowid,))

            if member["loan"]["credit"] > 0:
                credit = member["loan"]["credit"]
                conn.execute("UPDATE wallet_accounts SET balance = balance + ?, updated_at = ? WHERE user_id = ?", (credit, imported_at, user_id))
                conn.execute(
                    "INSERT INTO wallet_transactions (user_id, date, amount, transaction_type, reference, note) VALUES (?, ?, ?, 'legacy_loan_credit', ?, ?)",
                    (user_id, imported_at, credit, f"LEGACY-CREDIT-{member['legacy_id']}", "Overpayment credit imported from Loans (2)"),
                )

        conn.execute("DELETE FROM dividend_runs WHERE year = ?", (DIVIDEND_YEAR,))
        conn.execute(
            "INSERT OR IGNORE INTO dividend_runs (year, profit_pool, distributed_at) VALUES (?, ?, ?)",
            (DIVIDEND_YEAR, round(sum(member["declared_dividend"] for member in members), 2), imported_at),
        )
        conn.commit()
        return backup
    except Exception:
        conn.rollback()
        if backup:
            shutil.copy2(backup, DB_PATH)
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Preview or import Antiq SACCO legacy XLSB records.")
    parser.add_argument("--apply", action="store_true", help="Back up and replace demo member/ledger records with workbook records.")
    args = parser.parse_args()
    members, totals = build_preview()
    print("IMPORT PREVIEW")
    for key, value in totals.items():
        print(f"{key}: {value}")
    print("No Excel phone numbers/emails are available; accounts will use legacy<ID>@antiqsacco.local and password password123.")
    print("Saving month entries are dated at month end because no day is recorded in the source workbook.")
    print("Loans are imported using Loans (2); balance is recalculated as payable minus paid, and excess paid is wallet credit.")
    print("Repayments sheet rows are not separately imported to avoid double counting the loan-sheet paid amounts.")
    if args.apply:
        backup = import_records(members)
        print(f"Imported {len(members)} members. Database backup: {backup or 'no existing database'}")
    else:
        print("Preview only. No database changes were made. Run with --apply after approving these totals.")


if __name__ == "__main__":
    main()