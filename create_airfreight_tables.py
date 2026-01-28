"""
Script to manually create AirFreight tables in production database
Run this if the tables are missing after deployment
"""
from db_config import app, db
from models import AirFreightPackage, AirFreightClient, AirFreightProduct, AirFreightUser
from werkzeug.security import generate_password_hash
import os

def create_airfreight_tables():
    with app.app_context():
        print("Creating AirFreight tables...")
        
        try:
            # Create all tables (will only create missing ones)
            db.create_all()
            print("✅ AirFreight tables created successfully!")
            
            # Check if air freight admin exists
            admin = AirFreightUser.query.filter_by(username='airadmin').first()
            
            if not admin:
                print("\nCreating AirFreight admin user...")
                admin = AirFreightUser(
                    username='airadmin',
                    password=generate_password_hash('airadmin123'),
                    role='Admin',
                    full_name='Air Freight Administrator',
                    email='admin@airfreight.com',
                    is_active=True
                )
                db.session.add(admin)
                db.session.commit()
                print("✅ AirFreight admin created!")
                print(f"   Username: airadmin")
                print(f"   Password: airadmin123")
                print("   ⚠️  Change this password after first login!")
            else:
                print("✅ AirFreight admin already exists")
            
            # List all tables to verify
            print("\n📋 Database tables:")
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            for table_name in inspector.get_table_names():
                if 'air_freight' in table_name:
                    print(f"   ✓ {table_name}")
            
            print("\n✅ All done! AirFreight system is ready.")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    create_airfreight_tables()
