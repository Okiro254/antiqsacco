import json
import sqlite3
import sys

from openpyxl import load_workbook


def normalized(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


if len(sys.argv) != 2:
    raise SystemExit("Usage: python inspect_xlsx.py <workbook.xlsx>")

path = sys.argv[1]
workbook = load_workbook(path, read_only=True, data_only=True)
report = {"file": path, "sheets": {}}
rows_by_sheet = {}

for sheet in workbook.worksheets:
    nonempty = []
    columns = 0
    for row in sheet.iter_rows(values_only=True):
        values = list(row)
        while values and values[-1] is None:
            values.pop()
        columns = max(columns, len(values))
        if any(value is not None for value in values):
            nonempty.append(values)
    report["sheets"][sheet.title] = {
        "nonempty_rows": len(nonempty),
        "columns": columns,
        "header_or_first_row": [normalized(value) for value in nonempty[0]] if nonempty else [],
        "sample_rows": [[normalized(value) for value in row] for row in nonempty[1:4]],
    }
    rows_by_sheet[sheet.title] = nonempty


def numeric_member_rows(sheet_name):
    rows = rows_by_sheet.get(sheet_name, [])[1:]
    return [row for row in rows if row and isinstance(row[0], (int, float))]


def number(row, column):
    if len(row) <= column or row[column] is None:
        return 0.0
    try:
        return float(row[column])
    except (TypeError, ValueError):
        return 0.0


for sheet_name in ("Members", "Savings", "Loans (2)", "Loans", "Repayments", "Summary"):
    report["sheets"].setdefault(sheet_name, {})["numeric_member_rows"] = len(numeric_member_rows(sheet_name))

if "Savings" in rows_by_sheet:
    savings_rows = numeric_member_rows("Savings")
    savings_header = rows_by_sheet["Savings"][0]
    report["sheets"]["Savings"]["month_columns"] = [
        {"column": index + 1, "label": value}
        for index, value in enumerate(savings_header)
        if index >= 2 and index <= 13 and value is not None
    ]
    report["sheets"]["Savings"]["monthly_column_totals"] = {
        str(savings_header[index]) if index < len(savings_header) and savings_header[index] is not None else f"column_{index + 1}": round(sum(number(row, index) for row in savings_rows), 2)
        for index in range(2, 14)
    }
    report["sheets"]["Savings"]["member_month_cells_total"] = round(sum(number(row, index) for row in savings_rows for index in range(2, 14)), 2)
    report["sheets"]["Savings"]["reported_total_column"] = round(sum(number(row, 14) for row in savings_rows), 2)

for loan_sheet in ("Loans (2)", "Loans"):
    loan_rows = numeric_member_rows(loan_sheet)
    if loan_rows:
        total_payable = sum(number(row, 5) for row in loan_rows)
        total_paid = sum(number(row, 6) for row in loan_rows)
        report["sheets"][loan_sheet]["principal"] = round(sum(number(row, 2) for row in loan_rows), 2)
        report["sheets"][loan_sheet]["interest"] = round(sum(number(row, 4) for row in loan_rows), 2)
        report["sheets"][loan_sheet]["payable"] = round(total_payable, 2)
        report["sheets"][loan_sheet]["paid"] = round(total_paid, 2)
        report["sheets"][loan_sheet]["recalculated_due"] = round(sum(max(0, number(row, 5) - number(row, 6)) for row in loan_rows), 2)
        report["sheets"][loan_sheet]["recalculated_credit"] = round(sum(max(0, number(row, 6) - number(row, 5)) for row in loan_rows), 2)

if "Repayments" in rows_by_sheet:
    repayment_rows = numeric_member_rows("Repayments")
    report["sheets"]["Repayments"]["paid_total"] = round(sum(number(row, 3) for row in repayment_rows), 2)
    report["sheets"]["Repayments"]["penalty_total"] = round(sum(number(row, 7) for row in repayment_rows), 2)

if "Summary" in rows_by_sheet:
    summary_rows = numeric_member_rows("Summary")
    report["sheets"]["Summary"]["savings_total"] = round(sum(number(row, 2) for row in summary_rows), 2)
    report["sheets"]["Summary"]["interest_estimate_total"] = round(sum(number(row, 4) for row in summary_rows), 2)
    report["sheets"]["Summary"]["payout_total"] = round(sum(number(row, 7) for row in summary_rows), 2)

try:
    connection = sqlite3.connect("instance/sacco.db")
    connection.row_factory = sqlite3.Row
    report["live_database"] = {
        "members": connection.execute("SELECT COUNT(*) FROM users WHERE role = 'member'").fetchone()[0],
        "savings_transactions": connection.execute("SELECT COUNT(*) FROM savings").fetchone()[0],
        "savings_total": round(connection.execute("SELECT COALESCE(SUM(amount), 0) FROM savings").fetchone()[0], 2),
        "loan_records": connection.execute("SELECT COUNT(*) FROM loans").fetchone()[0],
        "loan_principal": round(connection.execute("SELECT COALESCE(SUM(principal_amount), 0) FROM loans").fetchone()[0], 2),
        "loan_due": round(connection.execute("SELECT COALESCE(SUM(balance_due), 0) FROM loans WHERE status = 'approved'").fetchone()[0], 2),
        "declared_dividends": round(connection.execute("SELECT COALESCE(SUM(amount), 0) FROM dividend_allocations WHERE status = 'declared'").fetchone()[0], 2),
    }
    live_by_name = {
        row["full_name"].strip().casefold(): row
        for row in connection.execute(
            "SELECT u.id, u.full_name, COALESCE((SELECT SUM(s.amount) FROM savings s WHERE s.user_id = u.id), 0) AS savings, COALESCE((SELECT SUM(d.amount) FROM dividend_allocations d WHERE d.user_id = u.id AND d.status = 'declared'), 0) AS dividends FROM users u WHERE u.role = 'member'"
        )
    }
    savings_rows = numeric_member_rows("Savings")
    summary_by_id = {int(row[0]): row for row in numeric_member_rows("Summary")}
    member_rows = indexed_rows = {
        int(row[0]): row
        for row in rows_by_sheet.get("Members", [])[1:]
        if row and isinstance(row[0], (int, float))
    }
    for row in savings_rows:
        if len(row) > 1 and row[1] and int(row[0]) not in member_rows:
            member_rows[int(row[0])] = row
    member_delta_preview = []
    for legacy_id, member_row in sorted(member_rows.items()):
        name = str(member_row[1]).strip()
        live = live_by_name.get(name.casefold())
        savings_row = next((row for row in savings_rows if int(row[0]) == legacy_id), [])
        summary_row = summary_by_id.get(legacy_id, [])
        workbook_savings = number(savings_row, 14)
        workbook_dividend = number(summary_row, 4)
        member_delta_preview.append({
            "name": name,
            "exists_in_live_db": live is not None,
            "workbook_savings_total": round(workbook_savings, 2),
            "live_savings_total": round(live["savings"], 2) if live else 0,
            "savings_difference": round(workbook_savings - float(live["savings"]), 2) if live else round(workbook_savings, 2),
            "workbook_declared_interest": round(workbook_dividend, 2),
            "live_declared_dividends": round(live["dividends"], 2) if live else 0,
            "dividend_difference": round(workbook_dividend - float(live["dividends"]), 2) if live else round(workbook_dividend, 2),
        })
    report["member_delta_preview"] = member_delta_preview
    report["members_missing_from_live_db"] = [entry["name"] for entry in member_delta_preview if not entry["exists_in_live_db"]]
    report["member_savings_total_differences"] = {
        "positive": round(sum(max(0, entry["savings_difference"]) for entry in member_delta_preview), 2),
        "negative": round(sum(min(0, entry["savings_difference"]) for entry in member_delta_preview), 2),
    }
    report["member_dividend_total_differences"] = {
        "positive": round(sum(max(0, entry["dividend_difference"]) for entry in member_delta_preview), 2),
        "negative": round(sum(min(0, entry["dividend_difference"]) for entry in member_delta_preview), 2),
    }
    connection.close()
except sqlite3.Error as error:
    report["live_database_error"] = str(error)

changed_members = [
    row for row in report.get("member_delta_preview", [])
    if not row["exists_in_live_db"] or row["savings_difference"] != 0 or row["dividend_difference"] != 0
]
print(json.dumps({
    "file": report["file"],
    "source": {
        name: {
            key: value
            for key, value in sheet.items()
            if key not in {"header_or_first_row", "sample_rows"}
        }
        for name, sheet in report["sheets"].items()
        if name in {"Members", "Savings", "Loans (2)", "Loans", "Repayments", "Summary"}
    },
    "live_database": report.get("live_database"),
    "members_missing_from_live_db": report.get("members_missing_from_live_db", []),
    "member_savings_total_differences": report.get("member_savings_total_differences"),
    "member_dividend_total_differences": report.get("member_dividend_total_differences"),
    "changed_member_preview": changed_members,
}, indent=2, default=str))