"""Service layer — reusable business logic shared by the CLI and the API.

Keeping ingestion here means the FastAPI endpoints and the command line call
the exact same code path. Everything is per-user now: ingest writes the owner,
and search/list/delete are scoped to one user.
"""

import hashlib
import os
import uuid

from rag.process import process_file, build_embedding_text
from db.storage import (
    insert_document,
    add_vector,
    run_sql,
    find_by_hash,
    delete_document,
    vector_search_with_text,
    get_documents_meta,
)


def _md5(path: str) -> str:
    """Compute the MD5 hex digest of a file in 8 KB chunks (memory-efficient)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_file(path: str, user_id: str, model: str = None) -> dict:
    """Process one file (owned by user_id) and write it to both stores.

    Dedup is PER-USER: if this user already uploaded the same content (same
    MD5), return the existing record without calling Claude or writing again.
    """
    file_hash = _md5(path)
    existing_id = find_by_hash(file_hash, user_id)
    if existing_id:
        return {"file_id": existing_id, "duplicate": True, "embedding_text": "", "doc": {}}

    doc = process_file(path, model=model)
    if doc.get("_parse_error"):
        raise ValueError(f"Claude 解析失败：{doc.get('_raw')}")

    file_id = str(uuid.uuid4())
    text = build_embedding_text(doc)
    insert_document(file_id, doc, os.path.abspath(path), file_hash, user_id)  # PG
    add_vector(file_id, text, doc.get("doc_type"), user_id)                   # Chroma
    return {"file_id": file_id, "duplicate": False, "embedding_text": text, "doc": doc}


def list_documents(user_id: str, limit: int = 100):
    """Return a user's recent documents for the file list page."""
    rows = run_sql(
        "SELECT file_id, doc_type, doc_date, vendor, amount, currency, "
        "summary, created_at FROM documents WHERE user_id = %s "
        "ORDER BY created_at DESC LIMIT %s",
        (user_id, limit),
    )
    keys = ["file_id", "doc_type", "doc_date", "vendor", "amount",
            "currency", "summary", "created_at"]
    return [dict(zip(keys, r)) for r in rows]


def delete_file(file_id: str, user_id: str) -> bool:
    """Delete a file from PG + Chroma + disk. Returns False if not found/owned."""
    path = delete_document(file_id, user_id)   # PG row + vector; None if not owned
    if path is None:
        return False
    try:
        if path and os.path.exists(path):
            os.remove(path)                    # remove the original from disk
    except OSError:
        pass                                   # best-effort; the row is already gone
    return True


def semantic_search(question: str, user_id: str, n: int = 5) -> list[dict]:
    """Natural-language file search: vector recall -> file metadata cards."""
    hits = vector_search_with_text(question, user_id, n=n)
    file_ids = [fid for fid, _text in hits]
    return get_documents_meta(file_ids, user_id)
