-- ---------------------------------------------------------------------
-- MANUAL migration for EXISTING databases.
--
-- Scripts in /docker-entrypoint-initdb.d only run on the FIRST startup of
-- the postgres container. A database that was already initialised will NOT
-- pick up new tables/columns added to 01_schema.sql automatically.
--
-- Run this file by hand once, on every environment whose DB predates these
-- changes (local AND the VPS):
--
--   docker compose exec -T postgres psql -U postgres -d ragdb < db/init/02_migration.sql
--
-- Everything here is idempotent (IF NOT EXISTS), so re-running it is safe.
-- ---------------------------------------------------------------------

-- (a) content-level dedup column, added earlier
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_hash VARCHAR(32) UNIQUE;

-- (b) users table — must exist before documents.user_id can reference it
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP DEFAULT now()
);

-- (c) link existing documents to an owner (NULL for legacy rows)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_user_id ON documents (user_id);

-- (c2) dedup must be PER-USER, not global. The original column was created with
-- a global UNIQUE(file_hash), which wrongly rejects user B uploading a file that
-- user A already has. Swap it for UNIQUE(user_id, file_hash) to match
-- find_by_hash() in service.py. Idempotent: drops the old constraint if present,
-- adds the new one only if missing.
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_file_hash_key;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_user_hash_key'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_user_hash_key UNIQUE (user_id, file_hash);
    END IF;
END $$;

-- (d) conversation history
CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY,
    user_id    UUID REFERENCES users(id),
    title      VARCHAR(255),
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations (user_id);

CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20),
    content         TEXT,
    created_at      TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages (conversation_id, created_at);

-- (e) agent traces — observability for the agentic-RAG loop
CREATE TABLE IF NOT EXISTS agent_traces (
    id              UUID PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    conversation_id UUID,
    question        TEXT,
    answer          TEXT,
    model           VARCHAR(60),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        NUMERIC,
    tool_calls      INTEGER,
    num_turns       INTEGER,
    duration_ms     INTEGER,
    status          VARCHAR(20),
    error           TEXT,
    steps           JSONB,
    created_at      TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trace_user ON agent_traces (user_id, created_at DESC);
