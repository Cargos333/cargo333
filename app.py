from flask import render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from db_config import app, db
from models import Container, Client, Shipment, User, Product
from decorators import admin_required, secretary_required, manager_required
from utils import format_number
import pandas as pd
import io
from io import BytesIO
import os

# Add these constants at the top of the file
CONTAINER_TYPES = ['40ft', '20ft']
DESTINATIONS = ['Moroni', 'Mutsamudu']

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

app.jinja_env.filters['format_number'] = format_number

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Routes
@app.route('/add-container')
@login_required
@secretary_required
def add_container():
    return render_template('add_container.html')

@app.route('/history')
@login_required
def history():
    # Change ordering to descending by ID
    delivered_containers = Container.query.filter_by(status='delivered').order_by(Container.id.desc()).all()
    return render_template('history.html', containers=delivered_containers)

@app.route('/')
@login_required
def dashboard():
    if current_user.role == 'Manager':
        return redirect(url_for('container_search'))
        
    # Use a consistent ordering by id instead of status-based ordering
    containers = Container.query.filter(Container.status != 'delivered').order_by(Container.id.desc()).all()
    
    # Keep the rest of the stats calculation the same
    total_containers = Container.query.count()
    active_containers = Container.query.filter(Container.status != 'delivered').count()
    total_clients = db.session.query(Client.mark).distinct().count()
    total_delivered = Container.query.filter_by(status='delivered').count()
    
    return render_template('dashboard.html', 
                         containers=containers,
                         total_containers=total_containers,
                         active_containers=active_containers,
                         total_clients=total_clients,
                         total_delivered=total_delivered,
                         container_types=CONTAINER_TYPES,
                         destinations=DESTINATIONS)

@app.route('/container/<int:id>')
@login_required
def container_details(id):
    # Load container
    container = Container.query.get_or_404(id)
    
    # Load shipments with explicit ordering to ensure consistent display
    shipments = Shipment.query.filter_by(container_id=id).order_by(Shipment.id).all()
    
    # Replace container.shipments with our ordered shipments for the template
    container.shipments = shipments
    
    return render_template('container_details.html', container=container)

@app.route('/container/create', methods=['POST'])
@login_required
def create_container():
    container_number = request.form.get('container_number')
    container_name = request.form.get('container_name')
    container_type = request.form.get('container_type')
    total_volume = float(request.form.get('total_volume'))
    price = float(request.form.get('price'))
    destination = request.form.get('destination')
    
    new_container = Container(
        container_number=container_number,
        container_name=container_name,
        container_type=container_type,
        total_volume=total_volume,
        price=price,
        destination=destination
    )
    
    db.session.add(new_container)
    db.session.commit()
    
    return redirect(url_for('dashboard'))

# Add this utility function to ensure consistent price calculation
def calculate_client_price(container_price, container_volume, client_volume, extra_charge=0):
    """
    Calculate client price based on container price and volume
    Uses the same logic in both back-end and front-end
    """
    # Ensure all values are floats and avoid division by zero
    container_price = float(container_price)
    container_volume = max(float(container_volume), 0.001)  # Avoid division by zero
    client_volume = float(client_volume)
    extra_charge = float(extra_charge) if extra_charge else 0
    
    # Calculate base price using the proportion of volume
    base_price = round((container_price / container_volume) * client_volume)
    
    # Add extra charge to get total price
    total_price = base_price + extra_charge
    
    return base_price, round(total_price)

@app.route('/container/<int:id>/add_client', methods=['POST'])
@login_required
def add_client_to_container(id):
    try:
        container = Container.query.get_or_404(id)
        
        # Get form data with validation
        name = request.form.get('client_name', '').strip()
        mark = request.form.get('client_mark', '').strip()
        phone = request.form.get('client_phone', '').strip()
        
        # Check for outstanding payments before adding client
        clients_with_same_mark = Client.query.filter(Client.mark.ilike(mark)).all()
        
        if clients_with_same_mark:
            client_ids = [c.id for c in clients_with_same_mark]
            # Check for outstanding payments
            outstanding_payments = db.session.query(Shipment).join(
                Container, Shipment.container_id == Container.id
            ).filter(
                Shipment.client_id.in_(client_ids),
                Container.status == 'delivered',
                Shipment.payment_status.in_(['unpaid', 'partial'])
            ).all()
            
            # Log if we found outstanding payments
            if outstanding_payments:
                app.logger.info(f"Client mark {mark} has {len(outstanding_payments)} outstanding payments but proceeding with adding to container")
        
        # Validate numeric inputs
        volume = request.form.get('volume', '')
        extra_charge = float(request.form.get('extra_charge', 0))
        
        # Convert to float with validation
        try:
            volume = float(volume) if volume else 0.0
            price, total_price = calculate_client_price(container.price, container.total_volume, volume, extra_charge)
        except ValueError:
            return "Please enter valid numbers for volume and extra charge", 400
        
        payment_status = request.form.get('payment_status', 'unpaid')
        paid_amount = request.form.get('paid_amount', '0')
        
        try:
            paid_amount = float(paid_amount) if paid_amount else 0.0
        except ValueError:
            return "Please enter a valid number for paid amount", 400
            
        # Validate required fields
        if not name or not mark or volume <= 0:
            return "Please fill all required fields with valid values", 400
            
        # Create new client
        client = Client(name=name, mark=mark, phone=phone)
        db.session.add(client)
        
        # Create shipment with payment info
        shipment = Shipment(
            client=client,
            container=container,
            volume=volume,
            price=price,
            extra_charge=extra_charge,
            payment_status=payment_status,
            paid_amount=paid_amount if payment_status == 'partial' else (price + extra_charge if payment_status == 'paid' else 0)
        )
        
        db.session.add(shipment)
        db.session.commit()
        
        return redirect(url_for('container_details', id=id))
    except Exception as e:
        db.session.rollback()
        return f"An error occurred: {str(e)}", 400

