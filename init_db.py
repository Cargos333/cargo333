import os
from db_config import app, db
from models import User, Container, Client, Shipment, Product
from werkzeug.security import generate_password_hash
from datetime import datetime

def init_db():
    with app.app_context():
        # Drop existing database
        try:
            os.remove('shipping.db')
            print("Existing database removed.")
        except FileNotFoundError:
            pass

        print("Creating new database...")
        
        # Create all tables
        db.drop_all()
        db.create_all()
        
        # Create admin user
        admin = User(
            username='admin',
            password=generate_password_hash('admin123'),
            role='Admin',
            full_name='Administrator',
            email='admin@cargo333.com',
            is_active=True
        )
        
        # Create a manager user
        manager = User(
            username='manager',
            password=generate_password_hash('manager123'),
            role='Manager',
            full_name='Manager User',
            email='manager@cargo333.com',
            is_active=True
        )

        # Create a secretary user
        secretary = User(
            username='secretary',
            password=generate_password_hash('secretary123'),
            role='Secretary',
            full_name='Secretary User',
            email='secretary@cargo333.com',
            is_active=True
        )
        
        # Create example container
        container = Container(
            container_number='TEST001',
            container_name='Test Container',
            container_type='40HC',
            total_volume=100.0,
            price=50000.0,
            destination='Moroni',
            status='active',
            sur_et_start=False,
            created_at=datetime.utcnow(),
            connaissement_pdf=None,
            pdf_filename=None
        )
        
        db.session.add_all([admin, manager, secretary, container])
        
        try:
            db.session.commit()
            print("\nDatabase initialized successfully!")
            print("\nDefault accounts created:")
            print("Admin - Username: admin / Password: admin123")
            print("Manager - Username: manager / Password: manager123")
            print("Secretary - Username: secretary / Password: secretary123")
            
        except Exception as e:
            db.session.rollback()
            print(f"Error during initialization: {str(e)}")
            raise e

if __name__ == "__main__":
    init_db()
