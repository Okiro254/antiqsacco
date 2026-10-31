# Antiq Sacco System Owner Guide

This guide describes the checked-in application as it exists now. It is intended for whoever operates and upgrades the system. The app is a small Flask server with SQLite storage; it does not connect to banks or M-Pesa. Staff record money already received by hand.

## 1. What runs where

- `app.py` is the web application: sign-in, session and role checks, member pages, staff pages, money calculations, reports, and posting routes.
- `init_db.py` creates the SQLite schema and applies additive schema migrations. The database is `instance/sacco.db`.
- `templates/` contains the Jinja HTML pages. `base.html` is the shared navigation; `member.html`, `admin.html`, `super_admin.html`, `change_password.html`, and `login.html` are the pages.
- `static/css/style.css` controls appearance; `static/js/app.js` handles browser-side estimates, filtering, and the member-history drawer.
- `integrations.py` contains optional Africa's Talking SMS sending. Missing credentials result in a `not_configured` notification state. SMS is separate from posting cash.
- `run_public.py` runs Waitress on `127.0.0.1:8080` and starts the monthly APScheduler job. Use this behind a protected HTTPS tunnel, not as a directly internet-bound server.
- `setup_super_admin.py` sets up the `Major` identity. It prompts for a hidden password twice and stores only a hash.
- `migrate_legacy.py` is the original XLSB **replacement** importer. Do not run it with `--apply` on a populated database unless replacing the member and financial ledgers is explicitly intended.
- `update_legacy_savings.py` is an additive XLSX update tool, currently hard-coded to July, August, and September 2026 columns in `ANTIQ SACCO FORMULA 2.xlsx`.
- `inspect_legacy.py`, `inspect_xlsx.py`, and `verify_update.py` are inspection/verification helpers.
- `tests/test_manual_workflow.py` runs eight regression tests against a temporary copy of the database.

## 2. Current business rules in code

- Savings entries are manual ledger records and are summed for locked savings. There is no member withdrawal route.
- A member's borrowing limit is three times savings less guarantor encumbrances and pending/active principal commitments.
- Member loan requests are one-month loans at 20% per cycle. The server validates the 3x cap and creates a pending guarantee lock. The guarantor must consent.
- Staff underwriting uses `loan_approvals` and requires two distinct admin accounts to approve. The second approval checks the 3x capacity and guarantor consent.
- Full settlement expects the exact current loan balance. Rollover requires cycle interest plus at least 50% of outstanding principal; the remaining principal gets a new 20% interest charge.
- Staff manually enter deposits and loan repayments. Optional internal references are unique across savings/repayment references.
- The monthly scheduler applies the configured default fine to overdue approved loans once per loan/month. It does **not** collect monthly savings or debit wallets.
- Member monthly reports estimate a share of collected loan interest and fines using month-end savings proportions. These provisional figures are not declared dividends.
- Exit estimates use a 12-month cycle from `users.date_joined`; payout is blocked before maturity, while an own pending/approved loan remains, or while the member guarantees another loan. The estimate includes declared dividends and wallet credits. Staff must still review any real settlement.
- A first-login password change is required when `must_change_password=1`. All 29 currently imported members have that flag set.

## 3. Account and access model

`users.role` is either `member` or `admin`; `is_super_admin` is an independent flag. Major is not currently configured: live database inspection found one admin, 29 members, and zero super-admin accounts. The previous Major setup stopped because the two entered passwords differed, so no Major account was written.

To set up Major later, run `python setup_super_admin.py` from the project directory using the configured Python executable. Enter the same fresh passphrase twice directly into the terminal prompt. The input is hidden. Do not send passwords in chat. The script creates or promotes the Major account and makes it a member as well as a super-admin.

Members sign in with their assigned email and temporary password. They must change it before viewing the member portal. Staff registration requires a 12-character temporary password; staff must hand it to the member securely outside the app. Avoid shared or default credentials. Create individual staff accounts so the two-approver rule represents two people.

## 4. Run and stop

Development (local testing only):

```powershell
$env:APP_ENV = 'development'
python app.py
```

Local production WSGI server (the public tunnel target):

```powershell
python run_public.py
```

The production launcher reads `.env`, creates a random `SECRET_KEY` if missing, sets secure cookies, binds only to localhost port 8080, and starts the scheduler. Keep `.env` private; `.gitignore` excludes it. The computer must remain powered on and connected for local hosting to be reachable. For shutdown, stop the terminal process with Ctrl+C.

## 5. Database tables

