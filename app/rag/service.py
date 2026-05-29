"""Service layer — reusable business logic shared by the CLI and the API.

Keeping ingestion here means the FastAPI endpoints and the command line call
the exact same code path.
"""

import os
import uuid

from rag.process import process_image, build_embedding_text
from db.storage import insert_document, add_vector, run_sql


def ingest_file(path: str) -> dict:
    """Process one file and write it to both stores. Returns a summary dict."""
    doc = process_image(path)
    if doc.get("_parse_error"):
        raise ValueError(f"Claude 解析失败：{doc.get('_raw')}")

    file_id = str(uuid.uuid4())
    text = build_embedding_text(doc)
    insert_document(file_id, doc, os.path.abspath(path))   # PostgreSQL
    add_vector(file_id, text, doc.get("doc_type"))         # ChromaDB
    return {"file_id": file_id, "embedding_text": text, "doc": doc}


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
