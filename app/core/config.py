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


# --- Auth / JWT ------------------------------------------------------------
# JWT_SECRET signs every login token. In production ALWAYS override it with a
# long random value via env (generate one with `openssl rand -hex 32`); the
# default below is for local development only.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
# How long a login stays valid before the user must sign in again. Default 7 days.
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24 * 7)))


# --- Celery / Redis --------------------------------------------------------
# Redis is BOTH the broker (task queue) and the result backend. In compose,
# the hostname "redis" resolves to the redis service over the internal network.
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