@app.route('/container/<int:id>/delete', methods=['POST'])
@login_required
def delete_container(id):
    container = Container.query.get_or_404(id)
    try:
        # Get all clients associated with this container
        clients_to_delete = set()
        for shipment in container.shipments:
            client = shipment.client
            # Check if client has shipments in other containers
            if len(client.shipments) == 1:  # Only in this container
                clients_to_delete.add(client)
        
        # Delete all shipments first
        Shipment.query.filter_by(container_id=id).delete()
        
        # Delete clients that were only in this container
        for client in clients_to_delete:
            db.session.delete(client)
            
        # Delete container
        db.session.delete(container)
        db.session.commit()
        return redirect(url_for('dashboard'))
    except Exception as e:
        db.session.rollback()
        return f"Error deleting container: {str(e)}", 400

@app.route('/container/<int:id>/deliver', methods=['POST'])
@login_required
def deliver_container(id):
    container = Container.query.get_or_404(id)
    container.status = 'delivered'
    # Clear PDF data when container is delivered
    container.connaissement_pdf = None
    container.pdf_filename = None
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/container/<int:id>/toggle-priority', methods=['POST'])
@login_required
def toggle_container_priority(id):
    container = Container.query.get_or_404(id)
    container.sur_et_start = not container.sur_et_start
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/container/<int:id>/edit', methods=['POST'])
@login_required
def edit_container(id):
    try:
        container = Container.query.get_or_404(id)
        
        container.container_number = request.form.get('container_number')
        container.container_name = request.form.get('container_name')
        container.container_type = request.form.get('container_type')
        container.total_volume = float(request.form.get('total_volume'))
        container.price = float(request.form.get('price'))
        container.destination = request.form.get('destination')
        
        db.session.commit()
        flash('Container updated successfully')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating container: {str(e)}')
    
    return redirect(url_for('dashboard'))

@app.route('/shipment/<int:id>/update_payment', methods=['POST'])
@login_required
def update_payment(id):
    shipment = Shipment.query.get_or_404(id)
    payment_status = request.form.get('payment_status')
    paid_amount = float(request.form.get('paid_amount', 0))
    
    shipment.payment_status = payment_status
    shipment.paid_amount = paid_amount if payment_status == 'partial' else (shipment.price if payment_status == 'paid' else 0)
    
    db.session.commit()
    return redirect(url_for('container_details', id=shipment.container_id))

@app.route('/shipment/<int:id>/edit', methods=['POST'])
@login_required
def edit_shipment(id):
    try:
        shipment = Shipment.query.get_or_404(id)
        client = shipment.client
        container = shipment.container
        
        # Update client info
        client.name = request.form.get('client_name')
        client.mark = request.form.get('client_mark')
        client.phone = request.form.get('client_phone')
        
        # Update shipment info
        new_volume = float(request.form.get('volume'))
        extra_charge = float(request.form.get('extra_charge', 0))
        
        # Use the common price calculation function
        base_price, _ = calculate_client_price(container.price, container.total_volume, new_volume)
        
        shipment.volume = new_volume
        shipment.price = base_price  # Use calculated base price
        shipment.extra_charge = extra_charge
        
        # Update payment info
        payment_status = request.form.get('payment_status')
        shipment.payment_status = payment_status
        shipment.paid_amount = (
            float(request.form.get('paid_amount', 0)) if payment_status == 'partial'
            else (shipment.price if payment_status == 'paid' else 0)
        )
        
        db.session.commit()
        return redirect(url_for('container_details', id=shipment.container_id))
    except Exception as e:
        db.session.rollback()
        return f"Error editing shipment: {str(e)}", 400

@app.route('/shipment/<int:id>/delete', methods=['POST'])
@login_required
def delete_shipment(id):
    shipment = Shipment.query.get_or_404(id)
    container_id = shipment.container_id
    try:
        client = shipment.client
        db.session.delete(shipment)
        
        # Delete client if they have no other shipments
        if len(client.shipments) <= 1:
            db.session.delete(client)
        
        db.session.commit()
        return redirect(url_for('container_details', id=container_id))
    except Exception as e:
        db.session.rollback()
        return f"Error deleting shipment: {str(e)}", 400

@app.route('/clients')
@login_required
@secretary_required
def clients():
    search_query = request.args.get('search', '').strip()
    selected_container = request.args.get('container')
    active_containers = {}
    history_containers = {}
    
    # Get containers in descending order by ID
    containers = Container.query.order_by(Container.id.desc()).all()
    for container in containers:
        if search_query:
            container_clients = Client.query.join(Client.shipments)\
                .filter(Shipment.container_id == container.id)\
                .filter(db.or_(
                    Client.name.ilike(f'%{search_query}%'),
                    Client.mark.ilike(f'%{search_query}%'),
                    Client.phone.ilike(f'%{search_query}%')
                )).all()
        else:
            container_clients = [shipment.client for shipment in container.shipments]
        
        if container_clients:
            if container.status == 'delivered':
                history_containers[container] = container_clients
            else:
                active_containers[container] = container_clients
    
    return render_template('clients.html', 
                         active_containers=active_containers,
                         history_containers=history_containers,
                         search_query=search_query,
                         selected_container=selected_container)

