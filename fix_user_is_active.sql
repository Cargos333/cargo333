-- SQL script to fix the is_active column type in user table
-- Run this in your Render PostgreSQL database

-- Step 1: Normalize existing bigint data to 0 or 1
UPDATE "user" 
SET is_active = CASE 
    WHEN is_active = 0 THEN 0::bigint
    ELSE 1::bigint
END;

-- Step 2: Change column type from bigint to boolean
ALTER TABLE "user" 
ALTER COLUMN is_active TYPE BOOLEAN 
USING CASE 
    WHEN is_active = 0 THEN false 
    WHEN is_active = 1 THEN true
    ELSE true 
END;

-- Step 3: Set default value
ALTER TABLE "user" 
ALTER COLUMN is_active SET DEFAULT true;
