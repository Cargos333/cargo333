"""
Migration script to add airline column to AirFreightPackage table
Run this script to add the airline field to existing AirFreight packages
"""
from db_config import app, db
from models import AirFreightPackage
import os

def add_airline_column():
    """Add airline column to AirFreightPackage table"""
    with app.app_context():
        print("Adding airline column to AirFreightPackage table...")

        try:
            # Use raw SQL to add the column if it doesn't exist (SQLite syntax)
            with db.engine.connect() as conn:
                # Check if column exists using SQLite pragma
                result = conn.execute(db.text("""
                    PRAGMA table_info(air_freight_package)
                """))

                columns = [row[1] for row in result.fetchall()]  # column names are in index 1

                if 'airline' not in columns:
                    # Add the column
                    conn.execute(db.text("""
                        ALTER TABLE air_freight_package
                        ADD COLUMN airline VARCHAR(50)
                    """))
                    conn.commit()
                    print("✅ Airline column added successfully!")
                else:
                    print("✅ Airline column already exists")

        except Exception as e:
            print(f"❌ Error adding airline column: {e}")

if __name__ == "__main__":
    add_airline_column()