@app.route('/client/<int:id>/delete', methods=['POST'])
@login_required
def delete_client(id):
    client = Client.query.get_or_404(id)
    try:
        # Delete associated shipments first
        Shipment.query.filter_by(client_id=id).delete()
        # Delete client
        db.session.delete(client)
        db.session.commit()
        return redirect(url_for('clients'))
    except Exception as e:
        db.session.rollback()
        return f"Error deleting client: {str(e)}", 400

@app.route('/client/get_by_mark/<mark>')
@login_required
def get_client_by_mark(mark):
    client = Client.query.filter_by(mark=mark).first()
    if client:
        return {
            'name': client.name,
            'phone': client.phone
        }
    return {'error': 'Client not found'}, 404

@app.route('/container-search')
@login_required
@manager_required
def container_search():
    search_query = request.args.get('search', '').strip()
    selected_container = None
    containers_by_destination = {}
    
    # Get all active containers in descending order by ID
    all_containers = Container.query.filter(Container.status != 'delivered').order_by(Container.id.desc()).all()
    for container in all_containers:
        if container.destination not in containers_by_destination:
            containers_by_destination[container.destination] = []
        containers_by_destination[container.destination].append(container)
    
    # If searching for a specific container
    if search_query:
        # First try exact match on container number
        selected_container = Container.query.filter(
            Container.container_number == search_query,
            Container.status != 'delivered'
        ).first()
        
        # If not found, try a broader search that includes partial matches in the container number
        if not selected_container:
            selected_container = Container.query.filter(
                Container.container_number.ilike(f"%{search_query}%"),
                Container.status != 'delivered'
            ).first()
        
        # If found, load the shipments to ensure they're available for display
        if selected_container:
            # Explicitly load shipments with ordering to ensure consistent display
            selected_container.shipments = Shipment.query.filter_by(container_id=selected_container.id).order_by(Shipment.id).all()
    
    return render_template('container_search.html', 
                         containers_by_destination=containers_by_destination,
                         selected_container=selected_container, 
                         search_query=search_query)

@app.route('/employees')
@login_required
@admin_required
def employees():
    if not current_user.is_admin():
        return redirect(url_for('dashboard'))
    employees = User.query.all()
    return render_template('employees.html', employees=employees)

@app.route('/employee/add', methods=['POST'])
@login_required
def add_employee():
    if not current_user.is_admin():
        return redirect(url_for('dashboard'))
    
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role')
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    
    if User.query.filter_by(username=username).first():
        flash('Username already exists')
        return redirect(url_for('employees'))
    
    employee = User(
        username=username,
        password=generate_password_hash(password),
        role=role,
        full_name=full_name,
        email=email,
        phone=phone
    )
    
    db.session.add(employee)
    db.session.commit()
    return redirect(url_for('employees'))

@app.route('/employee/<int:id>/delete', methods=['POST'])
@login_required
def delete_employee(id):
    if not current_user.is_admin():
        return redirect(url_for('dashboard'))
    
    if id == current_user.id:
        flash('Cannot delete your own account')
        return redirect(url_for('employees'))
    
    employee = User.query.get_or_404(id)
    db.session.delete(employee)
    db.session.commit()
    return redirect(url_for('employees'))

@app.route('/client/<int:id>/products')
@login_required
def client_products(id):
    client = Client.query.get_or_404(id)
    
    # Get container ID from query parameter if provided
    container_id = request.args.get('container_id', type=int)
    
    # Get container status for this client's latest shipment
    latest_shipment = Shipment.query.filter_by(client_id=id).order_by(Shipment.id.desc()).first()
    container_delivered = latest_shipment.container.status == 'delivered' if latest_shipment else False
    
    # Get the container information to show in print view
    # If container_id is provided, use that container, otherwise use the latest shipment's container
    if container_id:
        container = Container.query.get_or_404(container_id)
        # Make sure the client has a shipment in this container
        shipment = Shipment.query.filter_by(client_id=id, container_id=container_id).first_or_404()
    else:
        container = latest_shipment.container if latest_shipment else None
    
    # Get products - all products belong to the client regardless of container
    products = Product.query.filter_by(client_id=id).all()
    
    # Check if we're coming from container details to show a "back" button
    from_container = bool(container_id)
    
    return render_template('products.html', 
                         client=client, 
                         products=products,
                         container_delivered=container_delivered,
                         container=container,
                         from_container=from_container,
                         container_id=container_id)  # Pass container information

@app.route('/client/<int:id>/add_product', methods=['POST'])
@login_required
def add_product(id):
    try:
        client = Client.query.get_or_404(id)
        
        reference = request.form.get('reference')
        quantity = int(request.form.get('quantity'))
        length = float(request.form.get('length'))
        width = float(request.form.get('width'))
        height = float(request.form.get('height'))
        
        product = Product(
            client_id=id,
            reference=reference,
            quantity=quantity,
            length=length,
            width=width,
            height=height,
            volume=length * width * height * quantity
        )
        
        db.session.add(product)
        db.session.commit()
        
        return redirect(url_for('client_products', id=id))
    except Exception as e:
        db.session.rollback()
        return f"Error adding product: {str(e)}", 400

@app.route('/product/<int:id>/edit', methods=['POST'])
@login_required
def edit_product(id):
    try:
        product = Product.query.get_or_404(id)
        
        product.reference = request.form.get('reference')
        product.quantity = int(request.form.get('quantity'))
        product.length = float(request.form.get('length'))
        product.width = float(request.form.get('width'))
        product.height = float(request.form.get('height'))
        product.volume = product.length * product.width * product.height * product.quantity
        
        db.session.commit()
        return redirect(url_for('client_products', id=product.client_id))
    except Exception as e:
        db.session.rollback()
        return f"Error editing product: {str(e)}", 400

