from db_config import app, db
from models import AirFreightUser
from werkzeug.security import generate_password_hash

def create_air_freight_admin():
    with app.app_context():
        # Check if admin user already exists
        if not AirFreightUser.query.filter_by(username='airadmin').first():
            admin = AirFreightUser(
                username='airadmin',
                password=generate_password_hash('airadmin123'),
                role='Admin',
                full_name='Air Freight Administrator',
                email='admin@airfreight.com'
            )
            db.session.add(admin)
            db.session.commit()
            print("Air Freight Admin account created successfully!")
            print("Username: airadmin")
            print("Password: airadmin123")
            print("Role: Admin")
        else:
            print("Air Freight Admin account already exists!")

if __name__ == "__main__":
    create_air_freight_admin()