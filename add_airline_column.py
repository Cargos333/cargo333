"""
Migration script to add airline column to AirFreightPackage table
Run this script to add the airline field to existing AirFreight packages
Works with both SQLite and PostgreSQL
"""
from db_config import app, db
from models import AirFreightPackage
import os

def add_airline_column():
    """Add airline column to AirFreightPackage table"""
    with app.app_context():
        print("Adding airline column to AirFreightPackage table...")

        try:
            # Check database type and use appropriate method
            db_url = app.config['SQLALCHEMY_DATABASE_URI']
            print(f"Database URL: {db_url[:50]}...")  # Print first 50 chars for debugging

            # Try PostgreSQL syntax first (most common for production)
            try:
                print("Trying PostgreSQL syntax...")
                with db.engine.connect() as conn:
                    # Check if column exists using PostgreSQL information_schema
                    result = conn.execute(db.text("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'air_freight_package'
                        AND table_schema = 'public'
                        AND column_name = 'airline'
                    """))

                    if not result.fetchone():
                        # Add the column
                        conn.execute(db.text("""
                            ALTER TABLE air_freight_package
                            ADD COLUMN airline VARCHAR(50)
                        """))
                        conn.commit()
                        print("✅ Airline column added successfully to PostgreSQL!")
                        return
                    else:
                        print("✅ Airline column already exists in PostgreSQL")
                        return

            except Exception as pg_error:
                print(f"PostgreSQL attempt failed: {pg_error}")
                print("Trying SQLite syntax...")

                # Try SQLite syntax as fallback
                try:
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
                            print("✅ Airline column added successfully to SQLite!")
                        else:
                            print("✅ Airline column already exists in SQLite")

                except Exception as sqlite_error:
                    print(f"❌ SQLite attempt also failed: {sqlite_error}")
                    print("❌ Unable to add airline column to database")

        except Exception as e:
            print(f"❌ Error adding airline column: {e}")
            print("Make sure the database is accessible and the table exists.")

if __name__ == "__main__":
    add_airline_column()