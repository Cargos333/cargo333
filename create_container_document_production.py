"""
Script to create container_document table in production database
Run this on Render using: python create_container_document_production.py
"""
import os
import psycopg2
from urllib.parse import urlparse

def create_container_document_table():
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
        
        # Create the table
        print("Creating container_document table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS container_document (
                id SERIAL PRIMARY KEY,
                container_id INTEGER NOT NULL,
                filename VARCHAR(255) NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                file_data BYTEA NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                file_size INTEGER NOT NULL,
                uploaded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
                uploaded_by INTEGER,
                FOREIGN KEY (container_id) REFERENCES container(id) ON DELETE CASCADE,
                FOREIGN KEY (uploaded_by) REFERENCES "user"(id)
            )
        """)
        
        # Create index
        print("Creating index...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_container_document_container_id 
            ON container_document(container_id)
        """)
        
        conn.commit()
        print("✓ Table created successfully!")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"ERROR: {e}")
        raise

if __name__ == '__main__':
    create_container_document_table()
