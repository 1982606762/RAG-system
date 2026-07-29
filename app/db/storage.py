"""Storage layer — thin helpers over PostgreSQL and the ChromaDB service.

Both stores are linked by file_id (a UUID). ChromaDB finds *which* file is
relevant; PostgreSQL holds the full structured metadata for that file.

Privacy model: every file belongs to a user. Vector hits are filtered by a
user_id stored in Chroma metadata; exact agent queries are built from a small
allow-list and always include user_id. So users cannot query each other's files.
"""

import json
import uuid
from functools import lru_cache
from typing import Any

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


# --- multilingual-e5 Embedding (local, computed by this process) ------------
#
# E5 uses an instruction prefix to distinguish query vs. document:
#   - documents (stored): encoded as plain text, no prefix needed
#   - queries   (search): must be prefixed with the instruction string below
#
# Dimension: 768  |  Max tokens: 512

_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "


@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    # Loaded once on first call; subsequent calls return the cached instance.
    return SentenceTransformer(EMBED_MODEL)


def _embed(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """Return L2-normalised 768-dim embeddings for a list of texts.

    is_query=True  -> prepend "query: "   (used at search time)
    is_query=False -> prepend "passage: " (used at ingest time)
    """
    prefix = _QUERY_PREFIX if is_query else _PASSAGE_PREFIX
    texts = [prefix + t for t in texts]
    return _get_embedder().encode(texts, normalize_embeddings=True).tolist()


# --- ChromaDB (vector store, a remote service) -----------------------------

def get_collection():
    """Connect to the ChromaDB SERVER (not an embedded file) via HttpClient."""
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return client.get_or_create_collection(name=CHROMA_COLLECTION)


def add_vector(file_id: str, text: str, doc_type: str, user_id: str):
    """Compute a multilingual-e5 embedding locally, then store it in ChromaDB.

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
    email = email.strip().lower()
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
    email = email.strip().lower()
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
    documents = [
        {
            "file_id": str(r[0]), "doc_type": r[1], "vendor": r[2],
            "summary": r[3], "doc_date": str(r[4]) if r[4] else None,
            "amount": float(r[5]) if r[5] is not None else None, "currency": r[6],
        }
        for r in rows
    ]
    order = {file_id: index for index, file_id in enumerate(file_ids)}
    documents.sort(key=lambda item: order.get(item["file_id"], len(order)))
    return documents


def delete_document(file_id: str, user_id: str) -> str | None:
    """Delete a file from Chroma and then PG, only if owned.

    Returns the file_path to remove from disk, or None if the file didn't
    exist or wasn't owned by this user (so the route can 404).

    Chroma is deleted first. If it is temporarily unavailable we keep the PG
    row and original file, so the user can retry instead of being told a
    successful delete while private content remains in the vector store.
    """
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT file_path FROM documents WHERE file_id = %s AND user_id = %s",
            (file_id, user_id),
        ).fetchone()
    if not row:
        return None
    get_collection().delete(ids=[file_id])
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "DELETE FROM documents WHERE file_id = %s AND user_id = %s",
            (file_id, user_id),
        )
    return row[0]


def rollback_document(file_id: str, user_id: str) -> None:
    """Best-effort compensation for a partially completed ingest."""
    try:
        get_collection().delete(ids=[file_id])
    except Exception:  # noqa: BLE001
        pass
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "DELETE FROM documents WHERE file_id = %s AND user_id = %s",
            (file_id, user_id),
        )


def run_sql(sql: str, params=()):
    """Run an arbitrary SELECT for exact / range / aggregate queries."""
    with psycopg.connect(PG_DSN) as conn:
        return conn.execute(sql, params).fetchall()


def run_select_safe(sql: str):
    """Read-only guard for SQL coming from the LLM (NOT user-scoped).

    Allows only a single SELECT so a crafted query can't modify or drop data.
    Kept for trusted admin/debug callers; the agent never uses raw SQL.
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


def structured_document_search(user_id: str, filters: dict[str, Any]) -> dict:
    """Run the agent's exact search without executing model-authored SQL.

    Every selectable column, operator and sort expression comes from a local
    allow-list. The model controls values only, and values are bound as query
    parameters, so it cannot read another table or escape the user_id filter.
    """
    mode = filters.get("mode", "rows")
    if mode not in {"rows", "count", "sum_amount"}:
        raise ValueError("不支持的查询模式")

    where = ["user_id = %s"]
    params: list[Any] = [user_id]

    exact_fields = {
        "doc_type": "doc_type",
        "currency": "currency",
    }
    for key, column in exact_fields.items():
        value = filters.get(key)
        if value:
            where.append(f"{column} = %s")
            params.append(value)

    vendor = filters.get("vendor_contains")
    if vendor:
        where.append("vendor ILIKE %s")
        params.append(f"%{vendor}%")

    range_fields = {
        "date_from": ("doc_date", ">="),
        "date_to": ("doc_date", "<="),
        "amount_min": ("amount", ">="),
        "amount_max": ("amount", "<="),
    }
    for key, (column, operator) in range_fields.items():
        value = filters.get(key)
        if value is not None:
            where.append(f"{column} {operator} %s")
            params.append(value)

    if mode == "count":
        select = "COUNT(*)"
    elif mode == "sum_amount":
        select = "COALESCE(SUM(amount), 0)"
    else:
        select = (
            "file_id, doc_type, doc_date, amount, currency, vendor, summary, created_at"
        )

    query = f"SELECT {select} FROM documents WHERE {' AND '.join(where)}"
    if mode == "rows":
        order_columns = {
            "created_at": "created_at",
            "doc_date": "doc_date",
            "amount": "amount",
        }
        order_by = order_columns.get(filters.get("order_by"), "created_at")
        direction = "ASC" if filters.get("order") == "asc" else "DESC"
        limit = max(1, min(int(filters.get("limit", 20)), 100))
        query += f" ORDER BY {order_by} {direction} NULLS LAST LIMIT %s"
        params.append(limit)

    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(query, params).fetchall()

    if mode != "rows":
        value = rows[0][0] if rows else 0
        if mode == "count":
            value = int(value or 0)
        else:
            value = float(value or 0)
        return {"mode": mode, "value": value}

    keys = [
        "file_id", "doc_type", "doc_date", "amount", "currency",
        "vendor", "summary", "created_at",
    ]
    return {
        "mode": mode,
        "rows": [
            {
                key: (
                    str(value)
                    if key in {"file_id", "doc_date", "created_at"} and value is not None
                    else float(value)
                    if key == "amount" and value is not None
                    else value
                )
                for key, value in zip(keys, row)
            }
            for row in rows
        ],
    }


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
            "WHERE user_id = %s ORDER BY created_at DESC LIMIT 200",
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
    """The latest 200 messages in a conversation, oldest first."""
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM ("
            "SELECT role, content, created_at FROM messages "
            "WHERE conversation_id = %s ORDER BY created_at DESC LIMIT 200"
            ") recent ORDER BY created_at ASC",
            (conv_id,),
        ).fetchall()
    return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]


