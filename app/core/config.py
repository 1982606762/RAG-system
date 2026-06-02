"""Central configuration — everything read from environment variables.

In containers we never hard-code hosts/passwords. docker-compose injects
these via environment / .env, and the same code runs locally if you export
the same vars.
"""

import os

# PostgreSQL connection (libpq DSN keywords).
PG_DSN = os.getenv(
    "PG_DSN",
    "host=postgres port=5432 dbname=ragdb user=postgres password=ragpass",
)

# ChromaDB runs as its OWN service, so we talk to it over HTTP.
CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "home_docs")

# Where uploaded originals are stored (mounted volume in docker-compose).
FILES_DIR = os.getenv("FILES_DIR", "/files")

# Anthropic. The SDK reads ANTHROPIC_API_KEY automatically; we expose the
# model name here so it's configurable in one place.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

AVAILABLE_MODELS = {
    "claude-haiku-4-5": "Haiku 4.5（快速·省钱）",
    "claude-sonnet-4-6": "Sonnet 4.6（更智能）",
}

# Local embedding model used for ChromaDB vectors.
# gte-Qwen2-1.5B-instruct is an LLM-backbone embedding model (1.5B params),
# producing 1536-dim vectors with strong Chinese / English / Danish support.
# NOTE: switching models requires clearing Chroma and re-ingesting all files.
EMBED_MODEL = os.getenv("EMBED_MODEL", "Alibaba-NLP/gte-Qwen2-1.5B-instruct")

# Relevance gate for the chat "file cards". Vector search ALWAYS returns the
# nearest N vectors, even when they're far away — so for an unrelated question
# ("你好") it still returns *something*. We only surface a file card when its
# distance is within this threshold, so off-topic chats show no cards.
# Embeddings are L2-normalised and Chroma uses squared-L2 distance, whose range
# is [0, 4] for unit vectors (0 = identical). ~1.0 ≈ cosine similarity 0.5.
# Tunable via .env; the evals harness can sweep this to find the best value.
RELEVANCE_MAX_DISTANCE = float(os.getenv("RELEVANCE_MAX_DISTANCE", "1.0"))


# --- Auth / JWT ------------------------------------------------------------
# JWT_SECRET signs every login token. In production ALWAYS override it with a
# long random value via env (generate one with `openssl rand -hex 32`); the
# default below is for local development only.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
# How long a login stays valid before the user must sign in again. Default 7 days.
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24 * 7)))

# Open self-registration. For a PRIVATE family knowledge base on a public VPS
# this should be OFF: otherwise anyone who finds your domain can sign up and
# burn YOUR Claude API quota. Create accounts via the CLI instead
# (`python cli.py create-user <email> <password>`). Set ALLOW_REGISTER=true in
# .env only if you really want public signups.
def _as_bool(val: str) -> bool:
    return val.strip().lower() in ("1", "true", "yes", "on")

ALLOW_REGISTER = _as_bool(os.getenv("ALLOW_REGISTER", "false"))


# --- Celery / Redis --------------------------------------------------------
# Redis is BOTH the broker (task queue) and the result backend. In compose,
# the hostname "redis" resolves to the redis service over the internal network.
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