@app.route('/product/<int:id>/delete', methods=['POST'])
@login_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    client_id = product.client_id
    try:
        db.session.delete(product)
        db.session.commit()
        return redirect(url_for('client_products', id=client_id))
    except Exception as e:
        db.session.rollback()
        return f"Error deleting product: {str(e)}", 400

@app.route('/client/<int:client_id>/delete_products', methods=['POST'])
@login_required
def delete_multiple_products(client_id):
    try:
        client = Client.query.get_or_404(client_id)
        
        # Get product IDs from form
        product_ids_str = request.form.get('product_ids', '')
        if not product_ids_str:
            flash('No products selected')
            return redirect(url_for('client_products', id=client_id))
        
        # Convert comma-separated string to list of IDs
        product_ids = [int(id) for id in product_ids_str.split(',') if id.strip().isdigit()]
        
        # Query products belonging to this client and with matching IDs
        products = Product.query.filter(
            Product.client_id == client_id,
            Product.id.in_(product_ids)
        ).all()
        
        count = len(products)
        for product in products:
            db.session.delete(product)
        
        db.session.commit()
        flash(f'Successfully deleted {count} products')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting products: {str(e)}')
    
    return redirect(url_for('client_products', id=client_id))

@app.route('/download-template')
@login_required
def download_template():
    output = io.BytesIO()
    df = pd.DataFrame({
        'Client Mark': ['MARK001', 'MARK002'],
        'Client Name': ['Example Name 1', 'Example Name 2'],
        'Phone': ['1234567890', '0987654321'],  # Plain string format
        'Volume': [10.5, 15.2]
    })
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
        # Format phone column as text in Excel
        workbook = writer.book
        worksheet = writer.sheets['Sheet1']
        worksheet.column_dimensions['C'].number_format = '@'
    
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='clients_template.xlsx'
    )

@app.route('/container/<int:id>/upload-excel', methods=['POST'])
@login_required
def upload_excel(id):
    try:
        container = Container.query.get_or_404(id)
        if 'file' not in request.files:
            flash('No file uploaded')
            return redirect(url_for('container_details', id=id))
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected')
            return redirect(url_for('container_details', id=id))
        
        if not file.filename.endswith('.xlsx'):
            flash('Please upload an Excel file (.xlsx)')
            return redirect(url_for('container_details', id=id))
        
        # Read Excel file with phone column as string
        df = pd.read_excel(file, dtype={'Phone': str})
        
        # Process each row
        for _, row in df.iterrows():
            # Create client
            client = Client(
                name=str(row['Client Name']),
                mark=str(row['Client Mark']),
                phone=str(row['Phone']).split('.')[0] if pd.notna(row['Phone']) else '',  # Remove decimal part
            )
            db.session.add(client)
            
            client_volume = float(row['Volume'])
            # Use the common price calculation function
            base_price, _ = calculate_client_price(container.price, container.total_volume, client_volume)
            
            # Create shipment
            shipment = Shipment(
                client=client,
                container=container,
                volume=client_volume,
                price=base_price,  # Use calculated base price
                payment_status='unpaid'
            )
            db.session.add(shipment)
        
        db.session.commit()
        flash(f'Successfully imported {len(df)} clients')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing file: {str(e)}')
    
    return redirect(url_for('container_details', id=id))

@app.route('/download-products-template')
@login_required
def download_products_template():
    output = io.BytesIO()
    df = pd.DataFrame({
        'Reference': ['REF001', 'REF002'],
        'Quantity': [5, 10],
        'Length': [1.5, 2.0],
        'Width': [0.8, 1.0],
        'Height': [0.5, 0.7]
    })
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='products_template.xlsx'
    )

@app.route('/client/<int:id>/upload-products', methods=['POST'])
@login_required
def upload_products(id):
    try:
        client = Client.query.get_or_404(id)
        if 'file' not in request.files:
            flash('No file uploaded')
            return redirect(url_for('client_products', id=id))
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected')
            return redirect(url_for('client_products', id=id))
        
        if not file.filename.endswith('.xlsx'):
            flash('Please upload an Excel file (.xlsx)')
            return redirect(url_for('client_products', id=id))
        
        # Read Excel file
        df = pd.read_excel(file)
        
        # Define column mappings (English -> Application fields)
        column_mappings = {
            # English columns
            'Reference': 'Reference',
            'Quantity': 'Quantity',
            'Length': 'Length',
            'Width': 'Width',
            'Height': 'Height',
            # French columns
            'Items': 'Reference',
            'Longueur': 'Length',
            'Largeur': 'Width',
            'Hauteur': 'Height',
            'Qty': 'Quantity',
            'Volume': 'Volume'
        }
        
        # Rename columns based on mappings
        df_columns = df.columns.tolist()
        rename_dict = {}
        
        for col in df_columns:
            if col in column_mappings:
                rename_dict[col] = column_mappings[col]
        
        if rename_dict:
            df = df.rename(columns=rename_dict)
        
        # Process each row
        processed_count = 0
        for _, row in df.iterrows():
            # Get reference (required field)
            if 'Reference' not in df.columns or pd.isna(row.get('Reference')):
                continue  # Skip rows without a reference
                
            reference = str(row.get('Reference', ''))
            
            # Get other fields with defaults
            try:
                quantity = int(row.get('Quantity')) if pd.notna(row.get('Quantity')) else 1
            except (ValueError, TypeError):
                quantity = 1
                
            try:
                length = float(row.get('Length')) if pd.notna(row.get('Length')) else 0
            except (ValueError, TypeError):
                length = 0
                
            try:
                width = float(row.get('Width')) if pd.notna(row.get('Width')) else 0
            except (ValueError, TypeError):
                width = 0
                
            try:
                height = float(row.get('Height')) if pd.notna(row.get('Height')) else 0
            except (ValueError, TypeError):
                height = 0
            
            # Calculate volume or use 0 if any dimension is missing
            if length > 0 and width > 0 and height > 0:
                volume = length * width * height * quantity
            else:
                # Use Volume field if available, otherwise 0
                try:
                    volume = float(row.get('Volume')) if pd.notna(row.get('Volume')) else 0
                except (ValueError, TypeError):
                    volume = 0
            
            product = Product(
                client_id=id,
                reference=reference,
                quantity=quantity,
                length=length,
                width=width,
                height=height,
                volume=volume
            )
            db.session.add(product)
            processed_count += 1
        
        db.session.commit()
        flash(f'Successfully imported {processed_count} products')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing file: {str(e)}')
    
    return redirect(url_for('client_products', id=id))

