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
    created_at    TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doc_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_doc_date ON documents (doc_date);
CREATE INDEX IF NOT EXISTS idx_amount   ON documents (amount);
CREATE INDEX IF NOT EXISTS idx_vendor   ON documents (vendor);
CREATE INDEX IF NOT EXISTS idx_full_analysis ON documents USING GIN (full_analysis);
