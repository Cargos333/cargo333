from flask import render_template, request, redirect, url_for, flash, send_file, jsonify, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import base64
from db_config import app, db
from models import Container, Client, Shipment, User, Product, ContainerDocument, Courier, CourierItem, FinanceRecord, Billetage, CourierBilletage, AirFreightPackage, AirFreightClient, AirFreightProduct, AirFreightUser
from decorators import admin_required, secretary_required, manager_required
from utils import format_number
import pandas as pd
import io
from io import BytesIO
import os
from datetime import datetime

# Add these constants at the top of the file
CONTAINER_TYPES = ['40ft', '20ft']
DESTINATIONS = ['Moroni', 'Mutsamudu']
# Conversion factor from tonne to cubic meters (adjustable via env: TONNE_TO_M3)
TONNE_TO_M3 = float(os.getenv('TONNE_TO_M3', '1'))
# Per-container defaults (can be overridden via env variables)
# Example: TONNE_TO_M3_20FT=1.1 TONNE_TO_M3_40FT=1.3
TONNE_TO_M3_20FT = float(os.getenv('TONNE_TO_M3_20FT', os.getenv('TONNE_TO_M3_20FT', '1')))
TONNE_TO_M3_40FT = float(os.getenv('TONNE_TO_M3_40FT', os.getenv('TONNE_TO_M3_40FT', '1')))

def get_tonne_to_m3_for_container(container_type: str) -> float:
    """Return conversion factor tonne -> m3 based on container type.

    Defaults fall back to TONNE_TO_M3, but can be overridden by
    TONNE_TO_M3_20FT / TONNE_TO_M3_40FT environment variables.
    """
    if not container_type:
        return TONNE_TO_M3
    ct = container_type.lower()
    if '20' in ct:
        return TONNE_TO_M3_20FT or TONNE_TO_M3
    if '40' in ct:
        return TONNE_TO_M3_40FT or TONNE_TO_M3
    return TONNE_TO_M3

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

app.jinja_env.filters['format_number'] = format_number

@login_manager.user_loader
def load_user(user_id):
    # Check if this is an air freight user (we'll use a session variable to distinguish)
    if session.get('air_freight_user'):
        return db.session.get(AirFreightUser, int(user_id))
    return db.session.get(User, int(user_id))