- `users`: sign-in identities, role/super-admin flags, first-login password state, join date, monthly contribution setting.
- `savings`: append-only manual/legacy savings ledger rows.
- `loans`: requested/approved loans, interest, principal, due amount, cycle date, status, guarantor.
- `loan_repayments`: manual repayments with principal/interest split and optional reference.
- `guarantor_locks`: savings capacity reserved for another member's loan.
- `loan_approvals`: staff decisions, enforcing one decision per official per loan.
- `loan_rollovers`: rollover history.
- `loan_fines`: monthly fine rows with unique loan/month protection.
- `dividend_runs`, `dividend_allocations`: declared annual dividends.
- `wallet_accounts`, `wallet_transactions`: legacy credit storage; do not treat these as a bank or live payment wallet.
- `monthly_obligations`: schema exists, but monthly savings collections are not currently automated.
- `notifications`: SMS attempt and queued/not-configured state.
- `mpesa_payments`, `mpesa_receipts`: leftover historical/schema tables only. No M-Pesa endpoints or active payment UI remain.

## 6. Backups and recovery

Before manual migrations or upgrades, stop the app and copy the database:

```powershell
Copy-Item .\instance\sacco.db .\instance\sacco-manual-backup-YYYYMMDD-HHMMSS.db
```

Use a new timestamped filename. Keep another encrypted copy off this computer. Automatic workbook scripts use SQLite's backup API before writing; do not rely on that instead of regular backups. Test restoring a backup to a separate test folder before relying on it. Never overwrite the only database copy.

## 7. Updating spreadsheet data safely

1. Copy the new workbook into a known path and inspect sheet names/headers first.
2. Confirm which sheet is authoritative for each data type, which year/month the figures refer to, and whether values replace balances or are new transactions.
3. Run a dry-run preview. Reconcile totals and member names/IDs to the live database.
4. Check for duplicate entries. Do not import formula/subtotal sheets as transactions.
5. Back up the DB and import only the agreed delta. Verify member count, ledger count, totals, loans, dividends, and report pages afterward.

`update_legacy_savings.py` is specific to one workbook and month-column layout; modify its column mapping only after inspecting the new workbook. The original `migrate_legacy.py --apply` deletes existing member ledger records and replaces them. That is destructive and not appropriate for incremental updates.

## 8. Testing before changes

Run:

```powershell
$env:APP_ENV = 'development'
python -m py_compile .\app.py .\init_db.py .\run_public.py
python -m unittest .\tests\test_manual_workflow.py -v
```

The tests cover staff manual posting, member loan application, password-change flow, super-admin dual access, reports, and absence of M-Pesa routes. Add tests for any new financial behavior before applying it to the live database.

## 9. Important limitations and review items

- `init_db.py` runs at app import and seeds demo users/records only if the database is empty. Protect production data and do not delete the database to “reset” the app.
- The 12-month cycle begins at account creation (`date_joined`), not a centrally configured chama opening date. Confirm this matches the SACCO's actual cycle policy before using maturity estimates for payouts.
- Legacy savings have month-end dates, not real transaction days; reports should retain that provenance.
- The spreadsheet had conflicting loan sheets and dividend totals. Only the agreed savings update was appended; earlier declared dividends and loans were deliberately preserved.
- The approval table records two signatures, but loan approval currently updates the loan to approved; it does not transfer money or verify a bank disbursement. Staff must record actual manual financial transactions accurately.
- A sole admin cannot complete the two-distinct-official approval rule by themselves. Set up a second real staff account.
- SMS requires Africa's Talking credentials and member phone numbers; imported members did not have phone/email details in the workbook. A notification marked `not_configured` was not sent.
- Public hosting is not currently configured. `HOSTING.md` describes a Cloudflare Tunnel plus Access path, but no domain/tunnel/Access policy is active yet.
- This project has no documented independent accountant/legal/security review. Have the SACCO approve rate, fine, dividend, cycle, guarantee, and payout policies before using displayed estimates as official financial commitments.

## 10. Suggested safe upgrade workflow

1. Stop the running server and make a timestamped backup.
2. Change one area at a time; write down the business rule before changing code.
3. Update the schema through additive migrations in `init_db.py`; do not rename/drop columns casually.
4. Add or update tests using a temporary DB copy.
5. Run syntax checks and the complete test suite.
6. Review the database totals and templates in a test instance.
7. Restart the production launcher and verify read-only dashboard/report pages before posting transactions.
8. Record the backup filename, deployment change, and any manual reconciliation performed.
