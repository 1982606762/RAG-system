"""Storage layer — thin helpers over PostgreSQL and the ChromaDB service.

Both stores are linked by file_id (a UUID). ChromaDB finds *which* file is
relevant; PostgreSQL holds the full structured metadata for that file.

Privacy model: every file belongs to a user. Vector hits are filtered by a
user_id stored in Chroma metadata; SQL is scoped to the user via a CTE (see
run_select_for_user). So one user can never see another user's files.
"""

import json
import uuid
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


# --- gte-Qwen2-1.5B Embedding (local, computed by this process) ------------
#
# gte-Qwen2-1.5B-instruct is built on the Qwen2 LLM backbone (1.5B params).
# Unlike BERT-style encoders, it uses a decoder-only architecture fine-tuned
# for retrieval, giving it much richer multilingual language understanding.
#
# It requires an instruction prefix to distinguish query vs. document:
#   - documents (stored): encoded as plain text, no prefix needed
#   - queries   (search): must be prefixed with the instruction string below
#
# Dimension: 1536  |  Max tokens: 8192  |  Memory: ~3 GB

_QUERY_INSTRUCTION = (
    "Instruct: Given a user query, retrieve the most relevant documents.\nQuery: "
)


@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    # Loaded once on first call; subsequent calls return the cached instance.
    return SentenceTransformer(EMBED_MODEL)


def _embed(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """Return L2-normalised 1536-dim embeddings for a list of texts.

    is_query=True  -> prepend the retrieval instruction (used at search time)
    is_query=False -> plain text, no prefix     (used at ingest time)
    """
    if is_query:
        texts = [_QUERY_INSTRUCTION + t for t in texts]
    return _get_embedder().encode(texts, normalize_embeddings=True).tolist()


# --- ChromaDB (vector store, a remote service) -----------------------------

def get_collection():
    """Connect to the ChromaDB SERVER (not an embedded file) via HttpClient."""
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return client.get_or_create_collection(name=CHROMA_COLLECTION)


def add_vector(file_id: str, text: str, doc_type: str, user_id: str):
    """Compute a gte-Qwen2 embedding locally, then store it in ChromaDB.

    user_id is saved in the vector's metadata so searches can be filtered to
    only this user's files.
    """
    embeddings = _embed([text], is_query=False)   # document: no prefix
    get_collection().upsert(
        ids=[file_id],
        embeddings=embeddings,
        documents=[text],
        metadatas=[{"doc_type": doc_type or "other", "user_id": user_id}],
    )


def vector_search(question: str, user_id: str, n: int = 3):
    """Return the most semantically similar file_ids OWNED BY user_id."""
    query_embedding = _embed([question], is_query=True)   # query: with prefix
    results = get_collection().query(
        query_embeddings=query_embedding,
        n_results=n,
        where={"user_id": user_id},   # only this user's vectors
    )
    return results["ids"][0]


def vector_search_with_text(question: str, user_id: str, n: int = 3):
    """Like vector_search but also returns the stored narrative text per hit."""
    query_embedding = _embed([question], is_query=True)   # query: with prefix
    results = get_collection().query(
        query_embeddings=query_embedding,
        n_results=n,
        where={"user_id": user_id},
    )
    return list(zip(results["ids"][0], results["documents"][0]))


def vector_search_scored(question: str, user_id: str, n: int = 3):
    """Like vector_search_with_text but ALSO returns each hit's distance.

    Returns a list of (file_id, text, distance), sorted nearest-first (Chroma's
    default). Smaller distance = more similar. Callers use the distance to drop
    weak/irrelevant matches (see RELEVANCE_MAX_DISTANCE).
    """
    query_embedding = _embed([question], is_query=True)   # query: with prefix
    results = get_collection().query(
        query_embeddings=query_embedding,
        n_results=n,
        where={"user_id": user_id},
        include=["documents", "distances"],
    )
    ids = results["ids"][0]
    docs = results["documents"][0]
    dists = results["distances"][0]
    return list(zip(ids, docs, dists))


# --- PostgreSQL: users -----------------------------------------------------

def create_user(email: str, password_hash: str) -> dict:
    """Insert a new user and return the public fields (id, email, created_at)."""
    user_id = str(uuid.uuid4())
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            """
            INSERT INTO users (id, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id, email, created_at
            """,
            (user_id, email, password_hash),
        ).fetchone()
    return {"id": str(row[0]), "email": row[1], "created_at": row[2]}


