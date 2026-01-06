"""
Migration script to add new columns to the courier table.
This script can be run on Render.com as a one-off command.

Run with: python migrate_courier_columns.py
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_config import app, db
from sqlalchemy import text, inspect

def migrate():
    """Add new columns to courier table if they don't exist"""
    try:
        with app.app_context():
            # Get the database engine
            engine = db.engine
            
            print("=" * 60)
            print("Starting Courier Table Migration")
            print("=" * 60)
            
            # Check if courier table exists
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            if 'courier' not in tables:
                print("ERROR: courier table does not exist!")
                return False
            
            # Get existing columns
            existing_columns = [col['name'] for col in inspector.get_columns('courier')]
            print(f"\nExisting columns in courier table: {', '.join(existing_columns)}")
            
            # Define columns to add
            columns_to_add = [
                ('brought_by_name', 'VARCHAR(100)'),
                ('brought_by_phone', 'VARCHAR(50)'),
                ('assigned_to', 'VARCHAR(100)'),
                ('photo_filename', 'VARCHAR(255)'),
                ('photo_data', 'BLOB'),
                ('photo_mime', 'VARCHAR(50)')
            ]
            
            print("\n" + "=" * 60)
            print("Adding New Columns")
            print("=" * 60)
            
            # Add columns if they don't exist
            with engine.begin() as conn:
                for column_name, column_type in columns_to_add:
                    if column_name not in existing_columns:
                        # For PostgreSQL (used by Render), use BYTEA instead of BLOB
                        if column_type == 'BLOB' and engine.dialect.name == 'postgresql':
                            column_type = 'BYTEA'
                        
                        sql = f'ALTER TABLE courier ADD COLUMN {column_name} {column_type}'
                        print(f"  → Adding column: {column_name} ({column_type})")
                        
                        try:
                            conn.execute(text(sql))
                            print(f"  ✓ Successfully added {column_name}")
                        except Exception as e:
                            print(f"  ✗ Error adding {column_name}: {str(e)}")
                            raise
                    else:
                        print(f"  ○ Column {column_name} already exists, skipping")
            
            print("\n" + "=" * 60)
            print("Migration Completed Successfully!")
            print("=" * 60)
            
            # Verify columns were added
            inspector = inspect(engine)
            final_columns = [col['name'] for col in inspector.get_columns('courier')]
            print(f"\nFinal columns in courier table: {', '.join(final_columns)}")
            
            return True
            
    except Exception as e:
        print("\n" + "=" * 60)
        print("ERROR: Migration Failed!")
        print("=" * 60)
        print(f"Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("\n")
    success = migrate()
    print("\n")
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
