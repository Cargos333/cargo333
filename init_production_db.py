"""
Initialize production database on Render.com
Run this script once after deployment to create all tables
"""
from app import app, db
from models import User, Client, Container, Shipment, Product, ContainerDocument, Courier, CourierItem, FinanceRecord, Billetage, CourierBilletage, AirFreightPackage, AirFreightClient, AirFreightProduct, AirFreightUser
from werkzeug.security import generate_password_hash

def init_production_database():
    with app.app_context():
        print("Creating all database tables...")
        
        # Create all tables
        db.create_all()
        
        print("Tables created successfully!")
        
        # Check if admin user exists
        admin = User.query.filter_by(username='admin').first()
        
        if not admin:
            print("Creating default admin user...")
            admin = User(
                username='admin',
                password=generate_password_hash('admin123'),  # Change this password!
                role='Admin',
                full_name='System Administrator'
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created!")
            print("Username: admin")
            print("Password: admin123")
            print("⚠️  IMPORTANT: Change this password immediately after first login!")
        else:
            print("Admin user already exists.")
        
        # Initialize Air Freight system
        print("\nInitializing Air Freight system...")
        try:
            from init_air_freight_admin import create_air_freight_admin
            create_air_freight_admin()
        except Exception as e:
            print(f"Warning: Could not initialize Air Freight admin: {e}")
        
        print("\n✅ Database initialization complete!")
        print("\nExisting tables:")
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        for table_name in inspector.get_table_names():
            print(f"  - {table_name}")

if __name__ == "__main__":
    init_production_database()
