-- SQL script to create container_document table in PostgreSQL
-- Run this in your Render PostgreSQL database

CREATE TABLE IF NOT EXISTS container_document (
    id SERIAL PRIMARY KEY,
    container_id INTEGER NOT NULL,
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    file_data BYTEA NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_size INTEGER NOT NULL,
    uploaded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
    uploaded_by INTEGER,
    FOREIGN KEY (container_id) REFERENCES container(id) ON DELETE CASCADE
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS ix_container_document_container_id ON container_document(container_id);
