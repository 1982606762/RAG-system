"""Storage layer — thin helpers over PostgreSQL and the ChromaDB service.

Both stores are linked by file_id (a UUID). ChromaDB finds *which* file is
relevant; PostgreSQL holds the full structured metadata for that file.
"""

import json
from functools import lru_cache

import chromadb
import psycopg
from sentence_transformers import SentenceTransformer

from core.config import (
    PG_DSN,
    CHROMA_HOST,
    CHROMA_PORT,
    CHROMA_COLLECTION,
    EMBED_MODEL,
)


# --- BGE-M3 Embedding (local, computed by this process) --------------------

@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    # Loaded once on first call; subsequent calls return the cached instance.
    return SentenceTransformer(EMBED_MODEL)


def _embed(texts: list[str]) -> list[list[float]]:
    """Return L2-normalised 1024-dim embeddings for a list of texts."""
    return _get_embedder().encode(texts, normalize_embeddings=True).tolist()


# --- ChromaDB (vector store, a remote service) -----------------------------

def get_collection():
    """Connect to the ChromaDB SERVER (not an embedded file) via HttpClient."""
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return client.get_or_create_collection(name=CHROMA_COLLECTION)


def add_vector(file_id: str, text: str, doc_type: str):
    """Compute a BGE-M3 embedding locally, then store it in ChromaDB."""
    embeddings = _embed([text])
    get_collection().upsert(
        ids=[file_id],
        embeddings=embeddings,
        documents=[text],
        metadatas=[{"doc_type": doc_type or "other"}],
    )


def vector_search(question: str, n: int = 3):
    """Return the most semantically similar file_ids."""
    query_embedding = _embed([question])
    results = get_collection().query(query_embeddings=query_embedding, n_results=n)
    return results["ids"][0]


def vector_search_with_text(question: str, n: int = 3):
    """Like vector_search but also returns the stored narrative text per hit."""
    query_embedding = _embed([question])
    results = get_collection().query(query_embeddings=query_embedding, n_results=n)
    return list(zip(results["ids"][0], results["documents"][0]))


# --- PostgreSQL (structured metadata) --------------------------------------

def find_by_hash(file_hash: str) -> str | None:
    """Return existing file_id if this MD5 hash was already ingested."""
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT file_id FROM documents WHERE file_hash = %s",
            (file_hash,),
        ).fetchone()
    return str(row[0]) if row else None


def insert_document(file_id: str, doc: dict, file_path: str, file_hash: str | None = None):
    """Write fixed columns + the full JSON (JSONB), keyed by file_id."""
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            """
            INSERT INTO documents
                (file_id, doc_type, doc_date, amount, currency,
                 vendor, summary, file_path, full_analysis, file_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (file_id) DO NOTHING
            """,
            (
                file_id,
                doc.get("doc_type"),
                doc.get("doc_date") or None,
                doc.get("amount"),
                doc.get("currency"),
                doc.get("vendor"),
                doc.get("summary"),
                file_path,
                json.dumps(doc, ensure_ascii=False),
                file_hash,
            ),
        )


def fetch_by_ids(file_ids):
    """Enrich vector hits with full metadata from PostgreSQL (the join)."""
    if not file_ids:
        return []
    with psycopg.connect(PG_DSN) as conn:
        return conn.execute(
            "SELECT file_id, doc_type, vendor, summary, amount "
            "FROM documents WHERE file_id = ANY(%s)",
            (list(file_ids),),
        ).fetchall()


def run_sql(sql: str, params=()):
    """Run an arbitrary SELECT for exact / range / aggregate queries."""
    with psycopg.connect(PG_DSN) as conn:
        return conn.execute(sql, params).fetchall()


def run_select_safe(sql: str):
    """Read-only guard for SQL coming from the LLM.

    Allows only a single SELECT so a crafted query can't modify or drop data.
    Teaching-grade guard; production would also use a read-only DB role.
    """
    cleaned = sql.strip().rstrip(";").strip()
    lowered = cleaned.lower()
    if not lowered.startswith("select"):
        raise ValueError("只允许 SELECT 查询")
    forbidden = (";", " insert ", " update ", " delete ", " drop ",
                 " alter ", " truncate ", " create ", " grant ")
    if any(tok in f" {lowered} " for tok in forbidden):
        raise ValueError("查询包含不允许的操作")
    with psycopg.connect(PG_DSN) as conn:
        return conn.execute(cleaned).fetchall()
