import getpass
from datetime import datetime

from werkzeug.security import generate_password_hash

from init_db import get_conn, init_db


USERNAME = "Major"
EMAIL = "major@antiqsacco.local"
FULL_NAME = "Major"


def main():
    init_db()
    password = getpass.getpass("Set a fresh super-admin passkey (input hidden): ")
    confirmation = getpass.getpass("Confirm super-admin passkey: ")
    if len(password) < 12:
        raise SystemExit("Passkey must be at least 12 characters.")
    if password != confirmation:
        raise SystemExit("Passkeys did not match; no account changes were made.")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        matches = conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?)",
            (USERNAME, EMAIL),
        ).fetchall()
        if len(matches) > 1:
            raise SystemExit("Username/email match different accounts; contact the database administrator.")
        password_hash = generate_password_hash(password)
        if matches:
            account = matches[0]
            if account["role"] not in {"member", "admin"}:
                raise SystemExit("Matched account has an unsupported role.")
            conn.execute(
                "UPDATE users SET username = ?, email = ?, password_hash = ?, full_name = ?, role = 'member', is_super_admin = 1 WHERE id = ?",
                (USERNAME, EMAIL, password_hash, FULL_NAME, account["id"]),
            )
            user_id = account["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO users (username, email, password_hash, full_name, role, is_super_admin, date_joined, monthly_contribution) VALUES (?, ?, ?, ?, 'member', 1, ?, 5000)",
                (USERNAME, EMAIL, password_hash, FULL_NAME, now),
            )
            user_id = cursor.lastrowid
        conn.execute(
            "INSERT OR IGNORE INTO wallet_accounts (user_id, balance, updated_at) VALUES (?, 0, ?)",
            (user_id, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("Super-admin account is ready.")
    print(f"Username: {USERNAME}")
    print("The account also has member access. The passkey was hashed and not stored in source code.")


if __name__ == "__main__":
    main()