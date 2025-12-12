"""
Fix user table structure and then create courier tables
"""
from db_config import app, db
from sqlalchemy import text

def fix_user_table_and_create_courier():
    with app.app_context():
        connection = db.engine.connect()
        
        print("Starting database fix...")
        
        try:
            # Check the structure of the user table
            print("\nChecking user table structure...")
            result = connection.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'user'
                ORDER BY ordinal_position;
            """))
            user_columns = result.fetchall()
            
            if user_columns:
                print("Current user table columns:")
                for col in user_columns:
                    print(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")
                
                # Check if id column has primary key constraint
                result = connection.execute(text("""
                    SELECT constraint_name, constraint_type
                    FROM information_schema.table_constraints
                    WHERE table_name = 'user' AND constraint_type = 'PRIMARY KEY';
                """))
                pk_exists = result.fetchone()
                
                if not pk_exists:
                    print("\n⚠️  User table missing primary key!")
                    print("Fixing user table by adding primary key constraint...")
                    
                    # Add primary key constraint
                    connection.execute(text("""
                        ALTER TABLE "user" ADD PRIMARY KEY (id);
                    """))
                    connection.commit()
                    print("✓ Primary key added to user table")
                else:
                    print("✓ User table has primary key")
            
            # Now create courier table
            result = connection.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'courier'
                );
            """))
            courier_exists = result.scalar()
            
            if not courier_exists:
                print("\nCreating courier table...")
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
            
            # Now create courier_item table
            result = connection.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'courier_item'
                );
            """))
            courier_item_exists = result.scalar()
            
            if not courier_item_exists:
                print("\nCreating courier_item table...")
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
                    print("\nAdding is_received column...")
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
            
            print("\n✅ Database fix completed successfully!")
            print("All your existing data has been preserved.")
            
        except Exception as e:
            connection.rollback()
            print(f"\n❌ Error during migration: {str(e)}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            connection.close()

if __name__ == "__main__":
    fix_user_table_and_create_courier()