def air_freight_login_required(f):
    """Decorator to require air freight user login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not isinstance(current_user, AirFreightUser):
            return redirect(url_for('air_freight_login'))
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_new_courier_count():
    """Make `new_courier_count` available in all templates.

    Counts couriers that have no approved items (no CourierItem with is_received=True).
    """
    try:
        # If user is not authenticated, show zero
        if not current_user or not current_user.is_authenticated:
            return dict(new_courier_count=0)

        base_q = Courier.query.filter(~Courier.items.any(CourierItem.is_received == True))

        # For Secretary and Manager only, count couriers that have contact info (name or phone)
        if current_user.role in ['Secretary', 'Manager']:
            contact_filter = db.or_(
                db.and_(Courier.brought_by_name.isnot(None), Courier.brought_by_name != ''),
                db.and_(Courier.brought_by_phone.isnot(None), Courier.brought_by_phone != '')
            )
            base_q = base_q.filter(contact_filter)

        new_count = base_q.count()
    except Exception:
        new_count = 0

    return dict(new_courier_count=new_count)


@app.context_processor
def inject_air_freight_package_count():
    """Make `air_freight_package_count` available in all templates.

    Counts total AirFreight packages that are not yet delivered.
    """
    try:
        # If user is not authenticated or not admin, show zero
        if not current_user or not current_user.is_authenticated or current_user.role != 'Admin':
            return dict(air_freight_package_count=0)

        from models import AirFreightPackage
        package_count = AirFreightPackage.query.filter_by(delivered=False).count()
    except Exception:
        package_count = 0

    return dict(air_freight_package_count=package_count)


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
    # Support optional search by container number or container name
    search_query = request.args.get('search', '').strip()

    # Base query for delivered containers
    base_q = Container.query.filter_by(status='delivered')

    if search_query:
        # Case-insensitive search on container_number or container_name
        base_q = base_q.filter(db.or_(
            Container.container_number.ilike(f"%{search_query}%"),
            Container.container_name.ilike(f"%{search_query}%")
        ))

    # Order by descending ID for recent-first display
    delivered_containers = base_q.order_by(Container.id.desc()).all()
    return render_template('history.html', containers=delivered_containers, search_query=search_query)

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
@app.route('/container/<int:id>/client/<int:client_id>')
@login_required
def container_details(id, client_id=None):
    # Load container
    container = Container.query.get_or_404(id)
    
    # Load shipments with explicit ordering to ensure consistent display
    shipments = Shipment.query.filter_by(container_id=id).order_by(Shipment.id).all()
    
    # Replace container.shipments with our ordered shipments for the template
    container.shipments = shipments
    
    # Provide container-specific tonne->m3 conversion to the template
    container_tonne_to_m3 = get_tonne_to_m3_for_container(container.container_type)
    return render_template('container_details.html', container=container, TONNE_TO_M3=TONNE_TO_M3, container_tonne_to_m3=container_tonne_to_m3, highlight_client_id=client_id)

@app.route('/container/<int:id>/upload-documents', methods=['POST'])
@login_required
def upload_container_documents(id):
    """Upload documents (PDFs and images) for a container"""
    try:
        container = Container.query.get_or_404(id)
        
        if 'documents' not in request.files:
            return jsonify({'success': False, 'message': 'No files uploaded'}), 400
        
        files = request.files.getlist('documents')
        uploaded_count = 0
        
        for file in files:
            if file and file.filename:
                # Validate file type
                allowed_extensions = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}
                filename = file.filename.lower()
                file_ext = filename.rsplit('.', 1)[1] if '.' in filename else ''
                
                if file_ext not in allowed_extensions:
                    continue
                
                # Determine file type
                file_type = 'pdf' if file_ext == 'pdf' else 'image'
                
                # Read file data
                file_data = file.read()
                file_size = len(file_data)
                
                # Create unique filename
                import uuid
                unique_filename = f"{uuid.uuid4().hex}_{file.filename}"
                
                # Create document record
                document = ContainerDocument(
                    container_id=container.id,
                    filename=unique_filename,
                    original_filename=file.filename,
                    file_data=file_data,
                    file_type=file_type,
                    file_size=file_size,
                    uploaded_by=current_user.id
                )
                
                db.session.add(document)
                uploaded_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'{uploaded_count} document(s) uploaded successfully',
            'count': uploaded_count
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/container/<int:id>/download-documents')
@login_required
def download_container_documents(id):
    """Download all documents for a container as a ZIP file"""
    try:
        container = Container.query.get_or_404(id)
        documents = ContainerDocument.query.filter_by(container_id=id).all()
        
        if not documents:
            flash('No documents to download', 'warning')
            return redirect(url_for('container_details', id=id))
        
        # Create ZIP file in memory
        import io
        import zipfile
        
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for doc in documents:
                zf.writestr(doc.original_filename, doc.file_data)
        
        memory_file.seek(0)
        
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'container_{container.container_number}_documents.zip'
        )
    
    except Exception as e:
        flash(f'Error downloading documents: {str(e)}', 'danger')
        return redirect(url_for('container_details', id=id))

@app.route('/container/<int:container_id>/document/<int:doc_id>/download')
@login_required
def download_single_document(container_id, doc_id):
    """Download a single document"""
    try:
        document = ContainerDocument.query.get_or_404(doc_id)
        
        # Verify document belongs to this container
        if document.container_id != container_id:
            flash('Invalid document', 'danger')
            return redirect(url_for('container_details', id=container_id))
        
        # Determine mimetype based on file type
        if document.file_type == 'pdf':
            mimetype = 'application/pdf'
        else:
            # Determine image mimetype from extension
            ext = document.original_filename.rsplit('.', 1)[1].lower() if '.' in document.original_filename else 'png'
            mimetype = f'image/{ext}' if ext in ['png', 'jpg', 'jpeg', 'gif'] else 'application/octet-stream'
        
        import io
        return send_file(
            io.BytesIO(document.file_data),
            mimetype=mimetype,
            as_attachment=True,
            download_name=document.original_filename
        )
    
    except Exception as e:
        flash(f'Error downloading document: {str(e)}', 'danger')
        return redirect(url_for('container_details', id=container_id))

@app.route('/container/<int:container_id>/document/<int:doc_id>/view')
@login_required
def view_single_document(container_id, doc_id):
    """View/preview a single document (inline, not download)"""
    try:
        document = ContainerDocument.query.get_or_404(doc_id)
        
        # Verify document belongs to this container
        if document.container_id != container_id:
            return jsonify({'error': 'Invalid document'}), 400
        
        # Determine mimetype based on file type
        if document.file_type == 'pdf':
            mimetype = 'application/pdf'
        else:
            # Determine image mimetype from extension
            ext = document.original_filename.rsplit('.', 1)[1].lower() if '.' in document.original_filename else 'png'
            mimetype = f'image/{ext}' if ext in ['png', 'jpg', 'jpeg', 'gif'] else 'application/octet-stream'
        
        import io
        return send_file(
            io.BytesIO(document.file_data),
            mimetype=mimetype,
            as_attachment=False,  # Display inline instead of downloading
            download_name=document.original_filename
        )
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/container/<int:container_id>/document/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_container_document(container_id, doc_id):
    """Delete a single document"""
    try:
        document = ContainerDocument.query.get_or_404(doc_id)
        
        # Verify document belongs to this container
        if document.container_id != container_id:
            return jsonify({'success': False, 'message': 'Invalid document'}), 400
        
        db.session.delete(document)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Document deleted successfully'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

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
        # Goods type: 'Merchandise', 'Car', 'Metals'
        goods_type = request.form.get('goods_type', 'Merchandise')
        
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
        
        # Validate numeric inputs depending on goods type
        extra_charge = float(request.form.get('extra_charge', 0) or 0)

        # Compute volume and price according to goods type
        try:
            if goods_type == 'Merchandise':
                # Use the normal volume-based flow
                volume = float(request.form.get('volume', '') or 0)
                price, total_price = calculate_client_price(container.price, container.total_volume, volume, extra_charge)

            elif goods_type == 'Car':
                # For cars user provides empty volume (vide) and used volume; actual volume = vide - used
                volume_vide = float(request.form.get('volume_vide', '') or 0)
                volume_used = float(request.form.get('volume_used', '') or 0)
                volume = max(volume_vide - volume_used, 0)
                price, total_price = calculate_client_price(container.price, container.total_volume, volume, extra_charge)

            elif goods_type == 'Metals':
                # Metals are priced per tonne; we ask for tonnage and price per tonne
                tonnage = float(request.form.get('tonnage', '') or 0)
                price_per_tonne = float(request.form.get('price_per_tonne', '') or 0)
                # Convert tonne to volume for bookkeeping using container-specific conversion
                tonne_to_m3 = get_tonne_to_m3_for_container(container.container_type)
                volume = tonnage * tonne_to_m3
                # Use price per tonne * tonnage for base price instead of container proportion
                price = round(price_per_tonne * tonnage)
                total_price = round(price + extra_charge)
            else:
                # Fallback to merchandise behavior
                volume = float(request.form.get('volume', '') or 0)
                price, total_price = calculate_client_price(container.price, container.total_volume, volume, extra_charge)
        except ValueError:
            return "Please enter valid numeric values for the selected goods type and charges", 400
        
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
        # Include tonnage and price_per_tonne for Metals shipments
        shipment_kwargs = dict(
            client=client,
            container=container,
            volume=volume,
            price=price,
            extra_charge=extra_charge,
            payment_status=payment_status,
            paid_amount=paid_amount if payment_status == 'partial' else (price + extra_charge if payment_status == 'paid' else 0)
        )

        if goods_type == 'Metals':
            # Ensure variables exist in this scope (they were computed above)
            shipment_kwargs['tonnage'] = tonnage
            shipment_kwargs['price_per_tonne'] = price_per_tonne
        elif goods_type == 'Car':
            # Persist the car-specific inputs so we can show them in the table
            shipment_kwargs['volume_vide'] = volume_vide
            shipment_kwargs['volume_used'] = volume_used

        shipment = Shipment(**shipment_kwargs)
        
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
        
        # Store old values for comparison
        old_price = container.price
        old_volume = container.total_volume
        
        # Update container information
        container.container_number = request.form.get('container_number')
        container.container_name = request.form.get('container_name')
        container.container_type = request.form.get('container_type')
        container.total_volume = float(request.form.get('total_volume'))
        container.price = float(request.form.get('price'))
        container.destination = request.form.get('destination')
        # Optional: allow setting priority flag from edit form
        sur_et_start_val = request.form.get('sur_et_start')
        # The checkbox will be present as 'on' when checked in most browsers
        container.sur_et_start = bool(sur_et_start_val) and sur_et_start_val not in ('false', '0', '')
        
        # Check if price or volume changed - if so, recalculate all shipment prices
        price_changed = old_price != container.price
        volume_changed = old_volume != container.total_volume
        
        if price_changed or volume_changed:
            # Get all shipments for this container
            shipments = Shipment.query.filter_by(container_id=id).all()
            updated_count = 0
            
            for shipment in shipments:
                # Skip Metals shipments that have price_per_tonne set (manual pricing)
                if shipment.tonnage and shipment.price_per_tonne:
                    continue
                
                # Recalculate price based on new container price/volume
                base_price, total_price = calculate_client_price(
                    container.price, 
                    container.total_volume, 
                    shipment.volume, 
                    shipment.extra_charge
                )
                
                # Update shipment price (base price without extra charge)
                shipment.price = base_price
                updated_count += 1
            
            if updated_count > 0:
                flash(f'Container updated successfully. Recalculated prices for {updated_count} shipments.', 'success')
            else:
                flash('Container updated successfully.', 'success')
        else:
            flash('Container updated successfully.', 'success')
        
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating container: {str(e)}', 'danger')

    # After editing, return to the container details page so the user remains in context
    return redirect(url_for('container_details', id=id))

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
        
        # Update phone for ALL clients with the same mark (case-insensitive)
        posted_client_phone = request.form.get('client_phone')
        if posted_client_phone is not None and posted_client_phone != client.phone:
            # Find all clients with the same mark (case-insensitive)
            clients_with_same_mark = Client.query.filter(
                db.func.lower(Client.mark) == db.func.lower(client.mark)
            ).all()
            
            # Update phone for all matching clients
            for matching_client in clients_with_same_mark:
                matching_client.phone = posted_client_phone
        
        # Update shipment info
        # Support Metals edits: prefer tonnage/price_per_tonne when provided
        extra_charge = float(request.form.get('extra_charge', 0))

        # Try to read tonnage/price_per_tonne from form (may be absent)
        tonnage_form = request.form.get('tonnage')
        price_per_tonne_form = request.form.get('price_per_tonne')
    # Do NOT allow an explicit price override from the modal form. Any 'price' field
    # submitted by the client will be ignored to prevent tampering. Price is computed
    # server-side from tonnage/price_per_tonne or from calculated base price.

        # If tonnage provided -> Metals edit
        if tonnage_form is not None and price_per_tonne_form is not None and tonnage_form != '':
            try:
                tonnage_val = float(tonnage_form)
                ppt_val = float(price_per_tonne_form) if price_per_tonne_form != '' else 0
            except ValueError:
                return "Please enter valid numeric values for tonnage/price per tonne", 400

            # Convert tonne to volume using container-specific factor
            tonne_to_m3 = get_tonne_to_m3_for_container(container.container_type)
            new_volume = tonnage_val * tonne_to_m3
            new_price = round(tonnage_val * ppt_val)

            shipment.tonnage = tonnage_val
            shipment.price_per_tonne = ppt_val
            shipment.volume = new_volume
            shipment.price = new_price
            shipment.extra_charge = extra_charge
        else:
            # Check for Car fields (volume_vide/volume_used)
            volume_vide_form = request.form.get('volume_vide')
            volume_used_form = request.form.get('volume_used')

            if volume_vide_form is not None and volume_vide_form != '':
                try:
                    vide_val = float(volume_vide_form)
                    used_val = float(volume_used_form) if volume_used_form not in (None, '') else 0
                except ValueError:
                    return "Please enter valid numeric values for vide/used volumes", 400

                new_volume = max(vide_val - used_val, 0)
                base_price, _ = calculate_client_price(container.price, container.total_volume, new_volume)

                shipment.volume_vide = vide_val
                shipment.volume_used = used_val
                shipment.volume = new_volume
                # Always use the calculated base price; ignore any manual price override.
                shipment.price = base_price
                shipment.extra_charge = extra_charge
            else:
                # Non-metals / legacy flow — update by volume
                try:
                    new_volume = float(request.form.get('volume'))
                except (TypeError, ValueError):
                    return "Please enter a valid numeric volume", 400

                # Use the common price calculation function
                base_price, _ = calculate_client_price(container.price, container.total_volume, new_volume)

                shipment.volume = new_volume
                # Always use the calculated base price; ignore any manual price override.
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
        
        # Check if client should be deleted BEFORE deleting the shipment
        # (count shipments before this one is removed from the relationship)
        should_delete_client = False
        if client:
            # Count how many shipments this client has (excluding the one we're about to delete)
            other_shipments_count = Shipment.query.filter(
                Shipment.client_id == client.id,
                Shipment.id != shipment.id
            ).count()
            should_delete_client = (other_shipments_count == 0)
        
        # Now delete the shipment
        db.session.delete(shipment)
        
        # Delete client if they have no other shipments
        if should_delete_client:
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


@app.route('/employee/<int:id>/update_role', methods=['POST'])
@login_required
@admin_required
def update_employee_role(id):
    try:
        employee = User.query.get_or_404(id)

        # Prevent changing your own role via this route
        if current_user.id == employee.id:
            flash('You cannot change your own role from this page', 'warning')
            return redirect(url_for('employees'))

        new_role = request.form.get('role')
        if new_role not in ('Admin', 'Secretary', 'Manager', 'Employee'):
            flash('Invalid role selected', 'danger')
            return redirect(url_for('employees'))

        employee.role = new_role
        db.session.commit()
        flash(f'Role updated for {employee.username} to {new_role}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating role: {str(e)}', 'danger')

    return redirect(url_for('employees'))

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

@app.route('/finance', methods=['GET', 'POST'])
@login_required
@admin_required
def finance():
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form.get('name', '').strip()
            amount = float(request.form.get('amount', 0) or 0)
            service_charge = float(request.form.get('service_charge', 0) or 0)
            payment_method = request.form.get('payment_method', 'cash')
            notes = request.form.get('notes', '').strip()
            
            if not name:
                flash('Name is required', 'danger')
                return redirect(url_for('finance'))
            
            # Create new finance record (ticket)
            finance_record = FinanceRecord(
                name=name,
                amount=amount,
                service_charge=service_charge,
                payment_method=payment_method,
                notes=notes,
                total_amount=0,  # Will be calculated next
                added_by=current_user.id
            )
            
            # Calculate and set total
            finance_record.total_amount = finance_record.calculate_total()
            
            db.session.add(finance_record)
            db.session.commit()
            
            flash(f'Ticket added successfully for {name}. Total: €{finance_record.total_amount:.2f}', 'success')
            return redirect(url_for('finance'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding ticket: {str(e)}', 'danger')
            return redirect(url_for('finance'))
    
    # GET request with optional date filter
    filter_date = request.args.get('date')
    
    if filter_date:
        try:
            from datetime import datetime as dt
            filter_date_obj = dt.strptime(filter_date, '%Y-%m-%d').date()
            # Filter records for specific date
            records = FinanceRecord.query.filter(
                db.func.date(FinanceRecord.created_at) == filter_date_obj
            ).order_by(FinanceRecord.created_at.desc()).all()
        except:
            records = FinanceRecord.query.order_by(FinanceRecord.created_at.desc()).all()
    else:
        records = FinanceRecord.query.order_by(FinanceRecord.created_at.desc()).all()
    
    # Calculate total sum and count
    total_sum = sum(record.total_amount for record in records)
    total_cash = sum(record.total_amount for record in records if record.payment_method == 'cash')
    ticket_count = len(records)
    
    # Create a dictionary to map user IDs to usernames
    user_dict = {user.id: user.username for user in User.query.all()}
    
    return render_template('finance.html', 
                         records=records, 
                         total_sum=total_sum,
                         total_cash=total_cash,
                         ticket_count=ticket_count, 
                         user_dict=user_dict,
                         filter_date=filter_date)

@app.route('/finance/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_finance_record(id):
    try:
        record = FinanceRecord.query.get_or_404(id)
        db.session.delete(record)
        db.session.commit()
        flash('Finance record deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting record: {str(e)}', 'danger')
    
    return redirect(url_for('finance'))

@app.route('/finance/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_finance_record(id):
    record = FinanceRecord.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form.get('name', '').strip()
            amount = float(request.form.get('amount', 0) or 0)
            service_charge = float(request.form.get('service_charge', 0) or 0)
            payment_method = request.form.get('payment_method', 'cash')
            notes = request.form.get('notes', '').strip()
            
            if not name:
                flash('Name is required', 'danger')
                return redirect(url_for('edit_finance_record', id=id))
            
            # Update the record
            record.name = name
            record.amount = amount
            record.service_charge = service_charge
            record.payment_method = payment_method
            record.notes = notes
            record.total_amount = record.calculate_total()
            
            db.session.commit()
            
            flash(f'Ticket updated successfully for {name}. Total: €{record.total_amount:.2f}', 'success')
            return redirect(url_for('finance'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating ticket: {str(e)}', 'danger')
            return redirect(url_for('edit_finance_record', id=id))
    
    # GET request - show edit form
    return render_template('edit_finance.html', record=record)

@app.route('/finance/delete_multiple', methods=['POST'])
@login_required
@admin_required
def delete_multiple_finance_records():
    try:
        ticket_ids = request.form.getlist('ticket_ids')
        
        if not ticket_ids:
            flash('No tickets selected for deletion.', 'warning')
            return redirect(url_for('finance'))
        
        # Delete all selected tickets
        deleted_count = 0
        for ticket_id in ticket_ids:
            record = FinanceRecord.query.get(ticket_id)
            if record:
                db.session.delete(record)
                deleted_count += 1
        
        db.session.commit()
        flash(f'Successfully deleted {deleted_count} ticket(s).', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting tickets: {str(e)}', 'danger')
    
    return redirect(url_for('finance'))

@app.route('/billetage', methods=['GET', 'POST'])
@login_required
@admin_required
def billetage():
    if request.method == 'POST':
        try:
            # Get form data for bills
            euro_500 = int(request.form.get('euro_500', 0) or 0)
            euro_200 = int(request.form.get('euro_200', 0) or 0)
            euro_100 = int(request.form.get('euro_100', 0) or 0)
            euro_50 = int(request.form.get('euro_50', 0) or 0)
            euro_20 = int(request.form.get('euro_20', 0) or 0)
            euro_10 = int(request.form.get('euro_10', 0) or 0)
            euro_5 = int(request.form.get('euro_5', 0) or 0)
            
            # Get form data for Comores denominations
            kmf_10000 = int(request.form.get('kmf_10000', 0) or 0)
            kmf_5000 = int(request.form.get('kmf_5000', 0) or 0)
            kmf_2000 = int(request.form.get('kmf_2000', 0) or 0)
            kmf_1000 = int(request.form.get('kmf_1000', 0) or 0)
            kmf_500 = int(request.form.get('kmf_500', 0) or 0)
            
            notes = request.form.get('notes', '').strip()
            count_date_str = request.form.get('count_date', '')
            
            # Parse count date
            from datetime import datetime as dt
            if count_date_str:
                count_date = dt.strptime(count_date_str, '%Y-%m-%d').date()
            else:
                count_date = datetime.utcnow().date()
            
            # Create new billetage record
            billetage_record = Billetage(
                count_date=count_date,
                euro_500=euro_500,
                euro_200=euro_200,
                euro_100=euro_100,
                euro_50=euro_50,
                euro_20=euro_20,
                euro_10=euro_10,
                euro_5=euro_5,
                kmf_10000=kmf_10000,
                kmf_5000=kmf_5000,
                kmf_2000=kmf_2000,
                kmf_1000=kmf_1000,
                kmf_500=kmf_500,
                notes=notes,
                total_amount=0,
                counted_by=current_user.id
            )
            
            # Calculate and set total
            billetage_record.total_amount = billetage_record.calculate_total()
            
            db.session.add(billetage_record)
            db.session.commit()
            
            flash(f'Billetage added successfully. Total: €{billetage_record.total_amount:.2f}', 'success')
            return redirect(url_for('billetage'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding billetage: {str(e)}', 'danger')
            return redirect(url_for('billetage'))
    
    # GET request with optional date filter
    filter_date = request.args.get('date')
    
    if filter_date:
        try:
            from datetime import datetime as dt
            filter_date_obj = dt.strptime(filter_date, '%Y-%m-%d').date()
            # Filter billetage for specific date
            billetage_records = Billetage.query.filter(
                Billetage.count_date == filter_date_obj
            ).order_by(Billetage.created_at.desc()).all()
            
            # Get tickets for the same date (cash only)
            tickets = FinanceRecord.query.filter(
                db.func.date(FinanceRecord.created_at) == filter_date_obj,
                FinanceRecord.payment_method == 'cash'
            ).all()
        except:
            billetage_records = Billetage.query.order_by(Billetage.created_at.desc()).all()
            tickets = []
    else:
        billetage_records = Billetage.query.order_by(Billetage.created_at.desc()).all()
        # Get all cash tickets
        tickets = FinanceRecord.query.filter_by(payment_method='cash').all()
    
    # Get total from cash tickets (for the filtered date or all)
    tickets_total = sum(ticket.total_amount for ticket in tickets)
    ticket_count = len(tickets)
    
    # Get total from billetage
    billetage_total = sum(record.total_amount for record in billetage_records)
    
    # Calculate difference
    difference = billetage_total - tickets_total
    
    # Create a dictionary to map user IDs to usernames
    user_dict = {user.id: user.username for user in User.query.all()}
    
    return render_template('billetage.html', 
                         billetage_records=billetage_records,
                         billetage_total=billetage_total,
                         tickets_total=tickets_total,
                         ticket_count=ticket_count,
                         tickets=tickets,
                         difference=difference,
                         user_dict=user_dict,
                         filter_date=filter_date,
                         current_date=datetime.utcnow().date().strftime('%Y-%m-%d'))

@app.route('/billetage/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_billetage(id):
    record = Billetage.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Update form data for bills
            record.euro_500 = int(request.form.get('euro_500', 0) or 0)
            record.euro_200 = int(request.form.get('euro_200', 0) or 0)
            record.euro_100 = int(request.form.get('euro_100', 0) or 0)
            record.euro_50 = int(request.form.get('euro_50', 0) or 0)
            record.euro_20 = int(request.form.get('euro_20', 0) or 0)
            record.euro_10 = int(request.form.get('euro_10', 0) or 0)
            record.euro_5 = int(request.form.get('euro_5', 0) or 0)
            
            # Update form data for Comores denominations
            record.kmf_10000 = int(request.form.get('kmf_10000', 0) or 0)
            record.kmf_5000 = int(request.form.get('kmf_5000', 0) or 0)
            record.kmf_2000 = int(request.form.get('kmf_2000', 0) or 0)
            record.kmf_1000 = int(request.form.get('kmf_1000', 0) or 0)
            record.kmf_500 = int(request.form.get('kmf_500', 0) or 0)
            
            record.notes = request.form.get('notes', '').strip()
            count_date_str = request.form.get('count_date', '')
            
            # Parse count date
            from datetime import datetime as dt
            if count_date_str:
                record.count_date = dt.strptime(count_date_str, '%Y-%m-%d').date()
            
            # Recalculate and update total
            record.total_amount = record.calculate_total()
            
            db.session.commit()
            
            flash(f'Billetage updated successfully. Total: €{record.total_amount:.2f}', 'success')
            return redirect(url_for('billetage'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating billetage: {str(e)}', 'danger')
            return redirect(url_for('billetage'))
    
    # GET request - just redirect to main page with edit modal
    return redirect(url_for('billetage'))

@app.route('/billetage/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_billetage(id):
    try:
        record = Billetage.query.get_or_404(id)
        db.session.delete(record)
        db.session.commit()
        flash('Billetage deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting billetage: {str(e)}', 'danger')
    
    return redirect(url_for('billetage'))

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

        # New: support goods_type for products (Merchandise/Car/Metals)
        goods_type = request.form.get('goods_type', 'Merchandise')

        # For Metals, dimensions and quantity are not required. Parse fields depending on goods type.
        if goods_type == 'Metals':
            # Use safe defaults for dimensions/quantity for metals
            quantity = int(request.form.get('quantity') or 1)
            length = float(request.form.get('length') or 0)
            width = float(request.form.get('width') or 0)
            height = float(request.form.get('height') or 0)
            # We'll compute volume from tonnage below
            volume = 0

        else:
            # For Merchandise and Car, dimensions and quantity are required (validate)
            try:
                quantity = int(request.form.get('quantity'))
                length = float(request.form.get('length'))
                width = float(request.form.get('width'))
                height = float(request.form.get('height'))
            except (TypeError, ValueError):
                return "Please enter valid numeric values for quantity and dimensions", 400

            # Default computed volume (merchandise)
            volume = length * width * height * quantity

        # Handle special goods types
        if goods_type == 'Car':
            try:
                volume_vide = float(request.form.get('volume_vide', '') or 0)
                volume_used = float(request.form.get('volume_used', '') or 0)
            except ValueError:
                return "Please enter valid numeric values for car volumes", 400
            volume = max(volume_vide - volume_used, 0)

            product = Product(
                client_id=id,
                reference=reference,
                quantity=quantity,
                length=length,
                width=width,
                height=height,
                volume=volume,
                goods_type='Car',
                volume_vide=volume_vide,
                volume_used=volume_used
            )

        elif goods_type == 'Metals':
            try:
                tonnage = float(request.form.get('tonnage', '') or 0)
            except ValueError:
                return "Please enter a valid tonnage value", 400

            # For Metals we treat the entered tonnage as the 'quantity' reported to the user
            # but keep the precise tonnage in product.tonnage. Compute volume from tonnage only.
            quantity_from_tonnage = int(round(tonnage)) if tonnage else 0
            # For Products of type Metals, volume must be 0.0 and immutable
            volume = 0.0

            product = Product(
                client_id=id,
                reference=reference,
                quantity=quantity_from_tonnage or 1,
                length=length,
                width=width,
                height=height,
                volume=volume,
                goods_type='Metals',
                tonnage=tonnage
            )

        else:
            # Merchandise / default
            product = Product(
                client_id=id,
                reference=reference,
                quantity=quantity,
                length=length,
                width=width,
                height=height,
                volume=volume,
                goods_type='Merchandise'
            )

        db.session.add(product)
        db.session.commit()

        # Preserve container_id in redirect if it was provided
        container_id = request.form.get('container_id', type=int)
        if container_id:
            return redirect(url_for('client_products', id=id, container_id=container_id))
        else:
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
        # Update reference
        # Only update dimensions/quantity for non-Metals products (Metals don't need these fields)

        # Enforce goods_type immutability: do not allow changing goods type once set on the product.
        posted_goods_type = request.form.get('goods_type')
        if product.goods_type:
            # Keep existing goods_type
            goods_type = product.goods_type
        else:
            # If not set (legacy rows), allow setting once via the edit form
            goods_type = posted_goods_type or 'Merchandise'
            product.goods_type = goods_type

        if goods_type != 'Metals':
            try:
                product.quantity = int(request.form.get('quantity'))
                product.length = float(request.form.get('length'))
                product.width = float(request.form.get('width'))
                product.height = float(request.form.get('height'))
            except (TypeError, ValueError):
                return "Please enter valid numeric values for quantity and dimensions", 400

        if goods_type == 'Car':
            try:
                volume_vide = float(request.form.get('volume_vide', '') or 0)
                volume_used = float(request.form.get('volume_used', '') or 0)
            except ValueError:
                return "Please enter valid numeric values for car volumes", 400

            new_volume = max(volume_vide - volume_used, 0)
            product.volume_vide = volume_vide
            product.volume_used = volume_used
            product.volume = new_volume

        elif goods_type == 'Metals':
            try:
                tonnage = float(request.form.get('tonnage', '') or 0)
            except ValueError:
                return "Please enter a valid tonnage value", 400

            # Treat tonnage as the reported quantity (rounded) but keep precise tonnage
            product.tonnage = tonnage
            product.quantity = int(round(tonnage)) if tonnage else product.quantity
            # For Metals, volume is fixed to 0.0 and cannot be changed
            product.volume = 0.0

        else:
            # Merchandise / default: recalc from dimensions
            product.volume = product.length * product.width * product.height * product.quantity

        db.session.commit()
        
        # Preserve container_id in redirect if it was provided
        container_id = request.form.get('container_id', type=int)
        if container_id:
            return redirect(url_for('client_products', id=product.client_id, container_id=container_id))
        else:
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
        
        # Preserve container_id in redirect if it was provided
        container_id = request.form.get('container_id', type=int)
        if container_id:
            return redirect(url_for('client_products', id=client_id, container_id=container_id))
        else:
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
    
    # Preserve container_id in redirect if it was provided
    container_id = request.form.get('container_id', type=int)
    if container_id:
        return redirect(url_for('client_products', id=client_id, container_id=container_id))
    else:
        return redirect(url_for('client_products', id=client_id))

@app.route('/download-template')
@login_required
def download_template():
    output = io.BytesIO()
    df = pd.DataFrame({
        'Client Mark': ['MARK001', 'MARK002'],
        'Client Name': ['Example Name 1', 'Example Name 2'],
        'Phone': ['1234567890', '0987654321'],  # Plain string format
        'Goods Type': ['Merchandise', 'Metals'],
        'Volume': [10.5, ''],
        'Volume Used': ['', ''],
        'Tonnage': ['', 2.5],
        'Price / Tonne': ['', 120.0]
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

@app.route('/download-csv-template')
@login_required
def download_csv_template():
    output = io.StringIO()
    df = pd.DataFrame({
        'Client Mark': ['MARK001', 'MARK002'],
        'Client Name': ['Example Name 1', 'Example Name 2'],
        'Phone': ['1234567890', '0987654321'],
        'Goods Type': ['Merchandise', 'Metals'],
        'Volume': [10.5, ''],
        'Volume Used': ['', ''],
        'Tonnage': ['', 2.5],
        'Price / Tonne': ['', 120.0]
    })
    df.to_csv(output, index=False)
    output.seek(0)
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='clients_template.csv'
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
        
        # Get file extension
        file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        # Process based on file type
        if file_extension in ['xlsx', 'xls']:
            # Read Excel file with phone column as string
            df = pd.read_excel(file, dtype={'Phone': str})
            
        elif file_extension == 'csv':
            # Read CSV file with phone column as string
            df = pd.read_csv(file, dtype={'Phone': str})
            
        else:
            flash('Unsupported file format. Please upload Excel (.xlsx, .xls) or CSV (.csv) files.')
            return redirect(url_for('container_details', id=id))
        
        if df is None or df.empty:
            flash('No data found in the uploaded file')
            return redirect(url_for('container_details', id=id))

        # Process each row
        for _, row in df.iterrows():
            # Create client
            client = Client(
                name=str(row.get('Client Name', '')).strip(),
                mark=str(row.get('Client Mark', '')).strip(),
                phone=str(row.get('Phone', '')).split('.')[0] if pd.notna(row.get('Phone', '')) else '',  # Remove decimal part
            )
            db.session.add(client)

            # Determine goods type and compute client_volume accordingly
            goods_type = str(row.get('Goods Type')).strip() if 'Goods Type' in df.columns and pd.notna(row.get('Goods Type')) else 'Merchandise'

            client_volume = 0.0
            tonnage = None
            volume_vide = None
            volume_used = None

            if goods_type.lower() == 'metals':
                try:
                    tonnage = float(row.get('Tonnage')) if 'Tonnage' in df.columns and pd.notna(row.get('Tonnage')) else 0
                except (ValueError, TypeError):
                    tonnage = 0
                # Convert tonne to m3 using container-specific factor
                tonne_to_m3 = get_tonne_to_m3_for_container(container.container_type)
                client_volume = tonnage * tonne_to_m3

            elif goods_type.lower() == 'car':
                try:
                    # Prefer Volume column to represent Volume Vide (if provided)
                    volume_vide = float(row.get('Volume')) if 'Volume' in df.columns and pd.notna(row.get('Volume')) else 0
                except (ValueError, TypeError):
                    volume_vide = 0
                try:
                    volume_used = float(row.get('Volume Used')) if 'Volume Used' in df.columns and pd.notna(row.get('Volume Used')) else 0
                except (ValueError, TypeError):
                    volume_used = 0
                client_volume = max((volume_vide or 0) - (volume_used or 0), 0)

            else:
                # Merchandise or fallback: use Volume column
                try:
                    client_volume = float(row.get('Volume')) if 'Volume' in df.columns and pd.notna(row.get('Volume')) else 0
                except (ValueError, TypeError):
                    client_volume = 0

            # Use the common price calculation function as a fallback
            base_price, _ = calculate_client_price(container.price, container.total_volume, client_volume)

            # Allow Metals to supply a Price / Tonne column to calculate price directly
            price = base_price
            price_per_tonne_val = None
            if goods_type.lower() == 'metals':
                try:
                    # Accept either 'Price / Tonne' or 'Price_per_tonne' column names
                    if 'Price / Tonne' in df.columns and pd.notna(row.get('Price / Tonne')):
                        price_per_tonne_val = float(row.get('Price / Tonne'))
                    elif 'Price_per_tonne' in df.columns and pd.notna(row.get('Price_per_tonne')):
                        price_per_tonne_val = float(row.get('Price_per_tonne'))
                except (ValueError, TypeError):
                    price_per_tonne_val = None

                # If a price per tonne was provided, use it to compute the shipment price
                if price_per_tonne_val is not None:
                    try:
                        price = round((tonnage or 0) * float(price_per_tonne_val))
                    except Exception:
                        price = base_price
                else:
                    price = base_price

            # Create shipment kwargs and include goods-specific metadata
            shipment_kwargs = dict(
                client=client,
                container=container,
                volume=client_volume,
                price=price,
                payment_status='unpaid'
            )

            if goods_type.lower() == 'metals':
                shipment_kwargs['tonnage'] = tonnage
                if price_per_tonne_val is not None:
                    shipment_kwargs['price_per_tonne'] = price_per_tonne_val
            elif goods_type.lower() == 'car':
                shipment_kwargs['volume_vide'] = volume_vide
                shipment_kwargs['volume_used'] = volume_used

            shipment = Shipment(**shipment_kwargs)
            db.session.add(shipment)
        
        db.session.commit()
        flash(f'Successfully imported {len(df)} clients')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing file: {str(e)}')
    
    return redirect(url_for('container_details', id=id))

@app.route('/download-products-template')
@app.route('/download-products-template/<int:client_id>')
@login_required
def download_products_template(client_id=None):
    output = io.BytesIO()
    df = pd.DataFrame({
        'Reference': ['REF001', 'REF002'],
        'Quantity': [5, 10],
        'Length (m)': [1.5, 2.0],
        'Width (m)': [0.8, 1.0],
        'Height (m)': [0.5, 0.7],
        'Goods Type': ['Merchandise', 'Car'],
        'Volume Used': ['', '']
    })
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    
    output.seek(0)
    
    # Determine the filename based on client_id
    if client_id:
        client = db.session.get(Client, client_id)
        if client:
            download_name = f"{client.mark}_products_template.xlsx"
        else:
            download_name = 'products_template.xlsx'
    else:
        download_name = 'products_template.xlsx'
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=download_name
    )

@app.route('/download-products-csv-template')
@app.route('/download-products-csv-template/<int:client_id>')
@login_required
def download_products_csv_template(client_id=None):
    output = io.StringIO()
    df = pd.DataFrame({
        'Reference': ['REF001', 'REF002'],
        'Quantity': [5, 10],
        'Length (m)': [1.5, 2.0],
        'Width (m)': [0.8, 1.0],
        'Height (m)': [0.5, 0.7],
        'Goods Type': ['Merchandise', 'Car'],
        'Volume Used': ['', '']
    })
    df.to_csv(output, index=False)
    output.seek(0)
    
    # Determine the filename based on client_id
    if client_id:
        client = db.session.get(Client, client_id)
        if client:
            download_name = f"{client.mark}_products_template.csv"
        else:
            download_name = 'products_template.csv'
    else:
        download_name = 'products_template.csv'
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=download_name
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
        
        # Get file extension
        file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        # Process based on file type
        if file_extension in ['xlsx', 'xls']:
            # Read Excel file
            df = pd.read_excel(file)
        elif file_extension == 'csv':
            # Read CSV file
            df = pd.read_csv(file)
        else:
            flash('Unsupported file format. Please upload Excel (.xlsx, .xls) or CSV (.csv) files.')
            return redirect(url_for('client_products', id=id))
        
        # Define column mappings (English -> Application fields)
        column_mappings = {
            # English columns
            'Reference': 'Reference',
            'Quantity': 'Quantity',
            'Length': 'Length',
            'Length (m)': 'Length',
            'Width': 'Width',
            'Width (m)': 'Width',
            'Height': 'Height',
            'Height (m)': 'Height',
            'Goods Type': 'Goods Type',
            'Tonnage': 'Tonnage',
            'Tonnage (t)': 'Tonnage',
            'Price / Tonne': 'Price / Tonne',
            'Price_per_tonne': 'Price / Tonne',
            'Volume Vide': 'Volume Vide',
            'Volume Used': 'Volume Used',
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

            reference = str(row.get('Reference', '')).strip()

            # Determine goods type (default to Merchandise)
            goods_type = str(row.get('Goods Type')).strip() if 'Goods Type' in df.columns and pd.notna(row.get('Goods Type')) else 'Merchandise'

            # Read common fields with safe defaults
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

            # Goods-specific parsing and volume calculation
            volume = 0
            tonnage = None
            price_per_tonne = None
            volume_vide = None
            volume_used = None

            if goods_type.lower() == 'metals':
                try:
                    tonnage = float(row.get('Tonnage')) if 'Tonnage' in df.columns and pd.notna(row.get('Tonnage')) else 0
                except (ValueError, TypeError):
                    tonnage = 0
                # For uploaded Metals rows, volume must be 0.0 regardless of tonnage or dimensions
                quantity_from_tonnage = int(round(tonnage)) if tonnage and tonnage > 0 else quantity

                product = Product(
                    client_id=id,
                    reference=reference,
                    quantity=quantity_from_tonnage or 1,
                    length=length,
                    width=width,
                    height=height,
                    volume=0.0,
                    goods_type='Metals',
                    tonnage=tonnage
                )

            elif goods_type.lower() == 'car':
                # Prefer explicit Volume Vide/Used if provided
                try:
                    volume_vide = float(row.get('Volume Vide')) if 'Volume Vide' in df.columns and pd.notna(row.get('Volume Vide')) else None
                except (ValueError, TypeError):
                    volume_vide = None
                try:
                    volume_used = float(row.get('Volume Used')) if 'Volume Used' in df.columns and pd.notna(row.get('Volume Used')) else None
                except (ValueError, TypeError):
                    volume_used = None

                # If Volume Vide provided, use it. Otherwise compute from dimensions when possible
                if volume_vide is not None:
                    computed_vide = float(volume_vide or 0)
                elif length > 0 and width > 0 and height > 0:
                    computed_vide = length * width * height * quantity
                else:
                    # Fallback to Volume column if present
                    try:
                        computed_vide = float(row.get('Volume')) if pd.notna(row.get('Volume')) else 0
                    except (ValueError, TypeError):
                        computed_vide = 0

                # Ensure we persist volume_vide (either provided or computed)
                volume_vide = computed_vide
                volume_used = volume_used or 0
                volume = max(volume_vide - volume_used, 0)

                product = Product(
                    client_id=id,
                    reference=reference,
                    quantity=quantity,
                    length=length,
                    width=width,
                    height=height,
                    volume=volume,
                    goods_type='Car',
                    volume_vide=volume_vide,
                    volume_used=volume_used
                )

            else:
                # Merchandise or default: prefer dimensions, otherwise Volume column
                if length > 0 and width > 0 and height > 0:
                    volume = length * width * height * quantity
                else:
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
                    volume=volume,
                    goods_type='Merchandise'
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
        Shipment.paid_amount,
        Shipment.id.label('shipment_id')
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
            'payment_status': result.payment_status,
            'shipment_id': result.shipment_id
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


@app.route('/api/shipment-products/<int:shipment_id>')
@login_required
def get_shipment_products(shipment_id):
    """Return JSON with products for the client related to a shipment and per-product price allocation.

    Allocation rules:
    - For Metals: allocate shipment.price proportionally by product.tonnage
    - For other goods: allocate shipment.price proportionally by product.volume
    Falls back gracefully if totals are zero.
    """
    try:
        shipment = Shipment.query.get_or_404(shipment_id)
        client_id = shipment.client_id
        container = shipment.container

        # Get products for this client (all products)
        products = Product.query.filter_by(client_id=client_id).all()

        # Compute totals for allocation
        total_tonnage = sum((p.tonnage or 0) for p in products if p.goods_type == 'Metals')
        total_volume = sum((p.volume or 0) for p in products if p.goods_type != 'Metals')

        product_list = []
        for p in products:
            p_tonnage = float(p.tonnage or 0)
            p_volume = float(p.volume or 0)

            # Determine allocation
            allocated_price = 0.0
            if p.goods_type == 'Metals':
                if total_tonnage > 0:
                    allocated_price = (p_tonnage / total_tonnage) * float(shipment.price or 0)
                else:
                    allocated_price = 0.0
            else:
                if total_volume > 0:
                    allocated_price = (p_volume / total_volume) * float(shipment.price or 0)
                else:
                    allocated_price = 0.0

            product_list.append({
                'id': p.id,
                'reference': p.reference,
                'goods_type': p.goods_type,
                'quantity': p.quantity,
                'length': p.length,
                'width': p.width,
                'height': p.height,
                'volume_vide': p.volume_vide,
                'volume_used': p.volume_used,
                'volume': p.volume,
                'tonnage': p.tonnage,
                'allocated_price': round(allocated_price, 2)
            })

        response = {
            'shipment_id': shipment.id,
            'client_id': client_id,
            'client_mark': shipment.client.mark,
            'client_name': shipment.client.name,
            'container_number': container.container_number if container else None,
            'shipment_price': float(shipment.price or 0),
            'extra_charge': float(shipment.extra_charge or 0),
            'paid_amount': float(shipment.paid_amount or 0),
            'payment_status': shipment.payment_status,
            'shipment_volume': float(shipment.volume or 0),
            'products': product_list
        }

        return jsonify(response)
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

@app.route('/unpaid-deliveries')
@login_required
def unpaid_deliveries():
    """Page to view all delivered containers with unpaid or partially paid freight fees"""
    
    # Get filters from query parameters
    search_query = request.args.get('search', '').strip()
    payment_filter = request.args.get('payment_status', '')
    destination_filter = request.args.get('destination', '')
    
    # Base query to get delivered containers with unpaid or partially paid shipments
    query = db.session.query(Container).filter(
        Container.status == 'delivered'
    ).distinct()
    
    # Join with shipments to find containers with unpaid/partial shipments
    containers_with_unpaid = db.session.query(
        Container.id
    ).join(
        Shipment, Container.id == Shipment.container_id
    ).filter(
        Container.status == 'delivered',
        Shipment.payment_status.in_(['unpaid', 'partial'])
    ).distinct()
    
    # Filter containers that have at least one unpaid/partial shipment
    query = query.filter(Container.id.in_(containers_with_unpaid))
    
    # Apply additional filters if provided
    if search_query:
        query = query.filter(
            db.or_(
                Container.container_number.ilike(f'%{search_query}%'),
                Container.container_name.ilike(f'%{search_query}%')
            )
        )
    
    if destination_filter:
        query = query.filter(Container.destination == destination_filter)
    
    # Get all results ordered by ID descending
    containers = query.order_by(Container.id.desc()).all()
    
    # Enrich containers with shipment and payment data
    enriched_containers = []
    
    for container in containers:
        # Get all shipments for this container
        shipments = Shipment.query.filter_by(container_id=container.id).all()
        
        # Filter shipments with unpaid or partial payments
        unpaid_shipments = [s for s in shipments if s.payment_status in ['unpaid', 'partial']]
        
        # Calculate totals for unpaid shipments
        total_unpaid_amount = 0
        shipment_details = []
        
        for shipment in unpaid_shipments:
            total_price = shipment.price + shipment.extra_charge
            paid = shipment.paid_amount or 0
            outstanding = total_price - paid
            
            if outstanding > 0:
                total_unpaid_amount += outstanding
                
                shipment_details.append({
                    'id': shipment.id,
                    'client': shipment.client,
                    'volume': shipment.volume,
                    'price': shipment.price,
                    'extra_charge': shipment.extra_charge,
                    'total_price': total_price,
                    'paid_amount': paid,
                    'outstanding': outstanding,
                    'payment_status': shipment.payment_status
                })
        
        # Only include container if it has unpaid shipments
        if shipment_details:
            enriched_containers.append({
                'container': container,
                'shipment_count': len(shipment_details),
                'total_unpaid': total_unpaid_amount,
                'shipments': shipment_details
            })
    
    # Apply payment filter if specified
    if payment_filter:
        enriched_containers = [
            ec for ec in enriched_containers 
            if any(s['payment_status'] == payment_filter for s in ec['shipments'])
        ]
    
    # Calculate total statistics
    total_containers = len(enriched_containers)
    total_outstanding = sum(ec['total_unpaid'] for ec in enriched_containers)
    unpaid_count = sum(1 for ec in enriched_containers if any(s['payment_status'] == 'unpaid' for s in ec['shipments']))
    partial_count = sum(1 for ec in enriched_containers if any(s['payment_status'] == 'partial' for s in ec['shipments']))
    
    # Get all destinations for filter dropdown
    destinations = db.session.query(Container.destination).filter(
        Container.status == 'delivered'
    ).distinct().order_by(Container.destination).all()
    destinations = [d[0] for d in destinations]
    
    return render_template(
        'unpaid_deliveries.html',
        enriched_containers=enriched_containers,
        search_query=search_query,
        payment_filter=payment_filter,
        destination_filter=destination_filter,
        destinations=destinations,
        total_containers=total_containers,
        total_outstanding=total_outstanding,
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
    
    # Check for missing phone filter
    missing_phone_param = request.args.get('missing_phone', 'false')
    missing_phone = missing_phone_param.lower() == 'true'
    
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
        
        # Apply missing phone filter
        if missing_phone:
            subq = subq.filter(
                db.or_(
                    Client.phone == None,
                    Client.phone == '',
                    Client.phone == '+'
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
        
        # Apply missing phone filter
        if missing_phone:
            client_query = client_query.filter(
                db.or_(
                    Client.phone == None,
                    Client.phone == '',
                    Client.phone == '+'
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
        missing_phone=missing_phone,
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

# Courier Routes
@app.route('/couriers')
@login_required
def couriers():
    """List all couriers"""
    all_couriers = Courier.query.order_by(Courier.created_at.desc()).all()
    
    # Separate couriers into new (unapproved) and approved
    new_couriers = []
    approved_couriers = []
    
    for courier in all_couriers:
        # Check if courier has at least one approved item
        approved_items = CourierItem.query.filter_by(courier_id=courier.id, is_received=True).first()
        if approved_items:
            approved_couriers.append(courier)
        else:
            new_couriers.append(courier)
    
    # Filter new couriers based on role visibility
    # Secretary and Manager only see new couriers with contact info (name or phone)
    if current_user.role in ['Secretary', 'Manager']:
        new_couriers = [c for c in new_couriers if c.brought_by_name or c.brought_by_phone]
    
    return render_template('couriers.html', couriers=new_couriers, approved_couriers=approved_couriers)

@app.route('/courier/create', methods=['POST'])
@login_required
def create_courier():
    """Create a new courier"""
    try:
        # Auto-generate courier_id
        # Find the highest existing courier_id number
        existing_couriers = Courier.query.all()
        max_id = 0
        for courier in existing_couriers:
            try:
                # Extract number from courier_id (remove leading zeros and convert to int)
                courier_num = int(courier.courier_id.lstrip('0'))
                if courier_num > max_id:
                    max_id = courier_num
            except ValueError:
                # Skip if courier_id is not a number
                continue
        
        # Generate next courier_id with leading zeros (001, 002, etc.)
        next_id = max_id + 1
        courier_id = f"{next_id:03d}"
        
        date_str = request.form.get('date')
        # Additional fields
        brought_by_name = request.form.get('brought_by_name')
        brought_by_phone = request.form.get('brought_by_phone')
        assigned_to = request.form.get('assigned_to')

        from datetime import datetime
        date = datetime.strptime(date_str, '%Y-%m-%d').date()

        new_courier = Courier(
            courier_id=courier_id,
            date=date,
            brought_by_name=brought_by_name,
            brought_by_phone=brought_by_phone,
            assigned_to=assigned_to
        )

        # Handle optional photo upload
        photo = request.files.get('photo')
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            data = photo.read()
            new_courier.photo_filename = filename
            new_courier.photo_data = data
            new_courier.photo_mime = photo.mimetype
        
        db.session.add(new_courier)
        db.session.commit()
        
        flash(f'Courier {courier_id} created successfully', 'success')
        return redirect(url_for('courier_details', id=new_courier.id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating courier: {str(e)}', 'danger')
        return redirect(url_for('couriers'))

@app.route('/courier/next-id', methods=['GET'])
@login_required
def get_next_courier_id():
    """Get the next auto-generated courier ID"""
    try:
        # Find the highest existing courier_id number
        existing_couriers = Courier.query.all()
        max_id = 0
        for courier in existing_couriers:
            try:
                # Extract number from courier_id (remove leading zeros and convert to int)
                courier_num = int(courier.courier_id.lstrip('0'))
                if courier_num > max_id:
                    max_id = courier_num
            except ValueError:
                # Skip if courier_id is not a number
                continue
        
        # Generate next courier_id with leading zeros (001, 002, etc.)
        next_id = max_id + 1
        courier_id = f"{next_id:03d}"
        
        return jsonify({'success': True, 'courier_id': courier_id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/courier/<int:id>')
@login_required
def courier_details(id):
    """View courier details and items"""
    courier = Courier.query.get_or_404(id)
    items = CourierItem.query.filter_by(courier_id=id).order_by(CourierItem.id).all()
    
    # Get active containers for dropdown
    active_containers = Container.query.filter_by(status='active').order_by(Container.container_number).all()
    
    # Create a mapping of container_number to container for easy lookup
    containers_map = {c.container_number: c for c in Container.query.all()}
    
    # Get clients/marks for each container
    container_clients = {}
    for container in active_containers:
        # Get unique client marks in this container
        clients = db.session.query(Client.mark, Client.name).join(
            Shipment, Client.id == Shipment.client_id
        ).filter(
            Shipment.container_id == container.id
        ).distinct().order_by(Client.mark).all()
        container_clients[container.container_number] = clients
    
    # Calculate totals
    total_amount = sum(item.amount for item in items)
    total_service = sum(item.service for item in items)
    total_euro = sum(item.money_in_euro for item in items)
    total_aed = sum(item.money_in_aed for item in items)
    
    # Calculate total money received (only for approved items)
    total_money_received = sum(
        item.money_received for item in items 
        if item.is_received and item.money_received is not None
    )
    
    # Calculate benefit (only if items are approved)
    benefit = total_money_received - total_aed if total_money_received > 0 else 0
    
    # Prepare photo data URI if available
    courier_photo_url = None
    try:
        if courier.photo_data:
            courier_photo_url = f"data:{courier.photo_mime};base64,{base64.b64encode(courier.photo_data).decode()}"
    except Exception:
        courier_photo_url = None
    
    # Get billetage records for this courier
    courier_billetages = CourierBilletage.query.filter_by(courier_id=id).order_by(CourierBilletage.created_at.desc()).all()

    return render_template('courier_details.html', 
                         courier=courier, 
                         items=items,
                         active_containers=active_containers,
                         containers_map=containers_map,
                         container_clients=container_clients,
                         total_amount=total_amount,
                         total_service=total_service,
                         total_euro=total_euro,
                         total_aed=total_aed,
                         total_money_received=total_money_received,
                         benefit=benefit,
                         courier_photo_url=courier_photo_url,
                         courier_billetages=courier_billetages)


@app.route('/courier/<int:courier_id>/billetage', methods=['POST'])
@login_required
def add_courier_billetage(courier_id):
    """Add cash counting (billetage) for a courier"""
    try:
        courier = Courier.query.get_or_404(courier_id)
        
        # Check if courier has items
        items = CourierItem.query.filter_by(courier_id=courier_id).all()
        
        if not items:
            flash('Cannot add billetage to courier without items', 'danger')
            return redirect(url_for('courier_details', id=courier_id))
        
        # Get form data for AED denominations
        aed_1000 = int(request.form.get('aed_1000', 0) or 0)
        aed_500 = int(request.form.get('aed_500', 0) or 0)
        aed_200 = int(request.form.get('aed_200', 0) or 0)
        aed_100 = int(request.form.get('aed_100', 0) or 0)
        aed_50 = int(request.form.get('aed_50', 0) or 0)
        aed_20 = int(request.form.get('aed_20', 0) or 0)
        aed_10 = int(request.form.get('aed_10', 0) or 0)
        aed_5 = int(request.form.get('aed_5', 0) or 0)
        
        # Get form data for Euro denominations
        euro_500 = int(request.form.get('euro_500', 0) or 0)
        euro_200 = int(request.form.get('euro_200', 0) or 0)
        euro_100 = int(request.form.get('euro_100', 0) or 0)
        euro_50 = int(request.form.get('euro_50', 0) or 0)
        euro_20 = int(request.form.get('euro_20', 0) or 0)
        euro_10 = int(request.form.get('euro_10', 0) or 0)
        euro_5 = int(request.form.get('euro_5', 0) or 0)
        
        # Get exchange rate
        euro_to_aed_rate = float(request.form.get('euro_to_aed_rate', 4.0))
        
        # Get notes
        notes = request.form.get('notes', '').strip()
        
        # Calculate totals
        total_aed = (aed_1000 * 1000 + aed_500 * 500 + aed_200 * 200 + 
                     aed_100 * 100 + aed_50 * 50 + aed_20 * 20 + 
                     aed_10 * 10 + aed_5 * 5)
        
        total_euro = (euro_500 * 500 + euro_200 * 200 + euro_100 * 100 + 
                      euro_50 * 50 + euro_20 * 20 + euro_10 * 10 + euro_5 * 5)
        
        total_euro_in_aed = total_euro * euro_to_aed_rate
        total_counted = total_aed + total_euro_in_aed
        
        # Calculate expected amount from courier items (based on exchange rate, not market rate)
        items = CourierItem.query.filter_by(courier_id=courier_id).all()
        expected_amount = sum(item.money_in_aed for item in items)
        
        # Calculate difference
        difference = total_counted - expected_amount
        
        # Create billetage record
        billetage = CourierBilletage(
            courier_id=courier_id,
            aed_1000=aed_1000,
            aed_500=aed_500,
            aed_200=aed_200,
            aed_100=aed_100,
            aed_50=aed_50,
            aed_20=aed_20,
            aed_10=aed_10,
            aed_5=aed_5,
            euro_500=euro_500,
            euro_200=euro_200,
            euro_100=euro_100,
            euro_50=euro_50,
            euro_20=euro_20,
            euro_10=euro_10,
            euro_5=euro_5,
            euro_to_aed_rate=euro_to_aed_rate,
            total_aed=total_aed,
            total_euro_in_aed=total_euro_in_aed,
            total_counted=total_counted,
            expected_amount=expected_amount,
            difference=difference,
            notes=notes,
            counted_by=current_user.id
        )
        
        db.session.add(billetage)
        db.session.commit()
        
        # Prepare flash message based on difference
        if difference == 0:
            flash(f'Cash count saved successfully! ✓ Balanced: {total_counted:,.0f} AED', 'success')
        elif difference > 0:
            flash(f'Cash count saved! Surplus of {difference:,.0f} AED (Total: {total_counted:,.0f} AED)', 'warning')
        else:
            flash(f'Cash count saved! Shortage of {abs(difference):,.0f} AED (Total: {total_counted:,.0f} AED)', 'danger')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error saving cash count: {str(e)}', 'danger')
    
    return redirect(url_for('courier_details', id=courier_id))


@app.route('/courier/billetage/<int:billetage_id>/edit', methods=['POST'])
@login_required
def edit_courier_billetage(billetage_id):
    """Edit an existing courier billetage"""
    try:
        billetage = CourierBilletage.query.get_or_404(billetage_id)
        
        # Get form data for AED denominations
        billetage.aed_1000 = int(request.form.get('aed_1000', 0) or 0)
        billetage.aed_500 = int(request.form.get('aed_500', 0) or 0)
        billetage.aed_200 = int(request.form.get('aed_200', 0) or 0)
        billetage.aed_100 = int(request.form.get('aed_100', 0) or 0)
        billetage.aed_50 = int(request.form.get('aed_50', 0) or 0)
        billetage.aed_20 = int(request.form.get('aed_20', 0) or 0)
        billetage.aed_10 = int(request.form.get('aed_10', 0) or 0)
        billetage.aed_5 = int(request.form.get('aed_5', 0) or 0)
        
        # Get form data for Euro denominations
        billetage.euro_500 = int(request.form.get('euro_500', 0) or 0)
        billetage.euro_200 = int(request.form.get('euro_200', 0) or 0)
        billetage.euro_100 = int(request.form.get('euro_100', 0) or 0)
        billetage.euro_50 = int(request.form.get('euro_50', 0) or 0)
        billetage.euro_20 = int(request.form.get('euro_20', 0) or 0)
        billetage.euro_10 = int(request.form.get('euro_10', 0) or 0)
        billetage.euro_5 = int(request.form.get('euro_5', 0) or 0)
        
        # Get exchange rate and notes
        billetage.euro_to_aed_rate = float(request.form.get('euro_to_aed_rate', 4.0))
        billetage.notes = request.form.get('notes', '').strip()
        
        # Recalculate totals
        billetage.total_aed = (billetage.aed_1000 * 1000 + billetage.aed_500 * 500 + 
                               billetage.aed_200 * 200 + billetage.aed_100 * 100 + 
                               billetage.aed_50 * 50 + billetage.aed_20 * 20 + 
                               billetage.aed_10 * 10 + billetage.aed_5 * 5)
        
        total_euro = (billetage.euro_500 * 500 + billetage.euro_200 * 200 + 
                      billetage.euro_100 * 100 + billetage.euro_50 * 50 + 
                      billetage.euro_20 * 20 + billetage.euro_10 * 10 + 
                      billetage.euro_5 * 5)
        
        billetage.total_euro_in_aed = total_euro * billetage.euro_to_aed_rate
        billetage.total_counted = billetage.total_aed + billetage.total_euro_in_aed
        billetage.difference = billetage.total_counted - billetage.expected_amount
        
        db.session.commit()
        
        flash('Cash count updated successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating cash count: {str(e)}', 'danger')
    
    return redirect(url_for('courier_details', id=billetage.courier_id))


@app.route('/courier/billetage/<int:billetage_id>/delete', methods=['POST'])
@login_required
def delete_courier_billetage(billetage_id):
    """Delete a courier billetage"""
    try:
        billetage = CourierBilletage.query.get_or_404(billetage_id)
        courier_id = billetage.courier_id
        
        db.session.delete(billetage)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Cash count deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/courier/<int:id>/edit', methods=['POST'])
@login_required
def edit_courier(id):
    """Update courier information (brought_by, phone, assigned_to, photo)"""
    courier = Courier.query.get_or_404(id)

    brought_by_name = request.form.get('brought_by_name') or None
    brought_by_phone = request.form.get('brought_by_phone') or None
    assigned_to = request.form.get('assigned_to') or None

    courier.brought_by_name = brought_by_name
    courier.brought_by_phone = brought_by_phone
    courier.assigned_to = assigned_to

    # Handle optional photo replacement
    photo = request.files.get('photo')
    if photo and photo.filename:
        filename = secure_filename(photo.filename)
        try:
            data = photo.read()
            courier.photo_filename = filename
            courier.photo_data = data
            courier.photo_mime = photo.mimetype
        except Exception:
            pass

    try:
        db.session.commit()
        flash('Courier information updated successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating courier: {str(e)}', 'danger')

    return redirect(url_for('courier_details', id=id))

@app.route('/courier/<int:id>/add-item', methods=['POST'])
@login_required
def add_courier_item(id):
    """Add an item to a courier"""
    try:
        courier = Courier.query.get_or_404(id)
        
        # Check if courier has any approved items
        approved_item = CourierItem.query.filter_by(
            courier_id=courier.id,
            is_received=True
        ).first()
        
        if approved_item:
            flash('Cannot add items to an approved courier', 'danger')
            return redirect(url_for('courier_details', id=id))
        
        new_item = CourierItem(
            courier_id=courier.id,
            container_number=request.form.get('container_number') or None,
            sender_name=request.form.get('sender_name'),
            receiver_name=request.form.get('receiver_name'),
            amount=float(request.form.get('amount')),
            service=float(request.form.get('service')),
            exchange_rate=float(request.form.get('exchange_rate'))
        )
        
        db.session.add(new_item)
        db.session.commit()
        
        flash('Item added successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding item: {str(e)}', 'danger')
    
    return redirect(url_for('courier_details', id=id))

@app.route('/courier/<int:courier_id>/item/<int:item_id>/edit', methods=['POST'])
@login_required
def edit_courier_item(courier_id, item_id):
    """Edit a courier item"""
    try:
        item = CourierItem.query.get_or_404(item_id)
        
        # Prevent editing if item is approved
        if item.is_received:
            return jsonify({'success': False, 'message': 'Cannot edit approved items'}), 403
        
        item.container_number = request.form.get('container_number') or None
        item.sender_name = request.form.get('sender_name')
        item.receiver_name = request.form.get('receiver_name')
        item.amount = float(request.form.get('amount'))
        item.service = float(request.form.get('service'))
        item.exchange_rate = float(request.form.get('exchange_rate'))
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Item updated successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/courier/<int:courier_id>/item/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_courier_item(courier_id, item_id):
    """Delete a courier item"""
    try:
        item = CourierItem.query.get_or_404(item_id)
        
        # Prevent deleting if item is approved
        if item.is_received:
            return jsonify({'success': False, 'message': 'Cannot delete approved items'}), 403
        
        db.session.delete(item)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Item deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/courier/<int:id>/delete', methods=['POST'])
@login_required
def delete_courier(id):
    """Delete a courier"""
    try:
        courier = Courier.query.get_or_404(id)
        
        # Check if courier has any approved items (but allow deletion with force parameter)
        approved_item = CourierItem.query.filter_by(
            courier_id=courier.id,
            is_received=True
        ).first()
        
        is_approved = bool(approved_item)
        
        db.session.delete(courier)
        db.session.commit()
        
        if is_approved:
            flash('Approved courier deleted successfully', 'warning')
        else:
            flash('Courier deleted successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting courier: {str(e)}', 'danger')
    
    return redirect(url_for('couriers'))

@app.route('/courier/<int:id>/is-approved', methods=['GET'])
@login_required
def check_courier_approved(id):
    """Check if a courier has approved items"""
    try:
        courier = Courier.query.get_or_404(id)
        
        approved_item = CourierItem.query.filter_by(
            courier_id=courier.id,
            is_received=True
        ).first()
        
        return jsonify({'is_approved': bool(approved_item)})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/courier/<int:courier_id>/item/<int:item_id>/approve', methods=['POST'])
@login_required
def approve_courier_item(courier_id, item_id):
    """Secretary or Admin approves receiving a courier item and enters market exchange rate"""
    try:
        # Only secretaries and admins can approve
        if current_user.role not in ['Secretary', 'Admin']:
            return jsonify({'success': False, 'message': 'Only secretaries and admins can approve courier items'}), 403
        
        item = CourierItem.query.get_or_404(item_id)
        
        # Check if already approved
        if item.is_received:
            return jsonify({'success': False, 'message': 'Item already approved'}), 400
        
        market_rate = request.form.get('market_exchange_rate')
        if not market_rate:
            return jsonify({'success': False, 'message': 'Market exchange rate is required'}), 400
        
        item.is_received = True
        item.market_exchange_rate = float(market_rate)
        item.received_at = datetime.utcnow()
        item.received_by = current_user.id
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Item approved successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/courier/<int:courier_id>/approve-all', methods=['POST'])
@login_required
def approve_all_courier_items(courier_id):
    """Secretary or Admin approves all courier items at once with market exchange rate (only once)"""
    try:
        # Only secretaries and admins can approve
        if current_user.role not in ['Secretary', 'Admin']:
            return jsonify({'success': False, 'message': 'Only secretaries and admins can approve courier items'}), 403
        
        courier = Courier.query.get_or_404(courier_id)
        
        # Check if any items are already approved
        approved_items = CourierItem.query.filter_by(
            courier_id=courier.id,
            is_received=True
        ).first()
        
        if approved_items:
            return jsonify({'success': False, 'message': 'Items have already been approved. Cannot approve again.'}), 400
        
        market_rate = request.form.get('market_exchange_rate')
        if not market_rate:
            return jsonify({'success': False, 'message': 'Market exchange rate is required'}), 400
        
        # Get all items for this courier
        all_items = CourierItem.query.filter_by(courier_id=courier.id).all()
        
        if not all_items:
            return jsonify({'success': False, 'message': 'No items found'}), 400
        
        # Approve all items
        approved_count = 0
        for item in all_items:
            item.is_received = True
            item.market_exchange_rate = float(market_rate)
            item.received_at = datetime.utcnow()
            item.received_by = current_user.id
            approved_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Successfully approved {approved_count} item(s)'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# Air Freight Routes
@app.route('/air-freight/login', methods=['GET', 'POST'])
def air_freight_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = AirFreightUser.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password) and user.is_active:
            session['air_freight_user'] = True
            login_user(user)
            return redirect(url_for('air_freight_dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('air_freight/login.html')

@app.route('/air-freight/logout', methods=['POST'])
@air_freight_login_required
def air_freight_logout():
    session.pop('air_freight_user', None)
    logout_user()
    return redirect(url_for('air_freight_login'))

def generate_air_freight_package_number():
    """Generate a unique package number for air freight packages.
    Format: AF + YYYY + MM + 4-digit sequential number
    Example: AF2026010001
    """
    from datetime import datetime
    
    # Get current year and month
    now = datetime.now()
    year_month = now.strftime('%Y%m')
    
    # Find the highest package number for this month
    prefix = f"AF{year_month}"
    
    # Query existing packages with this prefix
    existing_packages = AirFreightPackage.query.filter(
        AirFreightPackage.package_number.like(f"{prefix}%")
    ).all()
    
    # Extract the sequential numbers
    sequential_numbers = []
    for package in existing_packages:
        try:
            # Extract the last 4 digits after the prefix
            suffix = package.package_number[len(prefix):]
            if suffix.isdigit() and len(suffix) == 4:
                sequential_numbers.append(int(suffix))
        except (ValueError, IndexError):
            continue
    
    # Get the next sequential number
    if sequential_numbers:
        next_number = max(sequential_numbers) + 1
    else:
        next_number = 1
    
    # Format with leading zeros to make it 4 digits
    return f"{prefix}{next_number:04d}"

@app.route('/air-freight/dashboard')
@air_freight_login_required
def air_freight_dashboard():
    packages = AirFreightPackage.query.filter_by(delivered=False).order_by(AirFreightPackage.created_at.desc()).all()
    
    # Prepare photo URLs for packages
    for package in packages:
        if package.photo_data:
            package.photo_url = f"data:{package.photo_mime};base64,{base64.b64encode(package.photo_data).decode()}"
        else:
            package.photo_url = None
    
    return render_template('air_freight/dashboard.html', packages=packages)

@app.route('/air-freight/add-package', methods=['GET', 'POST'])
@air_freight_login_required
def add_air_freight_package():
    if request.method == 'POST':
        # Generate package number automatically
        package_number = generate_air_freight_package_number()
        mark = request.form.get('mark')
        airline = request.form.get('airline')  # New airline field
        
        # Handle photo upload
        photo_data = None
        photo_filename = None
        photo_mime = None
        
        if 'photo' in request.files:
            photo_file = request.files['photo']
            if photo_file and photo_file.filename:
                photo_data = photo_file.read()
                photo_filename = photo_file.filename
                photo_mime = photo_file.mimetype
        
        new_package = AirFreightPackage(
            package_number=package_number,
            mark=mark,
            airline=airline,  # Add airline field
            photo_data=photo_data,
            photo_filename=photo_filename,
            photo_mime=photo_mime
        )
        
        db.session.add(new_package)
        db.session.commit()
        
        flash('Package added successfully!', 'success')
        return redirect(url_for('air_freight_dashboard'))
    
    # Generate preview package number for GET request
    preview_package_number = generate_air_freight_package_number()
    return render_template('air_freight/add_package.html', preview_package_number=preview_package_number)

@app.route('/air-freight/package/<int:package_id>')
@air_freight_login_required
def air_freight_package_details(package_id):
    package = AirFreightPackage.query.get_or_404(package_id)
    
    # Prepare photo URL for package
    if package.photo_data:
        package.photo_url = f"data:{package.photo_mime};base64,{base64.b64encode(package.photo_data).decode()}"
    else:
        package.photo_url = None
    
    return render_template('air_freight/package_details.html', package=package)

@app.route('/air-freight/package/<int:package_id>/add-client', methods=['GET', 'POST'])
@air_freight_login_required
def add_air_freight_client(package_id):
    package = AirFreightPackage.query.get_or_404(package_id)
    
    # Prevent adding clients to delivered packages
    if package.delivered:
        flash('Cannot add clients to delivered packages.', 'warning')
        return redirect(url_for('air_freight_package_details', package_id=package_id))
    
    if request.method == 'POST':
        name = request.form.get('name')
        mark = request.form.get('mark')
        phone = request.form.get('phone')
        
        new_client = AirFreightClient(
            package_id=package_id,
            name=name,
            mark=mark,
            phone=phone
        )
        
        db.session.add(new_client)
        db.session.commit()
        
        flash('Client added successfully!', 'success')
        return redirect(url_for('air_freight_package_details', package_id=package_id))
    
    return render_template('air_freight/add_client.html', package=package)

@app.route('/air-freight/package/<int:package_id>/edit', methods=['GET', 'POST'])
@air_freight_login_required
def edit_air_freight_package(package_id):
    package = AirFreightPackage.query.get_or_404(package_id)
    
    if request.method == 'POST':
        package.mark = request.form.get('mark')
        package.airline = request.form.get('airline')  # Add airline field
        
        # Handle photo upload
        if 'photo' in request.files:
            photo_file = request.files['photo']
            if photo_file and photo_file.filename:
                package.photo_data = photo_file.read()
                package.photo_filename = photo_file.filename
                package.photo_mime = photo_file.mimetype
        
        db.session.commit()
        flash('Package updated successfully!', 'success')
        return redirect(url_for('air_freight_dashboard'))
    
    # Prepare photo URL for display
    if package.photo_data:
        package.photo_url = f"data:{package.photo_mime};base64,{base64.b64encode(package.photo_data).decode()}"
    else:
        package.photo_url = None
    
    return render_template('air_freight/edit_package.html', package=package)

@app.route('/air-freight/package/<int:package_id>/toggle-delivery', methods=['POST'])
@air_freight_login_required
def toggle_air_freight_package_delivery(package_id):
    package = AirFreightPackage.query.get_or_404(package_id)
    package.delivered = not package.delivered
    db.session.commit()
    
    status = "delivered" if package.delivered else "in transit"
    flash(f'Package marked as {status}!', 'success')
    return redirect(url_for('air_freight_dashboard'))

@app.route('/air-freight/package/<int:package_id>/delete', methods=['POST'])
@air_freight_login_required
def delete_air_freight_package(package_id):
    package = AirFreightPackage.query.get_or_404(package_id)
    db.session.delete(package)
    db.session.commit()
    flash('Package deleted successfully!', 'success')
    return redirect(url_for('air_freight_dashboard'))

@app.route('/air-freight/client/<int:client_id>')
@air_freight_login_required
def air_freight_client_details(client_id):
    client = AirFreightClient.query.get_or_404(client_id)
    
    # Prepare photo URLs for products
    for product in client.products:
        if product.photo_data:
            product.photo_url = f"data:{product.photo_mime};base64,{base64.b64encode(product.photo_data).decode()}"
        else:
            product.photo_url = None
    
    return render_template('air_freight/client_details.html', client=client)

@app.route('/air-freight/client/<int:client_id>/print')
@air_freight_login_required
def air_freight_client_print(client_id):
    from datetime import datetime
    client = AirFreightClient.query.get_or_404(client_id)
    return render_template('air_freight/client_print.html', client=client, now=datetime.now())

@app.route('/air-freight/client/<int:client_id>/add-product', methods=['GET', 'POST'])
@air_freight_login_required
def add_air_freight_product(client_id):
    client = AirFreightClient.query.get_or_404(client_id)
    
    # Prevent adding products to clients of delivered packages
    if client.package.delivered:
        flash('Cannot add products to clients of delivered packages.', 'warning')
        return redirect(url_for('air_freight_client_details', client_id=client_id))
    
    if request.method == 'POST':
        reference = request.form.get('reference')
        quantity = int(request.form.get('quantity', 1))
        weight = float(request.form.get('weight', 0))
        freight_price_aed = float(request.form.get('freight_price_aed', 0))
        freight_paid = request.form.get('freight_paid') == 'on'
        
        # Handle photo upload
        photo_data = None
        photo_filename = None
        photo_mime = None
        
        if 'photo' in request.files:
            photo_file = request.files['photo']
            if photo_file and photo_file.filename:
                photo_data = photo_file.read()
                photo_filename = photo_file.filename
                photo_mime = photo_file.mimetype
        
        new_product = AirFreightProduct(
            client_id=client_id,
            reference=reference,
            quantity=quantity,
            weight=weight,
            value=freight_price_aed,  # Using value field for freight price in AED
            freight_paid=freight_paid,
            photo_data=photo_data,
            photo_filename=photo_filename,
            photo_mime=photo_mime
        )
        
        db.session.add(new_product)
        db.session.commit()
        
        flash('Product added successfully!', 'success')
        return redirect(url_for('air_freight_client_details', client_id=client_id))
    
    return render_template('air_freight/add_product.html', client=client)

@app.route('/air-freight/client/<int:client_id>/edit', methods=['GET', 'POST'])
@air_freight_login_required
def edit_air_freight_client(client_id):
    client = AirFreightClient.query.get_or_404(client_id)
    
    # Prevent editing clients of delivered packages
    if client.package.delivered:
        flash('Cannot edit clients of delivered packages.', 'warning')
        return redirect(url_for('air_freight_package_details', package_id=client.package_id))
    
    if request.method == 'POST':
        client.name = request.form.get('name')
        client.mark = request.form.get('mark')
        client.phone = request.form.get('phone')
        
        db.session.commit()
        
        flash('Client updated successfully!', 'success')
        return redirect(url_for('air_freight_package_details', package_id=client.package_id))
    
    return render_template('air_freight/edit_client.html', client=client)

@app.route('/air-freight/client/<int:client_id>/delete', methods=['POST'])
@air_freight_login_required
def delete_air_freight_client(client_id):
    client = AirFreightClient.query.get_or_404(client_id)
    package_id = client.package_id
    
    # Prevent deleting clients of delivered packages
    if client.package.delivered:
        flash('Cannot delete clients of delivered packages.', 'warning')
        return redirect(url_for('air_freight_package_details', package_id=package_id))
    
    try:
        # Delete all products associated with this client first
        AirFreightProduct.query.filter_by(client_id=client_id).delete()
        
        # Delete the client
        db.session.delete(client)
        db.session.commit()
        
        flash('Client and all associated products deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting client: {str(e)}', 'danger')
    
    return redirect(url_for('air_freight_package_details', package_id=package_id))

@app.route('/air-freight/client/<int:client_id>/confirm-delivery', methods=['POST'])
@air_freight_login_required
def confirm_client_delivery(client_id):
    client = AirFreightClient.query.get_or_404(client_id)
    package_id = client.package_id
    
    # Toggle the delivery status
    client.delivered = not client.delivered
    db.session.commit()
    
    status_text = "delivered" if client.delivered else "marked as in transit"
    flash(f'Client {client.name} has been {status_text}!', 'success')
    
    return redirect(url_for('air_freight_package_details', package_id=package_id))

@app.route('/air-freight/product/<int:product_id>/edit', methods=['GET', 'POST'])
@air_freight_login_required
def edit_air_freight_product(product_id):
    product = AirFreightProduct.query.get_or_404(product_id)
    
    # Prevent editing products of delivered packages
    if product.client.package.delivered:
        flash('Cannot edit products of delivered packages.', 'warning')
        return redirect(url_for('air_freight_client_details', client_id=product.client_id))
    
    if request.method == 'POST':
        product.reference = request.form.get('reference')
        product.quantity = int(request.form.get('quantity', 1))
        product.weight = float(request.form.get('weight', 0))
        product.value = float(request.form.get('freight_price_aed', 0))  # Using value field for freight price in AED
        product.freight_paid = request.form.get('freight_paid') == 'on'
        
        # Handle photo upload (optional - keep existing if no new photo)
        if 'photo' in request.files:
            photo_file = request.files['photo']
            if photo_file and photo_file.filename:
                product.photo_data = photo_file.read()
                product.photo_filename = photo_file.filename
                product.photo_mime = photo_file.mimetype
        
        db.session.commit()
        
        flash('Product updated successfully!', 'success')
        return redirect(url_for('air_freight_client_details', client_id=product.client_id))
    
    return render_template('air_freight/edit_product.html', product=product)

@app.route('/air-freight/product/<int:product_id>/delete', methods=['POST'])
@air_freight_login_required
def delete_air_freight_product(product_id):
    product = AirFreightProduct.query.get_or_404(product_id)
    client_id = product.client_id
    
    # Prevent deleting products of delivered packages
    if product.client.package.delivered:
        flash('Cannot delete products of delivered packages.', 'warning')
        return redirect(url_for('air_freight_client_details', client_id=client_id))
    
    try:
        db.session.delete(product)
        db.session.commit()
        
        flash('Product deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting product: {str(e)}', 'danger')
    
    return redirect(url_for('air_freight_client_details', client_id=client_id))

# Air Freight User Management Routes
@app.route('/air-freight/users')
@air_freight_login_required
def air_freight_users():
    if not current_user.is_admin():
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('air_freight_dashboard'))
    
    users = AirFreightUser.query.order_by(AirFreightUser.created_at.desc()).all()
    return render_template('air_freight/users.html', users=users)

@app.route('/air-freight/users/add', methods=['GET', 'POST'])
@air_freight_login_required
def add_air_freight_user():
    if not current_user.is_admin():
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('air_freight_dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role', 'Employee')
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        
        # Check if username already exists
        existing_user = AirFreightUser.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists!', 'danger')
            return redirect(url_for('add_air_freight_user'))
        
        # Create new user
        hashed_password = generate_password_hash(password)
        new_user = AirFreightUser(
            username=username,
            password=hashed_password,
            role=role,
            full_name=full_name,
            email=email,
            phone=phone
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('User created successfully!', 'success')
            return redirect(url_for('air_freight_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'danger')
    
    return render_template('air_freight/add_user.html')

@app.route('/air-freight/users/<int:user_id>/edit', methods=['GET', 'POST'])
@air_freight_login_required
def edit_air_freight_user(user_id):
    if not current_user.is_admin():
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('air_freight_dashboard'))
    
    user = AirFreightUser.query.get_or_404(user_id)
    
    if request.method == 'POST':
        # Check if username is being changed and if it's already taken
        new_username = request.form.get('username')
        if new_username != user.username:
            existing_user = AirFreightUser.query.filter_by(username=new_username).first()
            if existing_user:
                flash('Username already exists!', 'danger')
                return redirect(url_for('edit_air_freight_user', user_id=user_id))
        
        # Update user information
        user.username = new_username
        password = request.form.get('password')
        if password:  # Only update password if provided
            user.password = generate_password_hash(password)
        user.role = request.form.get('role', 'Employee')
        user.full_name = request.form.get('full_name')
        user.email = request.form.get('email')
        user.phone = request.form.get('phone')
        user.is_active = request.form.get('is_active') == 'on'
        
        try:
            db.session.commit()
            flash('User updated successfully!', 'success')
            return redirect(url_for('air_freight_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating user: {str(e)}', 'danger')
    
    return render_template('air_freight/edit_user.html', user=user)

@app.route('/air-freight/users/<int:user_id>/delete', methods=['POST'])
@air_freight_login_required
def delete_air_freight_user(user_id):
    if not current_user.is_admin():
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('air_freight_dashboard'))
    
    user = AirFreightUser.query.get_or_404(user_id)
    
    # Prevent deleting yourself
    if user.id == current_user.id:
        flash('You cannot delete your own account!', 'danger')
        return redirect(url_for('air_freight_users'))
    
    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    
    return redirect(url_for('air_freight_users'))

@app.route('/air-freight/history')
@air_freight_login_required
def air_freight_history():
    # Get all delivered packages ordered by delivery date (most recent first)
    delivered_packages = AirFreightPackage.query.filter_by(delivered=True).order_by(AirFreightPackage.created_at.desc()).all()
    
    # Prepare photo URLs for packages
    for package in delivered_packages:
        if package.photo_data:
            package.photo_url = f"data:{package.photo_mime};base64,{base64.b64encode(package.photo_data).decode()}"
        else:
            package.photo_url = None
    
    return render_template('air_freight/history.html', packages=delivered_packages)

def init_air_freight_admin():
    """Initialize default admin user for air freight system"""
    admin_user = AirFreightUser.query.filter_by(username='admin').first()
    if not admin_user:
        hashed_password = generate_password_hash('admin123')
        admin_user = AirFreightUser(
            username='admin',
            password=hashed_password,
            role='Admin',
            full_name='Air Freight Administrator',
            email='admin@airfreight.com'
        )
        db.session.add(admin_user)
        db.session.commit()
        print("Default air freight admin user created: username='admin', password='admin123'")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_air_freight_admin()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5002)))