# --- PostgreSQL: agent traces (observability) ------------------------------

def save_trace(user_id: str, trace: dict, conversation_id: str = None) -> None:
    """Persist one agent run's trace. Best-effort: callers wrap this so that a
    failure to record observability never breaks the actual answer."""
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            """
            INSERT INTO agent_traces
                (id, user_id, conversation_id, question, answer, model,
                 input_tokens, output_tokens, cost_usd, tool_calls,
                 num_turns, duration_ms, status, error, steps)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                conversation_id,
                trace.get("question"),
                trace.get("answer"),
                trace.get("model"),
                trace.get("input_tokens"),
                trace.get("output_tokens"),
                trace.get("cost_usd"),
                trace.get("tool_calls"),
                trace.get("num_turns"),
                trace.get("duration_ms"),
                trace.get("status"),
                trace.get("error"),
                json.dumps(trace.get("steps") or [], ensure_ascii=False),
            ),
        )


def list_traces(user_id: str, limit: int = 50) -> list[dict]:
    """Recent traces for the list view (no steps — keep the payload small)."""
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT id, question, model, cost_usd, tool_calls, num_turns, "
            "duration_ms, status, created_at FROM agent_traces "
            "WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()
    keys = ["id", "question", "model", "cost_usd", "tool_calls", "num_turns",
            "duration_ms", "status", "created_at"]
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["id"] = str(d["id"])
        d["cost_usd"] = float(d["cost_usd"]) if d["cost_usd"] is not None else None
        d["created_at"] = str(d["created_at"]) if d["created_at"] else None
        out.append(d)
    return out


def get_trace(trace_id: str, user_id: str) -> dict | None:
    """One full trace incl. the step timeline, for the detail view. Owner-scoped."""
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT id, question, answer, model, input_tokens, output_tokens, "
            "cost_usd, tool_calls, num_turns, duration_ms, status, error, "
            "steps, created_at FROM agent_traces "
            "WHERE id = %s AND user_id = %s",
            (trace_id, user_id),
        ).fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]), "question": row[1], "answer": row[2], "model": row[3],
        "input_tokens": row[4], "output_tokens": row[5],
        "cost_usd": float(row[6]) if row[6] is not None else None,
        "tool_calls": row[7], "num_turns": row[8], "duration_ms": row[9],
        "status": row[10], "error": row[11],
        "steps": row[12],   # JSONB -> already a Python list
        "created_at": str(row[13]) if row[13] else None,
    }
