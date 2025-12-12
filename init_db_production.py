"""
Production Database Initialization Script for Render
This script creates all database tables in the PostgreSQL database
"""
from db_config import app, db
from models import User
from werkzeug.security import generate_password_hash

def init_production_db():
    with app.app_context():
        print("Dropping existing tables and creating new ones...")
        
        # Drop all existing tables and create fresh ones
        db.drop_all()
        print("Existing tables dropped.")
        
        # Create all tables
        db.create_all()
        
        print("Tables created successfully!")
        
        # Check if admin user exists
        admin = db.session.get(User, 1)
        
        if not admin:
            print("Creating default admin user...")
            admin = User(
                username='admin',
                password=generate_password_hash('admin123'),
                role='Admin',
                full_name='Administrator',
                email='admin@cargo333.com',
                is_active=True
            )
            
            secretary = User(
                username='secretary',
                password=generate_password_hash('secretary123'),
                role='Secretary',
                full_name='Secretary User',
                email='secretary@cargo333.com',
                is_active=True
            )
            
            db.session.add_all([admin, secretary])
            
            try:
                db.session.commit()
                print("\nDatabase initialized successfully!")
                print("\nDefault accounts created:")
                print("Admin - Username: admin / Password: admin123")
                print("Secretary - Username: secretary / Password: secretary123")
                print("\n⚠️  IMPORTANT: Change these default passwords after first login!")
            except Exception as e:
                db.session.rollback()
                print(f"Error during initialization: {str(e)}")
                raise e
        else:
            print("Admin user already exists. Skipping user creation.")
            print("Database tables verified and ready!")

if __name__ == "__main__":
    init_production_db()
