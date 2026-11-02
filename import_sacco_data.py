# name=import_sacco_data.py
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

DB_PATH = Path(__file__).parent / "instance" / "sacco.db"

# 1. Savings & Limits Dataset (29 Members)
SAVINGS_DATA = [
    (1, "JOEL RIOBA", 6000.0, 6200.0, 7000.0, 3000.0, 3300.0, 28500.0, 85500.0, 57000.0),
    (2, "COSMAS KOSGEY", 1000.0, 1000.0, 3000.0, 1000.0, 1000.0, 8000.0, 24000.0, 16000.0),
    (3, "OSCAR WEKESA", 1000.0, 1400.0, 1000.0, 1200.0, 1000.0, 6600.0, 19800.0, 13200.0),
    (4, "JACKSON PAPU", 1000.0, 1000.0, 1400.0, 1800.0, 1000.0, 7200.0, 21600.0, 14400.0),
    (5, "PATRICK WEKESA", 1000.0, 1400.0, 1600.0, 1600.0, 1000.0, 7600.0, 22800.0, 15200.0),
    (6, "TITUS KIPROP", 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 12000.0, 36000.0, 24000.0),
    (7, "GERARD ONDARI", 5000.0, 5000.0, 5000.0, 1000.0, 1000.0, 18000.0, 54000.0, 36000.0),
    (8, "CORNELIUS KORES", 1000.0, 1000.0, 1000.0, 1600.0, 1000.0, 6600.0, 19800.0, 13200.0),
    (9, "COSMAS AMADI", 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 6000.0, 18000.0, 12000.0),
    (10, "SAMUEL ROTICH", 1000.0, 1400.0, 1500.0, 1400.0, 1000.0, 9300.0, 27900.0, 18600.0),
    (11, "LILIAN MENITO", 1000.0, 2000.0, 2200.0, 2000.0, 2000.0, 14200.0, 42600.0, 28400.0),
    (12, "MARTIN NDIKI", 1000.0, 2000.0, 2000.0, 1600.0, 2400.0, 11000.0, 33000.0, 22000.0),
    (13, "FRANK MUTUA", 1000.0, 4000.0, 1000.0, 3000.0, 2000.0, 12000.0, 36000.0, 24000.0),
    (14, "MWENDWA AUGUSTIN", 1000.0, 1600.0, 1000.0, 1000.0, 1000.0, 6600.0, 19800.0, 13200.0),
    (15, "KELVIN MUGOCHI", 2000.0, 2200.0, 3400.0, 2000.0, 2000.0, 14600.0, 43800.0, 29200.0),
    (16, "SYLVESTER AMIANI", 1000.0, 1800.0, 1400.0, 1000.0, 2000.0, 10000.0, 30000.0, 20000.0),
    (17, "JULIUS NYERERE", 1000.0, 1000.0, 2200.0, 1200.0, 3800.0, 10600.0, 31800.0, 21200.0),
    (18, "JOHN WANYOIKE", 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 12000.0, 36000.0, 24000.0),
    (19, "KENNETH IRERI", 4000.0, 4000.0, 9100.0, 6000.0, 1000.0, 28100.0, 84300.0, 48200.0),
    (20, "EMMANUEL WANYAMA", 5000.0, 2000.0, 3000.0, 2000.0, 2000.0, 15400.0, 46200.0, 30800.0),
    (21, "DERICK ONYANGO", 1000.0, 1400.0, 5000.0, 1000.0, 1000.0, 10400.0, 31200.0, 20800.0),
    (22, "MICHEAL ODUOR", 2000.0, 5000.0, 2000.0, 2000.0, 1000.0, 13000.0, 39000.0, 26000.0),
    (23, "KIPLIMO KELVIN", 1000.0, 1400.0, 1000.0, 1000.0, 1000.0, 6400.0, 19200.0, 12800.0),
    (24, "GEOFRY MOKAYA", 1000.0, 4000.0, 4000.0, 1800.0, 1200.0, 14000.0, 42000.0, 28000.0),
    (25, "KIPYEGON PHANUEL", 2000.0, 5400.0, 3000.0, 2200.0, 2600.0, 17700.0, 53100.0, 35400.0),
    (26, "MICHEAL BULUKU", 1000.0, 5400.0, 1000.0, 1000.0, 1000.0, 9400.0, 28200.0, 18800.0),
    (27, "BRIAN SITE", 1000.0, 1000.0, 1200.0, 1000.0, 1000.0, 5200.0, 15600.0, 10400.0),
    (28, "ALLAN KIRUEI", 3000.0, 2000.0, 5000.0, 1000.0, 1000.0, 12000.0, 36000.0, 24000.0),
    (29, "NICHOLUS KILEL", 1500.0, 5200.0, 1000.0, 1400.0, 1400.0, 10500.0, 31500.0, 21000.0),
]

