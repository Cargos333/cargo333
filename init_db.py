from db_config import app, db
from models import User
from werkzeug.security import generate_password_hash

def init_db():
    with app.app_context():
        # Create tables
        db.create_all()
        
        # Check if admin exists
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password=generate_password_hash('admin123'),
                role='Admin',
                full_name='Administrator',
                email='admin@cargo333.com'
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created successfully")

if __name__ == "__main__":
    init_db()
