import sqlite3
import os

# Check dist database
db_path = 'd:/claude/dist/data/rally_eta.db'

if not os.path.exists(db_path):
    print(f"Database NOT FOUND: {db_path}")
    print("\nCreating database structure...")
    # The app will create it, so just report
else:
    print(f"Database FOUND: {db_path}")
    print("=" * 70)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print(f"\nTables: {tables}")
    
    # If clean_stage_results exists, check driver mappings
    if 'clean_stage_results' in tables:
        # Count total drivers
        cursor.execute("SELECT COUNT(DISTINCT driver_id) FROM clean_stage_results")
        total = cursor.fetchone()[0]
        print(f"\nTotal unique drivers: {total}")
        
        # Get problematic driver mappings
        query = """
        SELECT DISTINCT driver_id, driver_name 
        FROM clean_stage_results 
        WHERE driver_name LIKE '%Ali T%' 
           OR driver_name LIKE '%Evran%' 
           OR driver_name LIKE '%Uras%' 
           OR driver_name LIKE '%Sevgi%'
        ORDER BY driver_name
        """
        cursor.execute(query)
        results = cursor.fetchall()
        
        if results:
            print("\nProblematic driver mappings:")
            for did, dname in results:
                print(f"  ID: {did:25s} -> Name: {dname}")
        else:
            print("\nNo drivers found with those names")
    
    conn.close()