@app.route('/container/<int:id>/upload-pdf', methods=['POST'])
@login_required
@manager_required
def upload_connaissement(id):
    container = Container.query.get_or_404(id)
    if 'pdf_file' not in request.files:
        flash('No file uploaded')
        return redirect(url_for('container_search'))
    
    file = request.files['pdf_file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('container_search'))
    
    if not file.filename.endswith('.pdf'):
        flash('Please upload a PDF file')
        return redirect(url_for('container_search'))
    
    container.connaissement_pdf = file.read()
    container.pdf_filename = file.filename
    db.session.commit()
    
    return redirect(url_for('container_search'))

@app.route('/container/<int:id>/download-pdf')
@login_required
def download_connaissement(id):
    container = Container.query.get_or_404(id)
    if not container.connaissement_pdf:
        flash('No PDF available')
        return redirect(url_for('container_search'))
    
    return send_file(
        BytesIO(container.connaissement_pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=container.pdf_filename or 'connaissement.pdf'
    )

@app.route('/api/search-clients')
@login_required
def search_clients():
    search_term = request.args.get('term', '').strip()
    
    if len(search_term) < 2:
        return jsonify([])
    
    # Search for clients across only active containers (not delivered)
    results = db.session.query(
        Client.mark, 
        Client.name, 
        Client.phone,
        Container.container_number,
        Container.id.label('container_id'),
        Container.status.label('container_status'),
        Shipment.volume,
        Shipment.payment_status,
        Shipment.paid_amount
    ).join(
        Shipment, Client.id == Shipment.client_id
    ).join(
        Container, Shipment.container_id == Container.id
    ).filter(
        db.and_(
            Container.status != 'delivered',  # Only show active containers
            db.or_(
                Client.mark.ilike(f'%{search_term}%'),
                Client.name.ilike(f'%{search_term}%'),
                Client.phone.ilike(f'%{search_term}%')
            )
        )
    ).all()
    
    # Format results for JSON response
    formatted_results = []
    for result in results:
        formatted_results.append({
            'mark': result.mark,
            'name': result.name,
            'phone': result.phone,
            'container_number': result.container_number,
            'container_id': result.container_id,
            'container_status': result.container_status,
            'volume': round(result.volume, 2),
            'payment_status': result.payment_status
        })
    
    return jsonify(formatted_results)

@app.route('/api/client-autocomplete')
@login_required
def client_autocomplete():
    term = request.args.get('term', '').strip()
    
    if len(term) < 2:
        return jsonify([])
    
    # Search for clients by mark, name, and phone, but only from active containers
    clients = db.session.query(
        Client.mark, 
        Client.name, 
        Client.phone
    ).join(
        Shipment, Client.id == Shipment.client_id
    ).join(
        Container, Shipment.container_id == Container.id
    ).filter(
        db.and_(
            Container.status != 'delivered',  # Exclude delivered containers
            db.or_(
                Client.mark.ilike(f'%{term}%'),
                Client.name.ilike(f'%{term}%'),
                Client.phone.ilike(f'%{term}%')
            )
        )
    ).distinct().limit(20).all()
    
    # Format results for autocomplete
    results = []
    for client in clients:
        display_text = f"{client.mark} - {client.name}"
        if client.phone:
            display_text += f" ({client.phone})"
            
        results.append({
            'value': client.mark,  # Value that goes into search box when selected
            'label': display_text, # Text shown in dropdown
            'mark': client.mark,
            'name': client.name,
            'phone': client.phone
        })
    
    return jsonify(results)

@app.route('/api/shipment-details/<int:id>')
@login_required
def get_shipment_details(id):
    """API endpoint to get shipment details for printing receipts"""
    try:
        shipment = Shipment.query.get_or_404(id)
        total = shipment.price + shipment.extra_charge
        
        return jsonify({
            'total': total,
            'price': shipment.price,
            'extra_charge': shipment.extra_charge,
            'payment_status': shipment.payment_status,
            'paid_amount': shipment.paid_amount if shipment.paid_amount else 0,
            'volume': shipment.volume
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/payments-tracker')
@login_required
def payments_tracker():
    """Page to track clients with unpaid or partially paid shipments in delivered containers"""
    
    # Get filters from query parameters
    container_filter = request.args.get('container', '')
    payment_filter = request.args.get('payment_status', '')
    search_query = request.args.get('search', '').strip()
    
    # Base query to get unpaid or partially paid shipments from DELIVERED containers only
    query = db.session.query(
        Shipment, Client, Container
    ).join(
        Client, Shipment.client_id == Client.id
    ).join(
        Container, Shipment.container_id == Container.id
    ).filter(
        Container.status == 'delivered',  # Only show delivered containers
        Shipment.payment_status.in_(['unpaid', 'partial'])
    )
    
    # Apply filters if provided
    if container_filter:
        query = query.filter(Container.id == container_filter)
    
    if payment_filter:
        query = query.filter(Shipment.payment_status == payment_filter)
        
    if search_query:
        query = query.filter(
            db.or_(
                Client.name.ilike(f'%{search_query}%'),
                Client.mark.ilike(f'%{search_query}%'),
                Client.phone.ilike(f'%{search_query}%'),
                Container.container_number.ilike(f'%{search_query}%')
            )
        )
    
    # Get all results - change ordering to descending by container ID
    results = query.order_by(Container.id.desc(), Client.name).all()
    
    # Get all containers for the filter dropdown - only delivered ones
    containers = Container.query.filter_by(status='delivered').order_by(
        Container.id.desc()
    ).all()
    
    # Calculate statistics
    total_unpaid = sum([(s.price + s.extra_charge - (s.paid_amount or 0)) for s, c, cont in results])
    total_items = len(results)
    unpaid_count = len([s for s, c, cont in results if s.payment_status == 'unpaid'])
    partial_count = len([s for s, c, cont in results if s.payment_status == 'partial'])
    
    return render_template(
        'payments_tracker.html',
        results=results,
        containers=containers,
        container_filter=container_filter,
        payment_filter=payment_filter,
        search_query=search_query,
        total_unpaid=total_unpaid,
        total_items=total_items,
        unpaid_count=unpaid_count,
        partial_count=partial_count
    )

@app.route('/shipment/<int:id>/mark-as-paid', methods=['POST'])
@login_required
def mark_shipment_paid(id):
    """Mark a shipment as paid from the payments tracker"""
    try:
        shipment = Shipment.query.get_or_404(id)
        
        # Set payment status to paid and update paid_amount
        shipment.payment_status = 'paid'
        shipment.paid_amount = shipment.price + shipment.extra_charge
        
        db.session.commit()
        flash(f'Payment for client {shipment.client.mark} has been marked as paid', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating payment status: {str(e)}', 'danger')
        
    # Return to payments tracker with original filters
    return redirect(request.referrer or url_for('payments_tracker'))

@app.route('/shipment/<int:id>/update-partial-payment', methods=['POST'])
@login_required
def update_partial_payment(id):
    """Update partial payment amount for a shipment"""
    try:
        shipment = Shipment.query.get_or_404(id)
        
        # Get the new paid amount from form
        paid_amount = float(request.form.get('paid_amount', 0))
        total_amount = shipment.price + shipment.extra_charge
        
        # Validate the amount (must be between 0 and total price)
        if paid_amount < 0 or paid_amount > total_amount:
            flash('Invalid payment amount', 'danger')
            return redirect(request.referrer or url_for('payments_tracker'))
        
        # Update payment status based on amount
        if paid_amount == 0:
            shipment.payment_status = 'unpaid'
        elif paid_amount >= total_amount:
            shipment.payment_status = 'paid'
            shipment.paid_amount = total_amount
        else:
            shipment.payment_status = 'partial'
            shipment.paid_amount = paid_amount
        
        db.session.commit()
        flash(f'Payment for client {shipment.client.mark} has been updated', 'success')
    except ValueError:
        flash('Please enter a valid payment amount', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating payment: {str(e)}', 'danger')
        
    # Return to payments tracker with original filters
    return redirect(request.referrer or url_for('payments_tracker'))

@app.route('/api/client-outstanding-payments/<mark>')
@login_required
def client_outstanding_payments(mark):
    """API endpoint to check if a client has outstanding payments from delivered containers"""
    try:
        # Always do a case-insensitive search to find all possible matches
        clients = Client.query.filter(Client.mark.ilike(mark.strip())).all()
        
        if not clients:
            return jsonify({"success": False, "message": "Client not found"}), 404
        
        # Get ALL client IDs that match this mark (case insensitive)
        client_ids = [c.id for c in clients]
        primary_client = clients[0] # Use the first matching client for name display
        
        # Log what we're searching for
        app.logger.info(f"Searching for outstanding payments for mark '{mark}', found clients: {client_ids}")
        
        # Find all shipments with unpaid balances for these client IDs
        outstanding_shipments = db.session.query(
            Shipment, Container
        ).join(
            Container, Shipment.container_id == Container.id
        ).filter(
            Shipment.client_id.in_(client_ids),
            Container.status == 'delivered',
            Shipment.payment_status.in_(['unpaid', 'partial'])
        ).all()
        
        # Debug info for the response
        total_outstanding = 0
        shipments_data = []
        
        for shipment, container in outstanding_shipments:
            # Calculate outstanding amount for this shipment
            total_price = shipment.price + shipment.extra_charge
            paid = shipment.paid_amount or 0
            outstanding = total_price - paid
            
            # Only include if there's an actual outstanding amount
            if outstanding > 0:
                total_outstanding += outstanding
                
                shipments_data.append({
                    'container_number': container.container_number,
                    'outstanding': outstanding,
                    'total_price': total_price,
                    'paid': paid,
                    'shipment_id': shipment.id,
                    'client_id': shipment.client_id,
                    'payment_status': shipment.payment_status
                })
        
        # Log what we found
        app.logger.info(f"Found {len(shipments_data)} outstanding payments totaling AED {total_outstanding}")
        
        return jsonify({
            'success': True,
            'client_name': primary_client.name,
            'client_mark': primary_client.mark,
            'total_outstanding': total_outstanding,
            'shipments': shipments_data,
            'has_outstanding': len(shipments_data) > 0
        })
        
    except Exception as e:
        app.logger.error(f"Error checking outstanding payments: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/resolve-outstanding-payments', methods=['POST'])
@login_required
def resolve_outstanding_payments():
    """API endpoint to resolve outstanding payments by adding them as extra charge"""
    try:
        shipment_id = request.form.get('shipment_id')
        extra_charge = float(request.form.get('extra_charge', 0))
        client_mark = request.form.get('client_mark')
        resolve_outstanding = request.form.get('resolve_outstanding') == 'true'
        
        # For the case where we're adding a new client (no shipment_id yet)
        new_client = request.form.get('new_client') == 'true'
        
        if (not shipment_id and not new_client) or not client_mark:
            return jsonify({'success': False, 'message': 'Missing required parameters'}), 400
            
        # If shipment_id exists, update that shipment's extra charge
        if shipment_id and not new_client:
            # Get the current shipment
            shipment = Shipment.query.get_or_404(shipment_id)
            
            # Update the extra charge
            shipment.extra_charge = extra_charge
        
        # Mark outstanding payments as resolved if requested
        if resolve_outstanding:
            # Get client by mark - make sure to find ALL matching clients 
            clients = Client.query.filter(Client.mark.ilike(client_mark.strip())).all()
            
            total_shipments_updated = 0
            
            for client in clients:
                # Find all outstanding shipments for this client in DELIVERED containers
                outstanding_shipments = db.session.query(Shipment).join(
                    Container, Shipment.container_id == Container.id
                ).filter(
                    Shipment.client_id == client.id,
                    Container.status == 'delivered',
                    Shipment.payment_status.in_(['unpaid', 'partial'])
                ).all()
                
                # Mark all as paid
                for os in outstanding_shipments:
                    total_amount = os.price + os.extra_charge
                    os.payment_status = 'paid'
                    os.paid_amount = total_amount
                    total_shipments_updated += 1
                
                app.logger.info(f"Marked {len(outstanding_shipments)} shipments as paid for client {client.mark} (ID: {client.id})")
            
            # Explicitly commit changes to ensure they're saved to database
            db.session.commit()
            app.logger.info(f"Total of {total_shipments_updated} shipments marked as paid across all clients with mark '{client_mark}'")
                
        # Final commit to ensure all changes are saved
        db.session.commit()
        return jsonify({'success': True, 'shipments_updated': total_shipments_updated if resolve_outstanding else 0})
        
    except Exception as e:
        app.logger.error(f"Error in resolve_outstanding_payments: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/client-records')
@login_required
def client_records():
    """Page to display detailed records of all clients"""
    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Number of records per page
    
    # Explicitly check the group_by_mark value - it should always be present now
    group_by_mark_param = request.args.get('group_by_mark', 'true')
    # Convert string to boolean - anything other than 'true' (case-insensitive) is False
    group_by_mark = group_by_mark_param.lower() == 'true'
    
    if group_by_mark:
        # First, get unique client marks
        subq = db.session.query(
            Client.mark, 
            db.func.min(Client.id).label('min_id')
        ).group_by(Client.mark)
        
        if search_query:
            subq = subq.filter(
                db.or_(
                    Client.mark.ilike(f'%{search_query}%'),
                    Client.name.ilike(f'%{search_query}%'),
                    Client.phone.ilike(f'%{search_query}%')
                )
            )
        
        subq = subq.subquery()
        
        # Now, get one client per unique mark
        client_query = db.session.query(Client).join(
            subq,
            Client.id == subq.c.min_id
        )
    else:
        # Base query for clients (show all)
        client_query = Client.query
        
        # Apply search if provided
        if search_query:
            client_query = client_query.filter(
                db.or_(
                    Client.name.ilike(f'%{search_query}%'),
                    Client.mark.ilike(f'%{search_query}%'),
                    Client.phone.ilike(f'%{search_query}%')
                )
            )
    
    # Get paginated clients
    pagination = client_query.order_by(Client.mark).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    clients = pagination.items
    
    # Get client marks for looking up duplicates
    all_marks = {c.mark.lower(): [] for c in clients}
    duplicate_client_ids = []
    
    # Find all clients with same marks and collect their IDs
    if group_by_mark:
        for client in clients:
            # Get all clients with the same mark
            duplicate_clients = Client.query.filter(
                db.func.lower(Client.mark) == client.mark.lower()
            ).all()
            all_marks[client.mark.lower()] = duplicate_clients
            
            # Add their IDs to our list for data collection
            for dup in duplicate_clients:
                duplicate_client_ids.append(dup.id)
    
    # Get all client IDs we need to fetch data for
    client_ids = duplicate_client_ids if group_by_mark else [c.id for c in clients]
    
    # Get all shipments for these clients
    all_shipments = db.session.query(
        Shipment, Client, Container
    ).join(
        Client, Shipment.client_id == Client.id
    ).join(
        Container, Shipment.container_id == Container.id
    ).filter(
        Shipment.client_id.in_(client_ids)
    ).all()
    
    # Organize shipments by client ID
    client_shipments = {}
    for shipment, client, container in all_shipments:
        if client.id not in client_shipments:
            client_shipments[client.id] = []
        client_shipments[client.id].append((shipment, container))
    
    # Get volumes, product counts, and latest containers for all clients
    volumes_dict = {}
    product_counts_dict = {}
    latest_container_dict = {}
    outstanding_dict = {}
    
    # For each client, calculate their stats
    for client_id in client_ids:
        # Get this client's shipments
        shipments_list = client_shipments.get(client_id, [])
        
        # Calculate total volume
        total_volume = sum(shipment.volume for shipment, _ in shipments_list)
        volumes_dict[client_id] = total_volume
        
        # Count shipments
        shipment_count = len(shipments_list)
        
        # Get product count for this client
        product_count = db.session.query(db.func.count(Product.id)).filter(
            Product.client_id == client_id
        ).scalar()
        product_counts_dict[client_id] = product_count
        
        # Find latest container
        if shipments_list:
            # Sort by shipment ID to get the newest one
            latest_shipment, latest_container = max(shipments_list, key=lambda x: x[0].id)
            latest_container_dict[client_id] = latest_container
            
            # Calculate outstanding payments
            outstanding = 0
            for shipment, container in shipments_list:
                if container.status == 'delivered' and shipment.payment_status in ['unpaid', 'partial']:
                    total_price = shipment.price + shipment.extra_charge
                    paid = shipment.paid_amount or 0
                    outstanding += (total_price - paid)
            
            outstanding_dict[client_id] = outstanding
    
    # Build the enhanced records with all data from our efficient queries
    enhanced_records = []
    for client in clients:
        # Get all duplicates for this mark
        if group_by_mark and client.mark.lower() in all_marks:
            duplicates = all_marks[client.mark.lower()]
            duplicate_ids = [c.id for c in duplicates]
            duplicate_count = len(duplicates)
            
            # Create a list of detailed info for each duplicate client
            duplicate_details = []
            for dup in duplicates:
                # Get stats for this specific duplicate
                duplicate_details.append({
                    'client': dup,
                    'shipment_count': len(client_shipments.get(dup.id, [])),
                    'total_volume': volumes_dict.get(dup.id, 0),
                    'outstanding_payments': outstanding_dict.get(dup.id, 0),
                    'latest_container': latest_container_dict.get(dup.id),
                    'product_count': product_counts_dict.get(dup.id, 0)
                })
            
            # Aggregate stats for the main display
            enhanced_records.append({
                'client': client,
                'shipment_count': sum(len(client_shipments.get(cid, [])) for cid in duplicate_ids),
                'total_volume': sum(volumes_dict.get(cid, 0) for cid in duplicate_ids),
                'outstanding_payments': sum(outstanding_dict.get(cid, 0) for cid in duplicate_ids),
                'latest_container': latest_container_dict.get(client.id),
                'product_count': sum(product_counts_dict.get(cid, 0) for cid in duplicate_ids),
                'duplicate_count': duplicate_count,
                'duplicates': duplicate_details
            })
        else:
            # Single client record
            enhanced_records.append({
                'client': client,
                'shipment_count': len(client_shipments.get(client.id, [])),
                'total_volume': volumes_dict.get(client.id, 0),
                'outstanding_payments': outstanding_dict.get(client.id, 0),
                'latest_container': latest_container_dict.get(client.id),
                'product_count': product_counts_dict.get(client.id, 0),
                'duplicate_count': 1,
                'duplicates': [{
                    'client': client,
                    'shipment_count': len(client_shipments.get(client.id, [])),
                    'total_volume': volumes_dict.get(client.id, 0),
                    'outstanding_payments': outstanding_dict.get(client.id, 0),
                    'latest_container': latest_container_dict.get(client.id),
                    'product_count': product_counts_dict.get(client.id, 0)
                }]
            })
    
    # Get total unique marks count for pagination
    if group_by_mark:
        total_clients = db.session.query(db.func.count(db.distinct(db.func.lower(Client.mark)))).scalar()
    else:
        total_clients = client_query.count()
    
    return render_template(
        'client_records.html',
        records=enhanced_records,
        search_query=search_query,
        total_clients=total_clients,
        pagination=pagination,
        group_by_mark=group_by_mark,
        client_shipments=client_shipments
    )

# Add new routes for editing and deleting clients

@app.route('/client/<int:id>/edit', methods=['POST'])
@login_required
def edit_client(id):
    """Edit client details"""
    try:
        client = Client.query.get_or_404(id)
        
        # Update client information
        client.name = request.form.get('name')
        client.mark = request.form.get('mark')
        client.phone = request.form.get('phone')
        
        db.session.commit()
        flash(f'Client "{client.mark}" updated successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating client: {str(e)}', 'danger')
    
    # Redirect back to the client records page with previous search/filters
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1)
    group_by_mark = request.args.get('group_by_mark', 'true')
    
    return redirect(url_for('client_records', search=search_query, page=page, group_by_mark=group_by_mark))

@app.route('/client/<int:id>/delete_from_records', methods=['POST'])
@login_required
def delete_client_from_records(id):
    """Delete client from client records"""
    try:
        client = Client.query.get_or_404(id)
        client_mark = client.mark  # Save for flash message
        
        # Check if client has products
        product_count = Product.query.filter_by(client_id=id).count()
        if product_count > 0:
            # Delete associated products
            Product.query.filter_by(client_id=id).delete()
        
        # Delete associated shipments
        Shipment.query.filter_by(client_id=id).delete()
        
        # Delete client
        db.session.delete(client)
        db.session.commit()
        
        flash(f'Client "{client_mark}" and all associated data deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting client: {str(e)}', 'danger')
    
    # Redirect back to the client records page with previous search/filters
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1)
    group_by_mark = request.args.get('group_by_mark', 'true')
    
    return redirect(url_for('client_records', search=search_query, page=page, group_by_mark=group_by_mark))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5002)))
