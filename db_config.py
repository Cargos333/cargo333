from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql://cargo_db_ofg3_user:OlxdBEGckM3DnLYLePaZunBnhmrEdKpa@dpg-cvt0ed24d50c73db1n8g-a/cargo_db_ofg3'
)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a7153e2ffe196b572ee474300a7fd13b')
db = SQLAlchemy(app)
