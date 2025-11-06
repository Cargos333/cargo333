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
database_url = os.getenv(
    'DATABASE_URL',
    'postgresql://cargo_db_ofg3_user:OlxdBEGckM3DnLYLePaZunBnhmrEdKpa@dpg-cvt0ed24d50c73db1n8g-a.oregon-postgres.render.com/cargo_db_ofg3'
)
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

# If using a local SQLite file, make the path absolute and ensure the directory exists.
if database_url.startswith('sqlite:///'):
    # strip the prefix and get the file path
    sqlite_path = database_url.replace('sqlite:///', '', 1)
    # If the path is not absolute, make it relative to the project dir (this file's dir)
    if not os.path.isabs(sqlite_path):
        project_root = os.path.dirname(os.path.abspath(__file__))
        sqlite_path = os.path.join(project_root, sqlite_path)
    # Ensure the directory for the sqlite file exists
    sqlite_dir = os.path.dirname(sqlite_path)
    if sqlite_dir and not os.path.exists(sqlite_dir):
        os.makedirs(sqlite_dir, exist_ok=True)
    # Use the absolute path for SQLAlchemy
    database_url = 'sqlite:///' + sqlite_path

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a7153e2ffe196b572ee474300a7fd13b')

db = SQLAlchemy(app)

# Try to test the database connection. For local SQLite we don't want to
# fail import (the file may be created later), so only raise for non-sqlite
try:
    with app.app_context():
        db.engine.connect()
    logger.info("Database connection successful")
except Exception as e:
    if database_url.startswith('sqlite:'):
        logger.warning(f"SQLite database not ready (will create on first use): {str(e)}")
    else:
        logger.error(f"Database connection failed: {str(e)}")
        # For remote DBs (e.g. Render Postgres) keep the old behaviour and raise
        raise
