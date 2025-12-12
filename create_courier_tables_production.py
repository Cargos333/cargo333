"""
Script to create Courier and CourierItem tables in production database
Run this on Render using: python create_courier_tables_production.py
"""
import os
import psycopg2
from urllib.parse import urlparse

def create_courier_tables():
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
        
        # Create Courier table
        print("Creating courier table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS courier (
                id SERIAL PRIMARY KEY,
                courier_id VARCHAR(50) UNIQUE NOT NULL,
                date DATE NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
            )
        """)
        
        # Create CourierItem table
        print("Creating courier_item table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS courier_item (
                id SERIAL PRIMARY KEY,
                courier_id INTEGER NOT NULL,
                container_number VARCHAR(50),
                sender_name VARCHAR(100) NOT NULL,
                receiver_name VARCHAR(100) NOT NULL,
                amount FLOAT8 NOT NULL,
                service FLOAT8 NOT NULL,
                exchange_rate FLOAT8 NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
                FOREIGN KEY (courier_id) REFERENCES courier(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes
        print("Creating indexes...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_courier_item_courier_id 
            ON courier_item(courier_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_courier_date 
            ON courier(date)
        """)
        
        conn.commit()
        print("✓ Tables created successfully!")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"ERROR: {e}")
        raise

if __name__ == '__main__':
    create_courier_tables()
