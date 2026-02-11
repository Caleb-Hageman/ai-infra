CREATE TYPE document_source_type AS ENUM ('upload', 'url', 'manual');
CREATE TYPE document_status AS ENUM ('uploaded', 'processing', 'ready', 'failed');
CREATE TYPE ingestion_status AS ENUM ('queued', 'running', 'succeeded', 'failed');
CREATE TYPE api_key_status AS ENUM ('active', 'revoked');
