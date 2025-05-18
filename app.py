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
    delivered_containers = Container.query.filter_by(status='delivered').all()
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

@app.route('/container/<int:id>/add_client', methods=['POST'])
@login_required
def add_client_to_container(id):
    try:
        container = Container.query.get_or_404(id)
        
        # Get form data with validation
        name = request.form.get('client_name', '').strip()
        mark = request.form.get('client_mark', '').strip()
        phone = request.form.get('client_phone', '').strip()
        
        # Validate numeric inputs
        volume = request.form.get('volume', '')
        price = request.form.get('price', '')
        paid_amount = request.form.get('paid_amount', '0')
        
        # Convert to float with validation
        try:
            volume = float(volume) if volume else 0.0
            price = float(price) if price else 0.0
            paid_amount = float(paid_amount) if paid_amount else 0.0
        except ValueError:
            return "Please enter valid numbers for volume, price, and paid amount", 400
        
        payment_status = request.form.get('payment_status', 'unpaid')
        extra_charge = float(request.form.get('extra_charge', 0))
        
        # Validate required fields
        if not name or not mark or volume <= 0 or price <= 0:
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
            paid_amount=paid_amount if payment_status == 'partial' else (price if payment_status == 'paid' else 0)
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
        
        # Update client info
        client.name = request.form.get('client_name')
        client.mark = request.form.get('client_mark')
        client.phone = request.form.get('client_phone')
        
        # Update shipment info
        shipment.volume = float(request.form.get('volume'))
        shipment.price = float(request.form.get('price'))
        shipment.extra_charge = float(request.form.get('extra_charge', 0))
        
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
    
    # Get containers and separate them by status
    containers = Container.query.all()
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
    
    # Get all active containers grouped by destination
    all_containers = Container.query.filter(Container.status != 'delivered').all()
    for container in all_containers:
        if container.destination not in containers_by_destination:
            containers_by_destination[container.destination] = []
        containers_by_destination[container.destination].append(container)
    
    # If searching for a specific container
    if search_query:
        selected_container = Container.query.filter(
            Container.container_number == search_query,
            Container.status != 'delivered'
        ).first()
    
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
    products = Product.query.filter_by(client_id=id).all()
    # Get container status for this client's latest shipment
    latest_shipment = Shipment.query.filter_by(client_id=id).order_by(Shipment.id.desc()).first()
    container_delivered = latest_shipment.container.status == 'delivered' if latest_shipment else False
    
    return render_template('products.html', 
                         client=client, 
                         products=products,
                         container_delivered=container_delivered)

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
            
            # Create shipment
            shipment = Shipment(
                client=client,
                container=container,
                volume=float(row['Volume']),
                price=round((container.price / container.total_volume) * float(row['Volume'])),
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
    
    # Search for clients across all active and delivered containers
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
        db.or_(
            Client.mark.ilike(f'%{search_term}%'),
            Client.name.ilike(f'%{search_term}%'),
            Client.phone.ilike(f'%{search_term}%')
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5002)))