def get_user_by_email(email: str) -> dict | None:
    """Look up a user for LOGIN — includes password_hash for verification."""
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s",
            (email,),
        ).fetchone()
    if not row:
        return None
    return {"id": str(row[0]), "email": row[1], "password_hash": row[2]}


def get_user_by_id(user_id: str) -> dict | None:
    """Look up a user by id for AUTH checks — no password_hash needed."""
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT id, email FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return {"id": str(row[0]), "email": row[1]}


# --- PostgreSQL: documents -------------------------------------------------

def find_by_hash(file_hash: str, user_id: str) -> str | None:
    """Return existing file_id if THIS USER already ingested this MD5."""
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT file_id FROM documents WHERE file_hash = %s AND user_id = %s",
            (file_hash, user_id),
        ).fetchone()
    return str(row[0]) if row else None


def insert_document(
    file_id: str,
    doc: dict,
    file_path: str,
    file_hash: str | None = None,
    user_id: str | None = None,
):
    """Write fixed columns + the full JSON (JSONB), keyed by file_id."""
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            """
            INSERT INTO documents
                (file_id, doc_type, doc_date, amount, currency,
                 vendor, summary, file_path, full_analysis, file_hash, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                user_id,
            ),
        )


def fetch_by_ids(file_ids):
    """Enrich vector hits with full metadata from PostgreSQL (the join).

    Used by the non-agentic baseline (answer.py); not user-scoped.
    """
    if not file_ids:
        return []
    with psycopg.connect(PG_DSN) as conn:
        return conn.execute(
            "SELECT file_id, doc_type, vendor, summary, amount "
            "FROM documents WHERE file_id = ANY(%s)",
            (list(file_ids),),
        ).fetchall()


def get_document(file_id: str, user_id: str) -> dict | None:
    """Fetch one document INCLUDING its file_path, only if owned by user_id.

    Used by download (needs the path on disk) with an ownership check baked in.
    """
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT file_id, doc_type, vendor, summary, file_path "
            "FROM documents WHERE file_id = %s AND user_id = %s",
            (file_id, user_id),
        ).fetchone()
    if not row:
        return None
    return {
        "file_id": str(row[0]), "doc_type": row[1], "vendor": row[2],
        "summary": row[3], "file_path": row[4],
    }


def get_document_full(file_id: str, user_id: str) -> dict | None:
    """Fetch ALL display fields for the detail modal, including the full JSONB
    analysis (the dynamic `details` layer Claude produced). Ownership-checked.

    Does NOT return file_path (that's an internal disk path; the browser reaches
    the original via the /preview and /download routes instead).
    """
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT file_id, doc_type, doc_date, amount, currency, vendor, "
            "summary, full_analysis, created_at "
            "FROM documents WHERE file_id = %s AND user_id = %s",
            (file_id, user_id),
        ).fetchone()
    if not row:
        return None
    return {
        "file_id": str(row[0]),
        "doc_type": row[1],
        "doc_date": str(row[2]) if row[2] else None,
        "amount": float(row[3]) if row[3] is not None else None,
        "currency": row[4],
        "vendor": row[5],
        "summary": row[6],
        # psycopg returns JSONB already decoded into a Python dict.
        "full_analysis": row[7],
        "created_at": str(row[8]) if row[8] else None,
    }


def get_documents_meta(file_ids: list[str], user_id: str) -> list[dict]:
    """Return display metadata for a set of files (for chat file cards).

    Scoped to user_id, so even if a stray id leaked in it won't expose another
    user's file. NUMERIC/DATE are converted to JSON-friendly types.
    """
    if not file_ids:
        return []
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT file_id, doc_type, vendor, summary, doc_date, amount, currency "
            "FROM documents WHERE file_id = ANY(%s) AND user_id = %s",
            (list(file_ids), user_id),
        ).fetchall()
    return [
        {
            "file_id": str(r[0]), "doc_type": r[1], "vendor": r[2],
            "summary": r[3], "doc_date": str(r[4]) if r[4] else None,
            "amount": float(r[5]) if r[5] is not None else None, "currency": r[6],
        }
        for r in rows
    ]


def delete_document(file_id: str, user_id: str) -> str | None:
    """Delete a file from PG (only if owned) and Chroma.

    Returns the file_path to remove from disk, or None if the file didn't
    exist or wasn't owned by this user (so the route can 404).
    """
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "DELETE FROM documents WHERE file_id = %s AND user_id = %s "
            "RETURNING file_path",
            (file_id, user_id),
        ).fetchone()
    if not row:
        return None
    # Remove the vector too. Ignore errors so a missing vector won't block delete.
    try:
        get_collection().delete(ids=[file_id])
    except Exception:  # noqa: BLE001
        pass
    return row[0]


def run_sql(sql: str, params=()):
    """Run an arbitrary SELECT for exact / range / aggregate queries."""
    with psycopg.connect(PG_DSN) as conn:
        return conn.execute(sql, params).fetchall()


def run_select_safe(sql: str):
    """Read-only guard for SQL coming from the LLM (NOT user-scoped).

    Allows only a single SELECT so a crafted query can't modify or drop data.
    Kept for non-private callers; the agent uses run_select_for_user instead.
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


