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
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
