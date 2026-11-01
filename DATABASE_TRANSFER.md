# Moving the live SACCO database to Render

The SQLite database is the SACCO ledger. Never commit it to GitHub or upload it to a free ephemeral Render filesystem and assume it is safe: a free web service can lose local files during restart/redeploy. Use durable storage first.

## 1. Configure durable storage on Render

Recommended: use Render PostgreSQL and migrate the app to PostgreSQL before production financial use. The current app uses SQLite, so the simpler compatible route is a Render Persistent Disk attached to the web service. Persistent disks require a paid Render service/plan; the current Free plan is not a durable SQLite target.

If you attach a persistent disk mounted at `/var/data`, add these environment variables to the `gotai` Render service:

- `DATABASE_PATH=/var/data/sacco.db`
- `DATABASE_PERSISTENT=true`

Keep the mount path and environment variables consistent. Redeploy after setting them. `init_db.py` reads `DATABASE_PATH` when the service starts.

## 2. Create a private, consistent export from the local database

From the project directory on the computer that has the current data:

```powershell
python .\export_database.py
```

The command writes a timestamped SQLite snapshot under `instance/`, checks its integrity, and reports only record counts. It contains password hashes, member identities, and financial records; treat it as confidential. It is ignored by Git. Transfer it only through a private, encrypted route and delete temporary copies safely when the migration has been confirmed.

## 3. Restore through the super-admin control center

1. Sign in to the deployed app with a super-admin account.
2. Open **Control center → Restore a SACCO database backup**.
3. Choose the exported `.db` file and type `RESTORE` exactly.
4. Confirm the restore result and compare member, savings, loan, and repayment counts with the export report.

The restore is refused in production unless `DATABASE_PERSISTENT=true`. Before replacing the target, the app validates SQLite integrity, required tables, required user fields, at least one admin, and foreign keys. It creates a timestamped backup of the current Render database first. Restore replaces the target database contents; only use it when the source snapshot is the complete authoritative database.

## 4. After restore

- Sign in again because account records/passwords now come from the uploaded snapshot.
- Check the admin dashboard totals and several member statements.
- Keep both the local source DB and the generated pre-restore backup until reconciliation is signed off.
- Do not use manual post-restore seeding to create duplicate members.

## Limitations

The upload does not make SQLite a multi-instance database. Keep Gunicorn at one worker as configured and do not scale multiple app instances against one SQLite file. For concurrent staff access, stronger availability, and safer backups, migrate to PostgreSQL; that requires an app database-adapter migration and a PostgreSQL service, not just uploading the SQLite file.
