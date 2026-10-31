import os
import sqlite3
from datetime import date, datetime
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "sacco.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT,
            role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
            is_super_admin INTEGER NOT NULL DEFAULT 0,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            date_joined TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS savings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            transaction_type TEXT NOT NULL DEFAULT 'deposit',
            recorded_by INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (recorded_by) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            principal_amount NUMERIC NOT NULL,
            interest_rate NUMERIC NOT NULL,
            duration_months INTEGER NOT NULL,
            total_payable NUMERIC NOT NULL,
            balance_due NUMERIC NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'fully_paid')),
            applied_date TEXT NOT NULL,
            reviewed_by INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (reviewed_by) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS loan_repayments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount_paid NUMERIC NOT NULL,
            recorded_by INTEGER,
            FOREIGN KEY (loan_id) REFERENCES loans(id),
            FOREIGN KEY (recorded_by) REFERENCES users(id)
        )
    """)

    c.executescript("""
        CREATE TABLE IF NOT EXISTS wallet_accounts (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            balance NUMERIC NOT NULL DEFAULT 0 CHECK (balance >= 0),
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            date TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            transaction_type TEXT NOT NULL,
            reference TEXT UNIQUE,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS monthly_obligations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            period TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'due',
            processed_at TEXT,
            UNIQUE (user_id, period)
        );
        CREATE TABLE IF NOT EXISTS loan_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL REFERENCES loans(id),
            official_id INTEGER NOT NULL REFERENCES users(id),
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
            date TEXT NOT NULL,
            UNIQUE (loan_id, official_id)
        );
        CREATE TABLE IF NOT EXISTS loan_rollovers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL REFERENCES loans(id),
            date TEXT NOT NULL,
            interest_paid NUMERIC NOT NULL,
            principal_paid NUMERIC NOT NULL,
            principal_remaining NUMERIC NOT NULL,
            new_due_date TEXT NOT NULL,
            recorded_by INTEGER REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS loan_fines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL REFERENCES loans(id),
            period TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            date TEXT NOT NULL,
            UNIQUE (loan_id, period)
        );
        CREATE TABLE IF NOT EXISTS guarantor_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL REFERENCES loans(id),
            guarantor_id INTEGER NOT NULL REFERENCES users(id),
            amount NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            UNIQUE (loan_id, guarantor_id)
        );
        CREATE TABLE IF NOT EXISTS mpesa_receipts (
            receipt_number TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            amount NUMERIC NOT NULL,
            phone TEXT,
            received_at TEXT NOT NULL,
            savings_id INTEGER REFERENCES savings(id)
        );
        CREATE TABLE IF NOT EXISTS mpesa_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checkout_request_id TEXT UNIQUE,
            merchant_request_id TEXT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            payment_type TEXT NOT NULL,
            loan_id INTEGER REFERENCES loans(id),
            requested_amount NUMERIC NOT NULL,
            phone TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            receipt_number TEXT UNIQUE,
            result_description TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            channel TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            provider_reference TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT
        );
        CREATE TABLE IF NOT EXISTS dividend_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL UNIQUE,
            profit_pool NUMERIC NOT NULL,
            distributed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dividend_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            year INTEGER NOT NULL,
            amount NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'declared',
            created_at TEXT NOT NULL,
            UNIQUE (user_id, year)
        );
    """)

    user_columns = {row[1] for row in c.execute("PRAGMA table_info(users)")}
    if "username" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN username TEXT")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    if "is_super_admin" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN is_super_admin INTEGER NOT NULL DEFAULT 0")
    if "must_change_password" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        c.execute("UPDATE users SET must_change_password = 1 WHERE role = 'member'")
    if "monthly_contribution" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN monthly_contribution NUMERIC NOT NULL DEFAULT 5000")
    loan_columns = {row[1] for row in c.execute("PRAGMA table_info(loans)")}
    for column, declaration in {
        "principal_balance": "NUMERIC NOT NULL DEFAULT 0",
        "interest_due": "NUMERIC NOT NULL DEFAULT 0",
        "cycle_due_date": "TEXT",
        "rollover_count": "INTEGER NOT NULL DEFAULT 0",
        "guarantor_id": "INTEGER REFERENCES users(id)",
    }.items():
        if column not in loan_columns:
            c.execute(f"ALTER TABLE loans ADD COLUMN {column} {declaration}")
    repayment_columns = {row[1] for row in c.execute("PRAGMA table_info(loan_repayments)")}
    for column in ("interest_paid", "principal_paid", "payment_type"):
        if column not in repayment_columns:
            declaration = "TEXT NOT NULL DEFAULT 'full'" if column == "payment_type" else "NUMERIC NOT NULL DEFAULT 0"
            c.execute(f"ALTER TABLE loan_repayments ADD COLUMN {column} {declaration}")
    savings_columns = {row[1] for row in c.execute("PRAGMA table_info(savings)")}
    if "reference" not in savings_columns:
        c.execute("ALTER TABLE savings ADD COLUMN reference TEXT")
    if "reference" not in repayment_columns:
        c.execute("ALTER TABLE loan_repayments ADD COLUMN reference TEXT")

    conn.commit()

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] > 0:
        c.execute(
            "INSERT OR IGNORE INTO wallet_accounts (user_id, balance, updated_at) SELECT id, 0, ? FROM users",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),),
        )
        conn.commit()
        conn.close()
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pw = generate_password_hash("password123")

    # Primary administrator
    c.execute(
            "INSERT INTO users (email, password_hash, full_name, phone, role, must_change_password, date_joined) VALUES (?,?,?,?,?,?,?)",
        ("admin@sacco.co.ke", pw, "System Administrator", "+254700000000", "admin", 0, now),
    )
    admin_id = c.lastrowid

    # Seed a mockup roster of 30 SACCO members
    member_ids = []
    for i in range(1, 31):
        c.execute(
            "INSERT INTO users (email, password_hash, full_name, phone, role, must_change_password, date_joined) VALUES (?,?,?,?,?,?,?)",
            (f"member{i:02d}@sacco.co.ke", pw, f"Member {i:02d}", f"+254700{i:07d}", "member", 1, now),
        )
        member_ids.append(c.lastrowid)

    c.execute(
        "INSERT INTO wallet_accounts (user_id, balance, updated_at) SELECT id, 0, ? FROM users",
        (now,),
    )

    # Primary demo member with an active savings ledger
    main_member = member_ids[0]
    for date_str, amt in [
        ("2024-01-15 09:00:00", 50000),
        ("2024-02-15 09:00:00", 50000),
        ("2024-03-15 09:00:00", 50000),
    ]:
        c.execute(
            "INSERT INTO savings (user_id, date, amount, transaction_type, recorded_by) VALUES (?,?,?,?,?)",
            (main_member, date_str, amt, "deposit", admin_id),
        )

    # A pending loan application awaiting underwriting
    c.execute(
        """
        INSERT INTO loans (user_id, principal_amount, interest_rate, duration_months, total_payable, balance_due, status, applied_date, reviewed_by, principal_balance)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (main_member, 100000, 20.0, 1, 0, 0, "pending", now, None, 100000),
    )

    conn.commit()
    conn.close()
    return True


if __name__ == "__main__":
    created = init_db()
    print("Database initialized successfully." if created else "Database already initialized.")
