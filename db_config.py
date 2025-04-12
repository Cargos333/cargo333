from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)

# Get database URL and fix potential "postgres://" to "postgresql://"
database_url = os.getenv('DATABASE_URL', 'postgresql://cargo_db_ofg3_user:OlxdBEGckM3DnLYLePaZunBnhmrEdKpa@dpg-cvt0ed24d50c73db1n8g-a.oregon-postgres.render.com/cargo_db_ofg3')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a7153e2ffe196b572ee474300a7fd13b')

# Configure database pooling
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 5,
    'pool_recycle': 280,
    'pool_pre_ping': True
}

try:
    db = SQLAlchemy(app)
    with app.app_context():
        db.engine.connect()
    logger.info("Database connection successful")
except Exception as e:
    logger.error(f"Database connection failed: {str(e)}")
    raise
