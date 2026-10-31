import json
import sys

from pyxlsb import open_workbook


def rows_for(sheet):
    with workbook.get_sheet(sheet) as worksheet:
        return [
            [cell.v for cell in row]
            for row in worksheet.rows(sparse=True)
            if any(cell.v is not None for cell in row)
        ]


def number(row, column):
    if len(row) <= column or row[column] is None:
        return 0.0
    try:
        return float(row[column])
    except (TypeError, ValueError):
        return 0.0


if len(sys.argv) != 2:
    raise SystemExit("Usage: python inspect_legacy.py <workbook.xlsb>")

workbook_path = sys.argv[1]
workbook = open_workbook(workbook_path)
report = {"file": workbook_path, "sheets": {}}

for sheet_name in workbook.sheets:
    rows = rows_for(sheet_name)
    report["sheets"][sheet_name] = {
        "nonempty_rows": len(rows),
        "header_or_first_row": rows[0] if rows else [],
        "sample_rows": rows[1:4] if rows else [],
    }

for sheet_name in ("Members", "Savings", "Loans (2)", "Loans", "Repayments", "Summary"):
    rows = rows_for(sheet_name)
    data = rows[1:] if rows else []
    report["sheets"].setdefault(sheet_name, {})["numeric_id_rows"] = sum(
        bool(row) and isinstance(row[0], (int, float)) for row in data
    )

member_rows = rows_for("Members")[1:]
member_ids = {int(row[0]) for row in member_rows if row and isinstance(row[0], (int, float))}
report["member_ids"] = sorted(member_ids)
report["member_names"] = [row[1] for row in member_rows if len(row) > 1 and row[1]]
for sheet_name in ("Savings", "Loans", "Loans (2)", "Repayments", "Summary"):
    sheet_rows = rows_for(sheet_name)[1:]
    sheet_ids = {
        int(row[0])
        for row in sheet_rows
        if row and isinstance(row[0], (int, float))
    }
    report["sheets"][sheet_name]["ids_not_in_members_sheet"] = sorted(sheet_ids - member_ids)
    report["sheets"][sheet_name]["unmatched_id_names"] = [
        {"id": int(row[0]), "name": row[1] if len(row) > 1 else None}
        for row in sheet_rows
        if row and isinstance(row[0], (int, float)) and int(row[0]) not in member_ids
    ]

if "Savings" in report["sheets"]:
    savings_rows = [
        row for row in rows_for("Savings")[1:]
        if row and isinstance(row[0], (int, float))
    ]
    report["sheets"]["Savings"]["month_totals"] = {
        month: round(sum(number(row, index) for row in savings_rows), 2)
        for index, month in enumerate(
            ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
            start=2,
        )
    }
    report["sheets"]["Savings"]["reported_total_column"] = round(
        sum(number(row, 14) for row in savings_rows), 2
    )

for sheet_name in ("Loans (2)", "Loans"):
    loan_rows = [
        row for row in rows_for(sheet_name)[1:]
        if row and isinstance(row[0], (int, float))
    ]
    report["sheets"][sheet_name]["loan_principal_column"] = round(
        sum(number(row, 2) for row in loan_rows), 2
    )
    report["sheets"][sheet_name]["interest_column"] = round(
        sum(number(row, 4) for row in loan_rows), 2
    )
    report["sheets"][sheet_name]["balance_column"] = round(
        sum(number(row, 7) for row in loan_rows), 2
    )
    report["sheets"][sheet_name]["positive_balance_total"] = round(
        sum(max(0, number(row, 7)) for row in loan_rows if len(row) > 7), 2
    )
    report["sheets"][sheet_name]["negative_balance_rows"] = [
        {"id": row[0], "name": row[1], "balance": number(row, 7)}
        for row in loan_rows
        if len(row) > 7 and number(row, 7) < 0
    ]
    report["sheets"][sheet_name]["nonzero_loan_rows"] = [
        {
            "id": row[0] if row else None,
            "name": row[1] if len(row) > 1 else None,
            "principal": number(row, 2),
            "interest": number(row, 4),
            "payable": number(row, 5),
            "paid": number(row, 6),
            "balance": number(row, 7),
        }
        for row in loan_rows
        if any(number(row, col) for col in (2, 4, 5, 6, 7))
    ]

if "Repayments" in report["sheets"]:
    repayment_rows = [
        row for row in rows_for("Repayments")[1:]
        if row and isinstance(row[0], (int, float))
    ]
    report["sheets"]["Repayments"]["paid_total"] = round(
        sum(number(row, 3) for row in repayment_rows), 2
    )
    report["sheets"]["Repayments"]["penalty_total"] = round(
        sum(number(row, 7) for row in repayment_rows), 2
    )

if "Summary" in report["sheets"]:
    summary_rows = [
        row for row in rows_for("Summary")[1:]
        if row and isinstance(row[0], (int, float))
    ]
    report["sheets"]["Summary"]["savings_total"] = round(
        sum(number(row, 2) for row in summary_rows), 2
    )
    report["sheets"]["Summary"]["estimated_interest_total"] = round(
        sum(number(row, 4) for row in summary_rows), 2
    )
    report["sheets"]["Summary"]["final_payout_total"] = round(
        sum(number(row, 7) for row in summary_rows), 2
    )

print(f"Members sheet: {len(member_ids)} IDs ({min(member_ids)}-{max(member_ids)})")
print("Savings sheet total column:", report["sheets"]["Savings"]["reported_total_column"])
print("Savings month totals:", report["sheets"]["Savings"]["month_totals"])
print("Savings IDs missing from roster:", report["sheets"]["Savings"]["unmatched_id_names"])
print("Loans (2) principal / interest / signed balance:", report["sheets"]["Loans (2)"]["loan_principal_column"], report["sheets"]["Loans (2)"]["interest_column"], report["sheets"]["Loans (2)"]["balance_column"])
loan_source_rows = [row for row in rows_for("Loans (2)")[1:] if row and isinstance(row[0], (int, float))]
loan_payable = sum(number(row, 5) for row in loan_source_rows)
loan_paid = sum(number(row, 6) for row in loan_source_rows)
print("Loans (2) payable / paid / amount due / credit:", round(loan_payable, 2), round(loan_paid, 2), round(sum(max(0, number(row, 5) - number(row, 6)) for row in loan_source_rows), 2), round(sum(max(0, number(row, 6) - number(row, 5)) for row in loan_source_rows), 2))
print("Loans (2) negative balance rows:", report["sheets"]["Loans (2)"]["negative_balance_rows"])
print("Repayments total / penalties:", report["sheets"]["Repayments"]["paid_total"], report["sheets"]["Repayments"]["penalty_total"])
print("Summary savings / interest / payout:", report["sheets"]["Summary"]["savings_total"], report["sheets"]["Summary"]["estimated_interest_total"], report["sheets"]["Summary"]["final_payout_total"])