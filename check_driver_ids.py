import sqlite3
import sys

# Connect to database
conn = sqlite3.connect('data/rally_eta.db')
cursor = conn.cursor()

# Get driver mappings for the problematic drivers
query = """
SELECT DISTINCT driver_id, driver_name 
FROM clean_stage_results 
WHERE driver_name LIKE '%Ali T%' 
   OR driver_name LIKE '%Evran%' 
   OR driver_name LIKE '%Uras%' 
   OR driver_name LIKE '%Sevgi%'
ORDER BY driver_name
"""

print("=" * 60)
print("DRIVER_ID to DRIVER_NAME Mappings")
print("=" * 60)

cursor.execute(query)
for driver_id, driver_name in cursor.fetchall():
    print(f"{driver_id:25s} -> {driver_name}")

print("\n" + "=" * 60)

# Check if there are duplicate driver names with different IDs
query2 = """
SELECT driver_name, COUNT(DISTINCT driver_id) as id_count
FROM clean_stage_results
WHERE driver_name LIKE '%Ali T%' 
   OR driver_name LIKE '%Evran%' 
   OR driver_name LIKE '%Uras%' 
   OR driver_name LIKE '%Sevgi%'
GROUP BY driver_name
HAVING id_count > 1
"""

print("Drivers with multiple IDs:")
cursor.execute(query2)
duplicates = cursor.fetchall()
if duplicates:
    for name, count in duplicates:
        print(f"  {name}: {count} different IDs")
else:
    print("  No duplicates found")

conn.close()