def run_select_for_user(sql: str, user_id: str):
    """Read-only guard for LLM SQL, scoped to ONE user's rows.

    The trick: we wrap the model's query in a CTE that redefines `documents`
    as only this user's rows. A non-recursive CTE's inner `FROM documents`
    still refers to the real table, while the model's outer `FROM documents`
    binds to the CTE — so any query the model writes is automatically
    restricted to this user, and the model never controls the filter.
    """
    cleaned = sql.strip().rstrip(";").strip()
    lowered = cleaned.lower()
    if not lowered.startswith("select"):
        raise ValueError("只允许 SELECT 查询")
    forbidden = (";", " insert ", " update ", " delete ", " drop ",
                 " alter ", " truncate ", " create ", " grant ", "public.")
    if any(tok in f" {lowered} " for tok in forbidden):
        raise ValueError("查询包含不允许的操作")
    scoped = (
        "WITH documents AS (SELECT * FROM documents WHERE user_id = %s) "
        + cleaned
    )
    with psycopg.connect(PG_DSN) as conn:
        return conn.execute(scoped, (user_id,)).fetchall()


# --- PostgreSQL: conversations & messages ----------------------------------

def create_conversation(user_id: str, title: str | None = None) -> dict:
    """Start a new chat thread owned by user_id."""
    conv_id = str(uuid.uuid4())
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            """
            INSERT INTO conversations (id, user_id, title)
            VALUES (%s, %s, %s)
            RETURNING id, title, created_at
            """,
            (conv_id, user_id, title),
        ).fetchone()
    return {"id": str(row[0]), "title": row[1], "created_at": row[2]}


def list_conversations(user_id: str) -> list[dict]:
    """All of a user's conversations, newest first (for the sidebar)."""
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM conversations "
            "WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [{"id": str(r[0]), "title": r[1], "created_at": r[2]} for r in rows]


def get_conversation(conv_id: str, user_id: str) -> dict | None:
    """Fetch one conversation, but ONLY if it belongs to user_id.

    This is the ownership check: a user must never read someone else's chat.
    """
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT id, title FROM conversations WHERE id = %s AND user_id = %s",
            (conv_id, user_id),
        ).fetchone()
    if not row:
        return None
    return {"id": str(row[0]), "title": row[1]}


def update_conversation_title(conv_id: str, title: str) -> None:
    """Set the title (we use the first question's first ~20 chars)."""
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "UPDATE conversations SET title = %s WHERE id = %s",
            (title, conv_id),
        )


def add_message(conv_id: str, role: str, content: str) -> dict:
    """Append one message (role = 'user' | 'assistant') to a conversation."""
    msg_id = str(uuid.uuid4())
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content)
            VALUES (%s, %s, %s, %s)
            RETURNING id, role, content, created_at
            """,
            (msg_id, conv_id, role, content),
        ).fetchone()
    return {"id": str(row[0]), "role": row[1], "content": row[2], "created_at": row[3]}


def get_messages(conv_id: str) -> list[dict]:
    """All messages in a conversation, oldest first (chat order)."""
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE conversation_id = %s ORDER BY created_at ASC",
            (conv_id,),
        ).fetchall()
    return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]
