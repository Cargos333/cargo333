"""
Comprehensive database diagnostic and fix script for Render
Run this script in Render shell to diagnose and fix database issues
"""
from db_config import app, db
from models import Container, Shipment, AirFreightPackage

def diagnose_database():
    """Diagnose database issues and provide fixes"""
    with app.app_context():
        print("🔍 Diagnosing database issues...")
        print("=" * 50)

        try:
            with db.engine.connect() as conn:
                # Test basic connectivity
                print("✅ Database connection established")

                # Check AirFreight tables
                print("\n📦 Checking AirFreight tables...")

                # Check if air_freight_package table exists
                try:
                    result = conn.execute(db.text("""
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_name = 'air_freight_package'
                            AND table_schema = 'public'
                        )
                    """))
                    table_exists = result.fetchone()[0]

                    if table_exists:
                        print("✅ air_freight_package table exists")

                        # Check airline column
                        result = conn.execute(db.text("""
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = 'air_freight_package'
                            AND table_schema = 'public'
                            AND column_name = 'airline'
                        """))

                        if result.fetchone():
                            print("✅ airline column exists")
                        else:
                            print("❌ airline column missing - run: python add_airline_column.py")

                    else:
                        print("❌ air_freight_package table missing - AirFreight not set up")

                except Exception as e:
                    print(f"❌ Error checking AirFreight tables: {e}")

                # Check main tables
                print("\n🏗️  Checking main application tables...")

                tables_to_check = ['container', 'shipment', 'client', 'user']
                for table in tables_to_check:
                    try:
                        result = conn.execute(db.text(f"SELECT COUNT(*) FROM {table}"))
                        count = result.fetchone()[0]
                        print(f"✅ {table} table: {count} records")
                    except Exception as e:
                        print(f"❌ {table} table error: {e}")

                # Test problematic query
                print("\n🔧 Testing problematic container-shipments relationship...")
                try:
                    containers = Container.query.limit(3).all()
                    for container in containers:
                        try:
                            shipment_count = len(container.shipments)
                            print(f"✅ Container {container.id}: {shipment_count} shipments")
                        except Exception as e:
                            print(f"❌ Container {container.id} relationship error: {e}")
                except Exception as e:
                    print(f"❌ Container query error: {e}")

        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return False

        print("\n" + "=" * 50)
        print("📋 RECOMMENDED FIXES:")
        print("1. If airline column is missing: python add_airline_column.py")
        print("2. If transaction errors persist: Restart your Render service")
        print("3. If tables are missing: Run your database initialization scripts")
        print("4. Check Render logs for more detailed error information")

        return True

if __name__ == "__main__":
    diagnose_database()