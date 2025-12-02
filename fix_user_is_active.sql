-- SQL script to fix the is_active column type in user table
-- Run this in your Render PostgreSQL database

-- Step 1: Convert existing data
UPDATE "user" 
SET is_active = CASE 
    WHEN is_active = 0 THEN false 
    ELSE true 
END
WHERE is_active IN (0, 1);

-- Step 2: Change column type to boolean
ALTER TABLE "user" 
ALTER COLUMN is_active TYPE BOOLEAN 
USING CASE 
    WHEN is_active = 0 THEN false 
    ELSE true 
END;

-- Step 3: Set default value
ALTER TABLE "user" 
ALTER COLUMN is_active SET DEFAULT true;
