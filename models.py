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
    documents = db.relationship('ContainerDocument', backref='container', lazy=True, cascade='all, delete-orphan')

class Shipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    volume = db.Column(db.Float, nullable=False)
    # Tonnage and price per tonne for metal shipments (nullable for other goods types)
    tonnage = db.Column(db.Float, nullable=True)
    price_per_tonne = db.Column(db.Float, nullable=True)
    # For cars: store the empty volume (vide) and the used volume so we can display them
    volume_vide = db.Column(db.Float, nullable=True)
    volume_used = db.Column(db.Float, nullable=True)
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
    # Goods-style fields to mirror Shipment behavior (nullable for legacy rows)
    goods_type = db.Column(db.String(50), nullable=True)  # 'Merchandise', 'Car', 'Metals'
    tonnage = db.Column(db.Float, nullable=True)
    price_per_tonne = db.Column(db.Float, nullable=True)
    volume_vide = db.Column(db.Float, nullable=True)
    volume_used = db.Column(db.Float, nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    length = db.Column(db.Float, nullable=False)
    width = db.Column(db.Float, nullable=False)
    height = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def calculate_volume(self):
        return self.length * self.width * self.height * self.quantity

class ContainerDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_data = db.Column(db.LargeBinary, nullable=False)
    file_type = db.Column(db.String(50), nullable=False)  # pdf, image
    file_size = db.Column(db.Integer, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

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
