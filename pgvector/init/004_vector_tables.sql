CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  title TEXT,
  source_type document_source_type NOT NULL,
  gcs_uri TEXT,
  mime_type TEXT,
  status document_status NOT NULL DEFAULT 'uploaded',
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE ingestion_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  status ingestion_status NOT NULL DEFAULT 'queued',
  error_message TEXT,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  chunks_created INT,
  embedding_model TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  vector_id TEXT NOT NULL,
  page_start INT,
  page_end INT,
  char_start INT,
  char_end INT,
  text_preview TEXT,
  token_count INT,
  created_at TIMESTAMP NOT NULL DEFAULT now()
);
