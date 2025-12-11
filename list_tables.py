import sqlite3

conn = sqlite3.connect('data/rally_eta.db')
cursor = conn.cursor()

# Get table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]

print("Tables in database:")
for table in tables:
    print(f"  - {table}")

conn.close()
