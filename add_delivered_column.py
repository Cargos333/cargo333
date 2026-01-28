"""
Migration script to add delivered column to air_freight_client table
Run this once to add the missing column
"""
from app import app, db
import sqlite3

def migrate_add_delivered_column():
    with app.app_context():
        print("Adding delivered column to air_freight_client table...")

        try:
            # For SQLite, we need to use raw SQL to add the column
            with db.engine.connect() as conn:
                conn.execute(db.text('ALTER TABLE air_freight_client ADD COLUMN delivered BOOLEAN DEFAULT 0 NOT NULL'))
                conn.commit()

            print("✅ delivered column added successfully to air_freight_client table!")

            # Verify the column was added
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            columns = inspector.get_columns('air_freight_client')

            column_names = [col['name'] for col in columns]
            if 'delivered' in column_names:
                print("✅ Verified: delivered column exists in air_freight_client table")
                print("\nAll columns in air_freight_client table:")
                for col in columns:
                    print(f"  - {col['name']}: {col['type']}")
            else:
                print("⚠️  Warning: Column addition reported success but column not found")

        except Exception as e:
            print(f"❌ Error adding column: {str(e)}")
            raise

if __name__ == "__main__":
    migrate_add_delivered_column()