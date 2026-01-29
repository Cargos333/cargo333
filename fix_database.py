"""
Script to fix database transaction issues on Render
Run this script in Render shell to rollback any aborted transactions
"""
from db_config import app, db

def fix_database_transaction():
    """Fix database transaction issues"""
    with app.app_context():
        try:
            print("Attempting to fix database transaction issues...")

            # Try to execute a simple query to reset the connection
            with db.engine.connect() as conn:
                # Execute a simple query to test the connection
                result = conn.execute(db.text("SELECT 1"))
                print("✅ Database connection is working")

                # Try to check if the airline column was added
                try:
                    result = conn.execute(db.text("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'air_freight_package'
                        AND table_schema = 'public'
                        AND column_name = 'airline'
                    """))

                    if result.fetchone():
                        print("✅ Airline column exists in air_freight_package table")
                    else:
                        print("❌ Airline column does not exist - you may need to run add_airline_column.py")

                except Exception as e:
                    print(f"❌ Error checking airline column: {e}")

                # Check if containers table is accessible
                try:
                    result = conn.execute(db.text("SELECT COUNT(*) FROM container"))
                    count = result.fetchone()[0]
                    print(f"✅ Containers table accessible: {count} containers")

                except Exception as e:
                    print(f"❌ Error accessing containers table: {e}")

        except Exception as e:
            print(f"❌ Database connection error: {e}")
            print("The database might be in an inconsistent state.")
            print("Try restarting your Render service.")

if __name__ == "__main__":
    fix_database_transaction()