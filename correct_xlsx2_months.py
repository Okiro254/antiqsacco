import argparse
import shutil
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

from init_db import DB_PATH, get_conn


PREFIX = "XLSX2-2026-"
MONTH_SHIFT = {7: 8, 8: 9, 9: 10}


def build_preview():
    conn = get_conn()
    try:
        entries = []
        for old_month, new_month in MONTH_SHIFT.items():
            old_prefix = f"{PREFIX}{old_month:02d}-%"
            rows = conn.execute(
                "SELECT id, user_id, date, amount, reference FROM savings WHERE reference LIKE ? ORDER BY user_id, id",
                (old_prefix,),
            ).fetchall()
            for row in rows:
                old_reference = row["reference"]
                new_reference = old_reference.replace(f"{PREFIX}{old_month:02d}-", f"{PREFIX}{new_month:02d}-", 1)
                next_month = date(2026 + (new_month == 12), 1 if new_month == 12 else new_month + 1, 1)
                new_date = f"{(next_month - date.resolution).isoformat()} 23:59:59"
                entries.append({
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "amount": round(float(row["amount"]), 2),
                    "old_reference": old_reference,
                    "new_reference": new_reference,
                    "old_date": row["date"],
                    "new_date": new_date,
                    "old_month": old_month,
                    "new_month": new_month,
                })
        selected_ids = {entry["id"] for entry in entries}
        for entry in entries:
            collision = conn.execute(
                "SELECT id FROM savings WHERE reference = ? AND id != ?",
                (entry["new_reference"], entry["id"]),
            ).fetchone()
            if collision and collision["id"] not in selected_ids:
                conflicting = conn.execute(
                    "SELECT id, user_id, date, amount, reference FROM savings WHERE id = ?",
                    (collision["id"],),
                ).fetchone()
                raise ValueError(
                    f"Reference collision while remapping {entry['old_reference']} to {entry['new_reference']}: "
                    f"existing row id={conflicting['id']} user_id={conflicting['user_id']} "
                    f"date={conflicting['date']} amount={conflicting['amount']} reference={conflicting['reference']}."
                )
        current = conn.execute(
            "SELECT substr(date, 1, 7) AS period, COUNT(*) AS count, ROUND(SUM(amount), 2) AS total FROM savings GROUP BY substr(date, 1, 7) ORDER BY period"
        ).fetchall()
        after = {}
        for row in current:
            after[row["period"]] = {"count": row["count"], "total": float(row["total"] or 0)}
        for entry in entries:
            old_period = entry["old_date"][:7]
            new_period = entry["new_date"][:7]
            after[old_period]["count"] -= 1
            after[old_period]["total"] -= entry["amount"]
            after.setdefault(new_period, {"count": 0, "total": 0.0})
            after[new_period]["count"] += 1
            after[new_period]["total"] += entry["amount"]
        return entries, current, after
    finally:
        conn.close()


def make_backup():
    path = Path(DB_PATH)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"sacco-before-cycle-month-correction-{timestamp}.db")
    with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    return backup


def apply_correction(entries):
    backup = make_backup()
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        batch_token = uuid.uuid4().hex
        for entry in entries:
            conn.execute(
                "UPDATE savings SET reference = ? WHERE id = ? AND reference = ?",
                (f"CORRECTING-{batch_token}-{entry['id']}", entry["id"], entry["old_reference"]),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                raise RuntimeError(f"Entry changed during correction: {entry['old_reference']}.")
        for entry in entries:
            conn.execute(
                "UPDATE savings SET date = ?, reference = ? WHERE id = ? AND reference = ?",
                (entry["new_date"], entry["new_reference"], entry["id"], f"CORRECTING-{batch_token}-{entry['id']}"),
            )
        conn.commit()
        return backup
    except Exception:
        conn.rollback()
        shutil.copy2(backup, DB_PATH)
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Preview or correct XLSX2 month labels shifted by its duplicated April header.")
    parser.add_argument("--apply", action="store_true", help="Back up and shift only XLSX2 July-September entries to August-October.")
    args = parser.parse_args()
    entries, before, after = build_preview()
    print("MONTH-LABEL CORRECTION PREVIEW")
    print(f"Rows to remap: {len(entries)}; amount affected: KSh {sum(row['amount'] for row in entries):,.2f}")
    print("Interpretation: the source has duplicate April labels; the three new month columns follow the existing May-July ledger sequence, so their values map to Aug-Oct.")
    print("Totals by month before:", [(row["period"], row["count"], round(float(row["total"] or 0), 2)) for row in before])
    print("Totals by month after:", [(period, values["count"], round(values["total"], 2)) for period, values in sorted(after.items()) if values["count"]])
    print("Total savings is unchanged. Loans and dividends are unchanged.")
    if args.apply:
        backup = apply_correction(entries)
        print(f"Corrected {len(entries)} ledger dates. Backup: {backup}")
    else:
        print("Preview only. No database changes were made.")


if __name__ == "__main__":
    main()