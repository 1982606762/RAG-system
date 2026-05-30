-- Runs automatically on the FIRST startup of the postgres container
-- (anything in /docker-entrypoint-initdb.d is executed once on init).
--
-- Fixed columns (indexed) for frequent filters/sorts, plus one JSONB column
-- holding Claude's full output incl. the dynamic `details` layer.
-- file_id is the UUID that links this row to ChromaDB and the original file.

CREATE TABLE IF NOT EXISTS documents (
    file_id       UUID PRIMARY KEY,
    doc_type      VARCHAR(50),
    doc_date      DATE,
    amount        NUMERIC,
    currency      VARCHAR(10),
    vendor        VARCHAR(255),
    summary       TEXT,
    file_path     TEXT,
    full_analysis JSONB,
    -- MD5 hex digest of the raw file; NULL = legacy row ingested before dedup.
    -- UNIQUE so the same file can't be inserted twice.
    file_hash     VARCHAR(32) UNIQUE,
    created_at    TIMESTAMP DEFAULT now()
);

-- For existing installs (table already exists), run once manually:
--   ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_hash VARCHAR(32) UNIQUE;

CREATE INDEX IF NOT EXISTS idx_doc_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_doc_date ON documents (doc_date);
CREATE INDEX IF NOT EXISTS idx_amount   ON documents (amount);
CREATE INDEX IF NOT EXISTS idx_vendor   ON documents (vendor);
CREATE INDEX IF NOT EXISTS idx_full_analysis ON documents USING GIN (full_analysis);
