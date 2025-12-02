"""
Script to fix the is_active column type in the user table
Run this on Render using: python fix_user_is_active_column.py
"""
import os
import psycopg2
from urllib.parse import urlparse

def fix_user_is_active_column():
    # Get database URL from environment
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        return
    
    # Parse the database URL
    result = urlparse(database_url)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port
    
    print(f"Connecting to database: {database} on {hostname}")
    
    try:
        # Connect to database
        conn = psycopg2.connect(
            database=database,
            user=username,
            password=password,
            host=hostname,
            port=port
        )
        
        cursor = conn.cursor()
        
        # First, check current data type
        print("Checking current data type...")
        cursor.execute("""
            SELECT data_type 
            FROM information_schema.columns 
            WHERE table_name = 'user' AND column_name = 'is_active'
        """)
        current_type = cursor.fetchone()
        if current_type:
            print(f"Current type: {current_type[0]}")
        
        # Convert bigint values: ensure 0 stays 0 and non-zero becomes 1
        print("Normalizing existing data to 0 or 1...")
        cursor.execute("""
            UPDATE "user" 
            SET is_active = CASE 
                WHEN is_active = 0 THEN 0::bigint
                ELSE 1::bigint
            END
        """)
        
        conn.commit()
        print("✓ Data normalized")
        
        # Change column type to boolean
        print("Changing column type from bigint to boolean...")
        cursor.execute("""
            ALTER TABLE "user" 
            ALTER COLUMN is_active TYPE BOOLEAN 
            USING CASE 
                WHEN is_active = 0 THEN false 
                WHEN is_active = 1 THEN true
                ELSE true 
            END
        """)
        
        conn.commit()
        print("✓ Column type changed to boolean")
        
        # Set default value
        print("Setting default value...")
        cursor.execute("""
            ALTER TABLE "user" 
            ALTER COLUMN is_active SET DEFAULT true
        """)
        
        conn.commit()
        print("✓ Column type fixed successfully!")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"ERROR: {e}")
        if conn:
            conn.rollback()
        raise

if __name__ == '__main__':
    fix_user_is_active_column()
