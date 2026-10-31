import sqlite3


connection = sqlite3.connect("instance/sacco.db")
print("members:", connection.execute("SELECT COUNT(*) FROM users WHERE role = ?", ("member",)).fetchone()[0])
print("savings rows and total:", connection.execute("SELECT COUNT(*), ROUND(SUM(amount), 2) FROM savings").fetchone())
print("new savings by month:", connection.execute("SELECT substr(date, 1, 7), COUNT(*), ROUND(SUM(amount), 2) FROM savings WHERE reference LIKE ? GROUP BY substr(date, 1, 7) ORDER BY 1", ("XLSX2-%",)).fetchall())
print("loans and principal:", connection.execute("SELECT COUNT(*), ROUND(SUM(principal_amount), 2) FROM loans").fetchone())
print("approved loan balance:", connection.execute("SELECT ROUND(SUM(balance_due), 2) FROM loans WHERE status = ?", ("approved",)).fetchone()[0])
print("declared dividends:", connection.execute("SELECT ROUND(SUM(amount), 2) FROM dividend_allocations WHERE status = ?", ("declared",)).fetchone()[0])
connection.close()