import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from init_db import DB_PATH


def export_database(output_path):
    source_path = Path(DB_PATH)
    if not source_path.exists():
        raise FileNotFoundError(f"Database not found: {source_path}")
    destination_path = Path(output_path).expanduser().resolve()
    if destination_path == source_path.resolve():
        raise ValueError("Output must be a separate backup file, not the live database path.")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source, sqlite3.connect(destination_path) as destination:
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Live database integrity check failed: {integrity}")
        source.backup(destination)
    with sqlite3.connect(destination_path) as snapshot:
        counts = {
            "members": snapshot.execute("SELECT COUNT(*) FROM users WHERE role = 'member'").fetchone()[0],
            "admins": snapshot.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0],
            "savings_rows": snapshot.execute("SELECT COUNT(*) FROM savings").fetchone()[0],
            "loan_rows": snapshot.execute("SELECT COUNT(*) FROM loans").fetchone()[0],
            "repayment_rows": snapshot.execute("SELECT COUNT(*) FROM loan_repayments").fetchone()[0],
        }
        integrity = snapshot.execute("PRAGMA integrity_check").fetchone()[0]
    return destination_path, counts, integrity


def main():
    parser = argparse.ArgumentParser(description="Create a consistent SQLite transfer backup for Antiq Sacco.")
    parser.add_argument("--output", help="Destination .db file. Defaults to a timestamped backup in instance/.")
    args = parser.parse_args()
    destination = args.output or str(Path(DB_PATH).with_name(f"antiq-transfer-{datetime.now():%Y%m%d-%H%M%S}.db"))
    output_path, counts, integrity = export_database(destination)
    print(f"Export created: {output_path}")
    print(f"Integrity: {integrity}")
    for key, value in counts.items():
        print(f"{key}: {value}")
    print("This file contains member personal and financial data. Keep it private and do not commit it to GitHub.")


if __name__ == "__main__":
    main()
