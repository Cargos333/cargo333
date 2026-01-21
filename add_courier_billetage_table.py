"""
Migration script to add courier_billetage table to production database
Run this once on production to create the missing table
"""
from app import app, db
from models import CourierBilletage

def migrate_add_courier_billetage():
    with app.app_context():
        print("Adding courier_billetage table to database...")
        
        try:
            # Create only the CourierBilletage table
            CourierBilletage.__table__.create(db.engine, checkfirst=True)
            print("✅ courier_billetage table created successfully!")
            
            # Verify the table was created
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'courier_billetage' in tables:
                print("✅ Verified: courier_billetage table exists in database")
                print("\nTable columns:")
                columns = inspector.get_columns('courier_billetage')
                for col in columns:
                    print(f"  - {col['name']}: {col['type']}")
            else:
                print("⚠️  Warning: Table creation reported success but table not found in database")
                
        except Exception as e:
            print(f"❌ Error creating table: {str(e)}")
            raise

if __name__ == "__main__":
    migrate_add_courier_billetage()
