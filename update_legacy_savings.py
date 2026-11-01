import argparse
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from init_db import DB_PATH, get_conn


SOURCE = Path(r"C:\Users\Godigs\Downloads\ANTIQ SACCO FORMULA 2.xlsx")
IMPORT_YEAR = 2026
NEW_MONTH_COLUMNS = ((9, 8, "August"), (10, 9, "September"), (11, 10, "October"))


def number(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def load_additions():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Workbook not found: {SOURCE}")
    workbook = load_workbook(SOURCE, read_only=True, data_only=True)
    sheet = workbook["Savings"]
    additions = []
    month_totals = {name: 0.0 for _, _, name in NEW_MONTH_COLUMNS}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or not isinstance(row[0], (int, float)) or len(row) <= 14:
            continue
        legacy_id = int(row[0])
        full_name = str(row[1] or "").strip()
        entries = []
        for column, month, month_name in NEW_MONTH_COLUMNS:
            amount = number(row[column])
            if amount > 0:
                entries.append({"month": month, "month_name": month_name, "amount": amount})
                month_totals[month_name] += amount
        additions.append({
            "legacy_id": legacy_id,
            "full_name": full_name,
            "reported_total": number(row[14]),
            "entries": entries,
            "new_amount": round(sum(item["amount"] for item in entries), 2),
        })
    workbook.close()
    return additions, {key: round(value, 2) for key, value in month_totals.items()}


def build_preview():
    additions, month_totals = load_additions()
    conn = get_conn()
    try:
        members = {
            row["full_name"].strip().casefold(): row
            for row in conn.execute("SELECT id, full_name FROM users WHERE role = 'member'")
        }
        preview = []
        for entry in additions:
            user = members.get(entry["full_name"].casefold())
            if user is None:
                raise ValueError(f"No live member matches workbook name: {entry['full_name']}")
            current_savings = number(conn.execute("SELECT COALESCE(SUM(amount), 0) FROM savings WHERE user_id = ?", (user["id"],)).fetchone()[0])
            already_posted = 0.0
            for item in entry["entries"]:
                reference = f"XLSX2-{IMPORT_YEAR}-{item['month']:02d}-{entry['legacy_id']:03d}"
                exists = conn.execute("SELECT 1 FROM savings WHERE reference = ?", (reference,)).fetchone()
                if exists:
                    already_posted += item["amount"]
            expected_before_new_months = round(entry["reported_total"] - entry["new_amount"], 2)
            if abs(current_savings - expected_before_new_months) > 0.01:
                raise ValueError(
                    f"Savings reconciliation failed for {entry['full_name']}: live KSh {current_savings:,.2f}, "
                    f"expected KSh {expected_before_new_months:,.2f} before August-October entries."
                )
            preview.append({
                **entry,
                "user_id": user["id"],
                "current_savings": current_savings,
                "already_posted": round(already_posted, 2),
                "to_import": round(entry["new_amount"] - already_posted, 2),
            })
        return preview, month_totals
    finally:
        conn.close()


def make_backup():
    database_path = Path(DB_PATH)
    if not database_path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = database_path.with_name(f"sacco-before-xlsx2-update-{stamp}.db")
    with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


def apply_additions(preview):
    backup_path = make_backup()
    conn = get_conn()
    added_count = 0
    added_total = 0.0
    try:
        conn.execute("BEGIN IMMEDIATE")
        admin = conn.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
        if admin is None:
            raise RuntimeError("An admin account is required to record legacy savings entries.")
        for member in preview:
            for item in member["entries"]:
                reference = f"XLSX2-{IMPORT_YEAR}-{item['month']:02d}-{member['legacy_id']:03d}"
                exists = conn.execute("SELECT 1 FROM savings WHERE reference = ?", (reference,)).fetchone()
                if exists:
                    continue
                next_month = date(IMPORT_YEAR + (item["month"] == 12), 1 if item["month"] == 12 else item["month"] + 1, 1)
                month_end = (next_month - date.resolution).isoformat()
                conn.execute(
                    "INSERT INTO savings (user_id, date, amount, transaction_type, recorded_by, reference) VALUES (?, ?, ?, 'legacy_monthly_contribution', ?, ?)",
                    (member["user_id"], f"{month_end} 23:59:59", item["amount"], admin["id"], reference),
                )
                added_count += 1
                added_total += item["amount"]
        conn.commit()
        return backup_path, added_count, round(added_total, 2)
    except Exception:
        conn.rollback()
        if backup_path:
            shutil.copy2(backup_path, DB_PATH)
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Preview or append August-October 2026 savings from the updated XLSX.")
    parser.add_argument("--apply", action="store_true", help="Back up and append only the reconciled new monthly savings entries.")
    args = parser.parse_args()
    preview, month_totals = build_preview()
    print("ADDITIVE SAVINGS UPDATE PREVIEW")
    print(f"Workbook: {SOURCE}")
    print(f"Existing members matched: {len(preview)}")
    print(f"Source months: August-October {IMPORT_YEAR} (corrected for the duplicated APR header)")
    print(f"By month: {month_totals}")
    print(f"Additional savings total: KSh {sum(member['new_amount'] for member in preview):,.2f}")
    print(f"Already present from this update: KSh {sum(member['already_posted'] for member in preview):,.2f}")
    print(f"New amount to post: KSh {sum(member['to_import'] for member in preview):,.2f}")
    print("Loan records and declared dividends will not be changed by this update.")
    if args.apply:
        backup, count, total = apply_additions(preview)
        print(f"Added {count} monthly savings entries totaling KSh {total:,.2f}.")
        print(f"Database backup: {backup}")
    else:
        print("Preview only. No database changes were made. Add --apply to post these entries.")


if __name__ == "__main__":
    main()