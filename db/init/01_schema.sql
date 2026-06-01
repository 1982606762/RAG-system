-- Runs automatically on the FIRST startup of the postgres container
-- (anything in /docker-entrypoint-initdb.d is executed once on init).
--
-- IMPORTANT: table creation order matters because of foreign keys.
-- A table referenced by REFERENCES must be created BEFORE the table that
-- points at it. So the order here is: users -> documents -> conversations
-- -> messages.


-- =====================================================================
-- users — one row per account. Login/auth is built on top of this table.
-- =====================================================================
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,   -- bcrypt hash, never the raw password
    created_at    TIMESTAMP DEFAULT now()
);


-- =====================================================================
-- documents — structured metadata for each ingested file.
-- Fixed columns (indexed) for frequent filters/sorts, plus one JSONB column
-- holding Claude's full output incl. the dynamic `details` layer.
-- file_id is the UUID that links this row to ChromaDB and the original file.
-- =====================================================================
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
    -- MD5 hex digest of the raw file. Dedup is PER-USER (see the UNIQUE
    -- constraint below), so the same file uploaded by two different users is
    -- stored twice — one row each.
    file_hash     VARCHAR(32),
    -- Owner of this file. NULL = legacy row ingested before the auth system.
    user_id       UUID REFERENCES users(id),
    created_at    TIMESTAMP DEFAULT now(),
    -- Per-user content dedup: a given user can't store the same file twice, but
    -- different users can each have their own copy. This matches find_by_hash()
    -- in service.py, which always filters by user_id. (A plain UNIQUE(file_hash)
    -- would be GLOBAL and wrongly reject user B's file just because user A has it.)
    CONSTRAINT documents_user_hash_key UNIQUE (user_id, file_hash)
);

CREATE INDEX IF NOT EXISTS idx_doc_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_doc_date ON documents (doc_date);
CREATE INDEX IF NOT EXISTS idx_amount   ON documents (amount);
CREATE INDEX IF NOT EXISTS idx_vendor   ON documents (vendor);
CREATE INDEX IF NOT EXISTS idx_user_id  ON documents (user_id);
CREATE INDEX IF NOT EXISTS idx_full_analysis ON documents USING GIN (full_analysis);


-- =====================================================================
-- conversations — one chat thread. A user can have many conversations.
-- =====================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY,
    user_id    UUID REFERENCES users(id),
    title      VARCHAR(255),            -- e.g. first ~20 chars of the first question
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations (user_id);


-- =====================================================================
-- messages — every message inside a conversation, in order.
-- role is 'user' or 'assistant'. This is what gives the agent multi-turn
-- memory: we replay these rows back into Claude's `messages` list.
-- =====================================================================
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20),         -- 'user' | 'assistant'
    content         TEXT,
    created_at      TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages (conversation_id, created_at);
