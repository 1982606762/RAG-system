-- Vectors are derived data. Deleting/replacing a chunk invalidates all models.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_base_v1.embedding_runs (
    document_id UUID NOT NULL REFERENCES knowledge_base_v1.documents(id) ON DELETE CASCADE,
    profile TEXT NOT NULL,
    model_resource TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions = 768),
    status TEXT NOT NULL CHECK (status IN ('processing', 'ready', 'failed', 'pending')),
    completed_chunks INTEGER NOT NULL DEFAULT 0,
    total_chunks INTEGER NOT NULL,
    vector_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, profile)
);

CREATE TABLE IF NOT EXISTS knowledge_base_v1.embedding_parts (
    document_id UUID NOT NULL,
    chunk_index INTEGER NOT NULL,
    profile TEXT NOT NULL,
    start_char INTEGER NOT NULL CHECK (start_char >= 0),
    end_char INTEGER NOT NULL CHECK (end_char > start_char),
    chunk_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    data JSONB NOT NULL,
    embedding vector(768),
    token_count INTEGER CHECK (token_count > 0 AND token_count <= 2048),
    CHECK ((embedding IS NULL) = (token_count IS NULL)),
    PRIMARY KEY (document_id, chunk_index, profile, start_char, end_char),
    FOREIGN KEY (document_id, chunk_index) REFERENCES knowledge_base_v1.chunks(document_id, chunk_index) ON DELETE CASCADE,
    FOREIGN KEY (document_id, profile) REFERENCES knowledge_base_v1.embedding_runs(document_id, profile) ON DELETE CASCADE
);
