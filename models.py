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

class Courier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    courier_id = db.Column(db.String(50), unique=True, nullable=False)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Person who brought the courier (optional fields)
    brought_by_name = db.Column(db.String(100), nullable=True)
    brought_by_phone = db.Column(db.String(50), nullable=True)
    # Person assigned to handle the courier (optional)
    assigned_to = db.Column(db.String(100), nullable=True)
    # Optional photo of the person or document
    photo_filename = db.Column(db.String(255), nullable=True)
    photo_data = db.Column(db.LargeBinary, nullable=True)
    photo_mime = db.Column(db.String(50), nullable=True)
    items = db.relationship('CourierItem', backref='courier', lazy=True, cascade='all, delete-orphan')
    billetages = db.relationship('CourierBilletage', backref='courier', lazy=True, cascade='all, delete-orphan')

class CourierItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    courier_id = db.Column(db.Integer, db.ForeignKey('courier.id'), nullable=False)
    container_number = db.Column(db.String(50), nullable=True)
    sender_name = db.Column(db.String(100), nullable=False)
    receiver_name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    service = db.Column(db.Float, nullable=False)
    exchange_rate = db.Column(db.Float, nullable=False)  # EURO to AED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Secretary approval fields
    is_received = db.Column(db.Boolean, default=False)
    market_exchange_rate = db.Column(db.Float, nullable=True)  # Market exchange rate at time of receipt
    received_at = db.Column(db.DateTime, nullable=True)
    received_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    @property
    def money_in_euro(self):
        return self.amount - self.service
    
    @property
    def money_in_aed(self):
        return self.money_in_euro * self.exchange_rate
    
    @property
    def money_received(self):
        """Money received based on market exchange rate (only if approved)"""
        if self.is_received and self.market_exchange_rate:
            return self.money_in_euro * self.market_exchange_rate
        return None

class FinanceRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Ticketing fields
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    service_charge = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    # Payment tracking
    is_paid = db.Column(db.Boolean, default=True)  # Assume tickets are paid when created
    payment_method = db.Column(db.String(50), default='cash')  # cash, card, transfer, etc.
    # Notes/Description
    notes = db.Column(db.Text)
    # User who added the record
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def calculate_total(self):
        """Calculate total amount (amount - service charge)"""
        return (self.amount or 0) - (self.service_charge or 0)

class Billetage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Date for which this cash count is valid (for filtering related tickets)
    count_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    # Bill denominations
    euro_500 = db.Column(db.Integer, default=0)
    euro_200 = db.Column(db.Integer, default=0)
    euro_100 = db.Column(db.Integer, default=0)
    euro_50 = db.Column(db.Integer, default=0)
    euro_20 = db.Column(db.Integer, default=0)
    euro_10 = db.Column(db.Integer, default=0)
    euro_5 = db.Column(db.Integer, default=0)
    # Comores denominations (KMF)
    kmf_10000 = db.Column(db.Integer, default=0)
    kmf_5000 = db.Column(db.Integer, default=0)
    kmf_2000 = db.Column(db.Integer, default=0)
    kmf_1000 = db.Column(db.Integer, default=0)
    kmf_500 = db.Column(db.Integer, default=0)
    # Total
    total_amount = db.Column(db.Float, nullable=False)
    # Reconciliation status
    is_reconciled = db.Column(db.Boolean, default=False)
    reconciliation_notes = db.Column(db.Text)
    # Notes
    notes = db.Column(db.Text)
    # User who counted
    counted_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def calculate_total(self):
        """Calculate total amount from all denominations"""
        # EUR to KMF exchange rate (approximate: 1 EUR = 492 KMF)
        EUR_TO_KMF = 492
        
        bills_total_eur = (
            (self.euro_500 or 0) * 500 +
            (self.euro_200 or 0) * 200 +
            (self.euro_100 or 0) * 100 +
            (self.euro_50 or 0) * 50 +
            (self.euro_20 or 0) * 20 +
            (self.euro_10 or 0) * 10 +
            (self.euro_5 or 0) * 5
        )
        
        kmf_total = (
            (self.kmf_10000 or 0) * 10000 +
            (self.kmf_5000 or 0) * 5000 +
            (self.kmf_2000 or 0) * 2000 +
            (self.kmf_1000 or 0) * 1000 +
            (self.kmf_500 or 0) * 500
        )
        
        # Convert KMF to EUR for total
        kmf_in_eur = kmf_total / EUR_TO_KMF
        
        return bills_total_eur + kmf_in_eur

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

class CourierBilletage(db.Model):
    """Cash counting for courier money received"""
    id = db.Column(db.Integer, primary_key=True)
    courier_id = db.Column(db.Integer, db.ForeignKey('courier.id'), nullable=False)
    
    # AED denominations
    aed_1000 = db.Column(db.Integer, default=0)
    aed_500 = db.Column(db.Integer, default=0)
    aed_200 = db.Column(db.Integer, default=0)
    aed_100 = db.Column(db.Integer, default=0)
    aed_50 = db.Column(db.Integer, default=0)
    aed_20 = db.Column(db.Integer, default=0)
    aed_10 = db.Column(db.Integer, default=0)
    aed_5 = db.Column(db.Integer, default=0)
    
    # Euro denominations
    euro_500 = db.Column(db.Integer, default=0)
    euro_200 = db.Column(db.Integer, default=0)
    euro_100 = db.Column(db.Integer, default=0)
    euro_50 = db.Column(db.Integer, default=0)
    euro_20 = db.Column(db.Integer, default=0)
    euro_10 = db.Column(db.Integer, default=0)
    euro_5 = db.Column(db.Integer, default=0)
    
    # Exchange rate for Euro to AED conversion
    euro_to_aed_rate = db.Column(db.Float, nullable=False)
    
    # Calculated totals
    total_aed = db.Column(db.Float, nullable=False)
    total_euro_in_aed = db.Column(db.Float, nullable=False)
    total_counted = db.Column(db.Float, nullable=False)
    expected_amount = db.Column(db.Float, nullable=False)
    difference = db.Column(db.Float, nullable=False)
    
    # Metadata
    notes = db.Column(db.Text)
    counted_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    counted_by_user = db.relationship('User', foreign_keys=[counted_by])
