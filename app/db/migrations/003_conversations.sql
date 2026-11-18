CREATE TABLE IF NOT EXISTS knowledge_base_v1.conversations (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_base_v1.conversation_turns (
    conversation_id UUID NOT NULL REFERENCES knowledge_base_v1.conversations(id) ON DELETE CASCADE,
    id UUID NOT NULL,
    turn_index INTEGER NOT NULL CHECK (turn_index > 0),
    question TEXT NOT NULL,
    depth TEXT NOT NULL CHECK (depth IN ('auto', 'deep')),
    answer JSONB NOT NULL,
    PRIMARY KEY (conversation_id, turn_index),
    UNIQUE (conversation_id, id)
);

CREATE INDEX IF NOT EXISTS conversations_recent_idx
    ON knowledge_base_v1.conversations (updated_at DESC, id DESC);
