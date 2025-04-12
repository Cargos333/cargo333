from db_config import app, db
from models import User
from werkzeug.security import generate_password_hash

def create_admin():
    with app.app_context():
        # Check if admin user already exists
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password=generate_password_hash('admin123')
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin account created successfully!")
            print("Username: admin")
            print("Password: admin123")
        else:
            print("Admin account already exists!")

if __name__ == "__main__":
    create_admin()
