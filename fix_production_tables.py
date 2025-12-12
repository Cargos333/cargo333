"""
Safe migration script for production - adds missing tables and columns without losing data
"""
from db_config import app, db
from sqlalchemy import text

def fix_production_tables():
    with app.app_context():
        connection = db.engine.connect()
        
        print("Starting safe migration...")
        
        try:
            # Check if courier table exists
            result = connection.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'courier'
                );
            """))
            courier_exists = result.scalar()
            
            if not courier_exists:
                print("Creating courier table...")
                connection.execute(text("""
                    CREATE TABLE courier (
                        id SERIAL PRIMARY KEY,
                        courier_id VARCHAR(50) UNIQUE NOT NULL,
                        date TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """))
                connection.commit()
                print("✓ Courier table created")
            else:
                print("✓ Courier table already exists")
            
            # Check if courier_item table exists
            result = connection.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'courier_item'
                );
            """))
            courier_item_exists = result.scalar()
            
            if not courier_item_exists:
                print("Creating courier_item table...")
                connection.execute(text("""
                    CREATE TABLE courier_item (
                        id SERIAL PRIMARY KEY,
                        courier_id INTEGER NOT NULL REFERENCES courier(id),
                        container_number VARCHAR(50),
                        sender_name VARCHAR(100) NOT NULL,
                        receiver_name VARCHAR(100) NOT NULL,
                        amount FLOAT NOT NULL,
                        service FLOAT NOT NULL,
                        exchange_rate FLOAT NOT NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        is_received BOOLEAN DEFAULT FALSE,
                        market_exchange_rate FLOAT,
                        received_at TIMESTAMP WITHOUT TIME ZONE,
                        received_by INTEGER REFERENCES "user"(id)
                    );
                """))
                connection.commit()
                print("✓ Courier_item table created")
            else:
                print("✓ Courier_item table already exists")
                
                # Check if approval columns exist
                result = connection.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'courier_item' 
                    AND column_name IN ('is_received', 'market_exchange_rate', 'received_at', 'received_by');
                """))
                existing_columns = [row[0] for row in result]
                
                # Add missing columns
                if 'is_received' not in existing_columns:
                    print("Adding is_received column...")
                    connection.execute(text("""
                        ALTER TABLE courier_item 
                        ADD COLUMN is_received BOOLEAN DEFAULT FALSE;
                    """))
                    connection.commit()
                    print("✓ is_received column added")
                
                if 'market_exchange_rate' not in existing_columns:
                    print("Adding market_exchange_rate column...")
                    connection.execute(text("""
                        ALTER TABLE courier_item 
                        ADD COLUMN market_exchange_rate FLOAT;
                    """))
                    connection.commit()
                    print("✓ market_exchange_rate column added")
                
                if 'received_at' not in existing_columns:
                    print("Adding received_at column...")
                    connection.execute(text("""
                        ALTER TABLE courier_item 
                        ADD COLUMN received_at TIMESTAMP WITHOUT TIME ZONE;
                    """))
                    connection.commit()
                    print("✓ received_at column added")
                
                if 'received_by' not in existing_columns:
                    print("Adding received_by column...")
                    connection.execute(text("""
                        ALTER TABLE courier_item 
                        ADD COLUMN received_by INTEGER REFERENCES "user"(id);
                    """))
                    connection.commit()
                    print("✓ received_by column added")
            
            print("\n✅ Migration completed successfully!")
            print("All your existing data has been preserved.")
            
        except Exception as e:
            connection.rollback()
            print(f"\n❌ Error during migration: {str(e)}")
            raise e
        finally:
            connection.close()

if __name__ == "__main__":
    fix_production_tables()
