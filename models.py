from datetime import datetime
from db_config import db
from flask_login import UserMixin

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    mark = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    shipments = db.relationship('Shipment', backref='client', lazy=True)

class Container(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_number = db.Column(db.String(20), unique=True, nullable=False)
    container_type = db.Column(db.String(50), nullable=False)
    total_volume = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)
    destination = db.Column(db.String(20), nullable=False)  # 'Mutsamudu' or 'Moroni'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='active')  # active, completed, cancelled
    container_name = db.Column(db.String(100))
    sur_et_start = db.Column(db.Boolean, default=False)
    connaissement_pdf = db.Column(db.LargeBinary)
    pdf_filename = db.Column(db.String(255))
    shipments = db.relationship('Shipment', backref='container', lazy=True)

class Shipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    volume = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), default='unpaid')  # paid, unpaid, partial
    paid_amount = db.Column(db.Float, default=0.0)
    extra_charge = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    reference = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    length = db.Column(db.Float, nullable=False)
    width = db.Column(db.Float, nullable=False)
    height = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def calculate_volume(self):
        return self.length * self.width * self.height * self.quantity

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Employee')  # Admin, Secretary, Manager, Employee
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    def is_admin(self):
        return self.role == 'Admin'
