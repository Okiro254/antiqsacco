import sqlite3
import os

def seed_test_user():
    # Connect to your SQLite database
    db_path = "sacco.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Ensure the users table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT
        )
    """)
    
    # 2. Insert Test Member ID 1
    cursor.execute(
        "INSERT OR IGNORE INTO users (id, name, email, phone) VALUES (1, 'Test Member', 'member1@antiqsacco.com', '0700000001')"
    )
    
    conn.commit()
    conn.close()
    print("Successfully seeded Test Member ID #1 into sacco.db!")

if __name__ == "__main__":
    seed_test_user()