# 2. Loan Ledger Dataset (June to September activity)
LOAN_LEDGER_DATA = [
    (1, 1000.0, 15000.0, 5000.0, 3000.0, 10000.0, 3000.0, 2000.0, 7000.0),
    (2, 2000.0, 2000.0, 0.0, 0.0, 3000.0, 0.0, 600.0, 6000.0),
    (3, 2000.0, 5000.0, 0.0, 0.0, 5000.0, 0.0, 1000.0, 5000.0),
    (4, 2000.0, 10000.0, 5000.0, 2000.0, 5000.0, 4000.0, 1000.0, 9000.0),
    (5, 2000.0, 7000.0, 0.0, 0.0, 8000.0, 0.0, 1600.0, 4000.0),
    (6, 2000.0, 3000.0, 0.0, 0.0, 4000.0, 0.0, 800.0, 5000.0),
    (7, 4000.0, 20000.0, 0.0, 4000.0, 27500.0, 3000.0, 5500.0, 30000.0),
    (8, 5000.0, 10000.0, 0.0, 0.0, 16000.0, 6000.0, 3200.0, 10000.0),
    (9, 5000.0, 15000.0, 0.0, 0.0, 10000.0, 0.0, 2000.0, 0.0),
    (10, 5000.0, 1000.0, 0.0, 0.0, 20000.0, 8000.0, 4000.0, 12000.0),
    (11, 5000.0, 10000.0, 3000.0, 2000.0, 7000.0, 0.0, 1400.0, 7000.0),
    (12, 6000.0, 4000.0, 0.0, 0.0, 10000.0, 5000.0, 2000.0, 5000.0),
    (13, 8000.0, 8500.0, 0.0, 1700.0, 10500.0, 7500.0, 2100.0, 3000.0),
    (14, 7000.0, 10500.0, 0.0, 2100.0, 10500.0, 1000.0, 2100.0, 9500.0),
    (15, 8000.0, 10000.0, 0.0, 2000.0, 20000.0, 0.0, 4000.0, 28000.0),
    (16, 9000.0, 15000.0, 3000.0, 3000.0, 12000.0, 2000.0, 2400.0, 10000.0),
    (17, 10000.0, 14000.0, 0.0, 2800.0, 20000.0, 3000.0, 4000.0, 17000.0),
    (18, 10000.0, 10000.0, 0.0, 0.0, 15000.0, 0.0, 3000.0, 15000.0),
    (19, 10000.0, 20000.0, 0.0, 4000.0, 25000.0, 12000.0, 5000.0, 13000.0),
    (20, 10000.0, 10000.0, 0.0, 0.0, 52000.0, 50000.0, 10000.0, 25400.0),
    (21, 10000.0, 15000.0, 2000.0, 3000.0, 13000.0, 0.0, 0.0, 15600.0),
    (22, 11000.0, 20000.0, 0.0, 4000.0, 20000.0, 1000.0, 4000.0, 19000.0),
    (23, 13000.0, 13000.0, 0.0, 2600.0, 13000.0, 0.0, 2600.0, 13000.0),
    (24, 15000.0, 15000.0, 0.0, 3000.0, 15000.0, 1000.0, 3000.0, 14000.0),
    (25, 20000.0, 20000.0, 0.0, 4000.0, 20000.0, 0.0, 4000.0, 70000.0),
    (26, 10000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    (27, 25000.0, 25000.0, 0.0, 5000.0, 25000.0, 0.0, 0.0, 30000.0),
    (28, 4000.0, 11000.0, 3000.0, 2200.0, 8000.0, 2000.0, 1600.0, 9000.0),
    (29, 5000.0, 5000.0, 0.0, 1000.0, 30000.0, 0.0, 0.0, 30000.0),
]

def run_import():
    if not DB_PATH.exists():
        print(f"Error: Database file not found at {DB_PATH}. Run init_db.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("--- Starting Sacco Spreadsheet Import ---")

    default_pwd = generate_password_hash("password123")

    # Temporarily disable foreign keys to cleanly clear dependent loan records
    cursor.execute("PRAGMA foreign_keys = OFF;")

    # 1. Insert/Update all 29 Members and their Savings
    for row in SAVINGS_DATA:
        member_id, name, may, june, july, aug, sept, total_sav, x3_lim, x2_lim = row
        email = f"member{member_id:03d}@antiqsacco.local"
        username = email
        phone = f"254700000{member_id:02d}"

        cursor.execute(
            """
            INSERT INTO users (id, username, email, password_hash, full_name, phone, role, is_super_admin, must_change_password, date_joined)
            VALUES (?, ?, ?, ?, ?, ?, 'member', 0, 1, '2026-05-01 00:00:00')
            ON CONFLICT(id) DO UPDATE SET 
                full_name = excluded.full_name, 
                email = excluded.email, 
                username = excluded.username;
            """,
            (member_id, username, email, default_pwd, name, phone)
        )

        cursor.execute("DELETE FROM savings WHERE user_id = ? AND transaction_type = 'spreadsheet_import'", (member_id,))

        monthly_savings = [
            ("2026-05-31 12:00:00", may, "MAY"),
            ("2026-06-30 12:00:00", june, "JUNE"),
            ("2026-07-31 12:00:00", july, "JULY"),
            ("2026-08-31 12:00:00", aug, "AUG"),
            ("2026-09-30 12:00:00", sept, "SEPT"),
        ]
        for d_str, amt, m_lbl in monthly_savings:
            if amt > 0:
                cursor.execute(
                    """
                    INSERT INTO savings (user_id, date, amount, transaction_type, reference)
                    VALUES (?, ?, ?, 'spreadsheet_import', ?)
                    """,
                    (member_id, d_str, amt, f"SAV-{member_id}-{m_lbl}")
                )

        cursor.execute(
            """
            INSERT OR IGNORE INTO wallet_accounts (user_id, balance, updated_at)
            VALUES (?, 0, '2026-09-30 12:00:00')
            """,
            (member_id,)
        )

    # 2. Clear dependent child tables and loans safely
    cursor.execute("DELETE FROM loan_repayments")
    cursor.execute("DELETE FROM loan_approvals")
    cursor.execute("DELETE FROM guarantor_locks")
    cursor.execute("DELETE FROM loan_fines")
    cursor.execute("DELETE FROM loans")

    for loan_row in LOAN_LEDGER_DATA:
        m_id, jn_loan, jl_loan, jl_rep, jl_int, ag_loan, ag_rep, ag_int, st_loan = loan_row

        # June Loan (Fully Settled)
        if jn_loan > 0:
            tot = jn_loan * 1.2
            cursor.execute(
                """
                INSERT INTO loans (user_id, principal_amount, interest_rate, duration_months, total_payable, balance_due, status, applied_date, principal_balance, interest_due)
                VALUES (?, ?, 20.0, 1, ?, 0, 'fully_paid', '2026-06-01 00:00:00', 0, 0)
                """,
                (m_id, jn_loan, tot)
            )

        # July Loan
        if jl_loan > 0:
            is_settled = (jl_rep > 0 or jl_int > 0 or (jl_rep == 0 and jl_int == 0))
            status = 'fully_paid' if is_settled else 'approved'
            tot = jl_loan * 1.2
            bal = 0 if is_settled else tot
            p_bal = 0 if is_settled else jl_loan
            i_due = 0 if is_settled else jl_loan * 0.2

            cursor.execute(
                """
                INSERT INTO loans (user_id, principal_amount, interest_rate, duration_months, total_payable, balance_due, status, applied_date, principal_balance, interest_due)
                VALUES (?, ?, 20.0, 1, ?, ?, ?, '2026-07-01 00:00:00', ?, ?)
                """,
                (m_id, jl_loan, tot, bal, status, p_bal, i_due)
            )
            if is_settled and (jl_rep > 0 or jl_int > 0):
                l_id = cursor.lastrowid
                cursor.execute(
                    """
                    INSERT INTO loan_repayments (loan_id, date, amount_paid, interest_paid, principal_paid, payment_type, reference)
                    VALUES (?, '2026-07-31 12:00:00', ?, ?, ?, 'full', ?)
                    """,
                    (l_id, jl_rep + jl_int, jl_int, jl_rep, f"JUL-REP-{m_id}")
                )

        # August Loan
        if ag_loan > 0:
            is_settled = (ag_rep > 0 or ag_int > 0 or (ag_rep == 0 and ag_int == 0))
            status = 'fully_paid' if is_settled else 'approved'
            tot = ag_loan * 1.2
            bal = 0 if is_settled else tot
            p_bal = 0 if is_settled else ag_loan
            i_due = 0 if is_settled else ag_loan * 0.2

            cursor.execute(
                """
                INSERT INTO loans (user_id, principal_amount, interest_rate, duration_months, total_payable, balance_due, status, applied_date, principal_balance, interest_due)
                VALUES (?, ?, 20.0, 1, ?, ?, ?, '2026-08-01 00:00:00', ?, ?)
                """,
                (m_id, ag_loan, tot, bal, status, p_bal, i_due)
            )
            if is_settled and (ag_rep > 0 or ag_int > 0):
                l_id = cursor.lastrowid
                cursor.execute(
                    """
                    INSERT INTO loan_repayments (loan_id, date, amount_paid, interest_paid, principal_paid, payment_type, reference)
                    VALUES (?, '2026-08-31 12:00:00', ?, ?, ?, 'full', ?)
                    """,
                    (l_id, ag_rep + ag_int, ag_int, ag_rep, f"AUG-REP-{m_id}")
                )

        # September Loan (Active current cycle)
        if st_loan > 0:
            tot = st_loan * 1.2
            cursor.execute(
                """
                INSERT INTO loans (user_id, principal_amount, interest_rate, duration_months, total_payable, balance_due, status, applied_date, principal_balance, interest_due)
                VALUES (?, ?, 20.0, 1, ?, ?, 'approved', '2026-09-01 00:00:00', ?, ?)
                """,
                (m_id, st_loan, tot, tot, st_loan, st_loan * 0.2)
            )

    # Re-enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")

    conn.commit()
    conn.close()
    print("SUCCESS: All 29 members, savings, and loan ledgers imported successfully into SQLite!")

if __name__ == "__main__":
    run_import()