"""Service layer — reusable business logic shared by the CLI and the API.

Keeping ingestion here means the FastAPI endpoints and the command line call
the exact same code path.
"""

import hashlib
import os
import uuid

from rag.process import process_file, build_embedding_text
from db.storage import insert_document, add_vector, run_sql, find_by_hash


def _md5(path: str) -> str:
    """Compute the MD5 hex digest of a file in 8 KB chunks (memory-efficient)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_file(path: str, model: str = None) -> dict:
    """Process one file and write it to both stores. Returns a summary dict.

    If the same file content was uploaded before (same MD5), returns the
    existing record without calling Claude or writing anything new.
    """
    file_hash = _md5(path)
    existing_id = find_by_hash(file_hash)
    if existing_id:
        return {"file_id": existing_id, "duplicate": True, "embedding_text": "", "doc": {}}

    doc = process_file(path, model=model)
    if doc.get("_parse_error"):
        raise ValueError(f"Claude 解析失败：{doc.get('_raw')}")

    file_id = str(uuid.uuid4())
    text = build_embedding_text(doc)
    insert_document(file_id, doc, os.path.abspath(path), file_hash)  # PostgreSQL
    add_vector(file_id, text, doc.get("doc_type"))                   # ChromaDB
    return {"file_id": file_id, "duplicate": False, "embedding_text": text, "doc": doc}


def list_documents(limit: int = 100):
    """Return recent documents for the file list page."""
    rows = run_sql(
        "SELECT file_id, doc_type, doc_date, vendor, amount, currency, "
        "summary, created_at FROM documents ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
    keys = ["file_id", "doc_type", "doc_date", "vendor", "amount",
            "currency", "summary", "created_at"]
    return [dict(zip(keys, r)) for r in rows]
