-- A separate namespace protects legacy tables. This migration is explicit.
CREATE SCHEMA IF NOT EXISTS knowledge_base_v1;

CREATE TABLE IF NOT EXISTS knowledge_base_v1.documents (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    status TEXT NOT NULL CHECK (status IN ('processing', 'ready', 'failed')),
    stage TEXT NOT NULL DEFAULT 'saved',
    error_code TEXT,
    error_message TEXT,
    page_count INTEGER,
    block_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    warnings JSONB NOT NULL DEFAULT '[]',
    parser_version TEXT,
    chunker_version TEXT,
    chunk_config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_base_v1.blocks (
    document_id UUID NOT NULL REFERENCES knowledge_base_v1.documents(id) ON DELETE CASCADE,
    block_index INTEGER NOT NULL,
    data JSONB NOT NULL,
    PRIMARY KEY (document_id, block_index)
);

CREATE TABLE IF NOT EXISTS knowledge_base_v1.chunks (
    document_id UUID NOT NULL REFERENCES knowledge_base_v1.documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    data JSONB NOT NULL,
    PRIMARY KEY (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS documents_created_idx
    ON knowledge_base_v1.documents (created_at DESC, id DESC);
