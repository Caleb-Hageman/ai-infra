CREATE INDEX idx_documents_project ON documents(project_id);
CREATE INDEX idx_chunks_document ON document_chunks(document_id);

CREATE UNIQUE INDEX idx_chunks_order
  ON document_chunks(document_id, chunk_index);

CREATE TABLE query_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id UUID NOT NULL REFERENCES teams(id),
  project_id UUID NOT NULL REFERENCES projects(id),
  api_key_id UUID REFERENCES api_keys(id),
  question_hash TEXT NOT NULL,
  used_rag BOOLEAN NOT NULL,
  top_k INT,
  model TEXT,
  latency_ms INT,
  prompt_tokens INT,
  completion_tokens INT,
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE query_citations (
  query_id UUID NOT NULL REFERENCES query_logs(id) ON DELETE CASCADE,
  chunk_id UUID NOT NULL REFERENCES document_chunks(id),
  rank INT NOT NULL,
  score FLOAT,
  PRIMARY KEY (query_id, chunk_id)
);
