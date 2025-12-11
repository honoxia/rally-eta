import sqlite3
import os

# Check all found databases
databases = [
    'd:/claude/data/rally_eta.db',
    'd:/claude/RallyETA_Portable_v1.2/data/rally_eta.db',
]

print("=" * 70)
print("CHECKING DRIVER MAPPINGS IN ALL DATABASES")
print("=" * 70)

for db_path in databases:
    if not os.path.exists(db_path):
        print(f"\n{db_path}: NOT FOUND")
        continue
        
    print(f"\n{db_path}:")
    print("-" * 70)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        print(f"Tables: {', '.join(tables) if tables else 'NONE'}")
        
        # If clean_stage_results exists, check driver mappings
        if 'clean_stage_results' in tables:
            query = """
            SELECT DISTINCT driver_id, driver_name 
            FROM clean_stage_results 
            WHERE driver_name LIKE '%Ali T%' 
               OR driver_name LIKE '%Evran%' 
               OR driver_name LIKE '%Uras%' 
               OR driver_name LIKE '%Sevgi%'
            ORDER BY driver_name
            LIMIT 10
            """
            cursor.execute(query)
            results = cursor.fetchall()
            
            if results:
                print("\nDriver mappings (selection):")
                for did, dname in results:
                    print(f"  {did:25s} -> {dname}")
            else:
                print("\nNo problematic drivers found in this database")
        
        conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

print("\n" + "=" * 70)
