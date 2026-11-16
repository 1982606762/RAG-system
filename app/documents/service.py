"""The request owns the complete ingestion lifecycle; there is no task queue."""

import hashlib
import logging
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from core import config
from db import documents as store
from documents.chunking import CHUNKER_VERSION, MAX_CHARS, OVERLAP_CHARS, TARGET_CHARS, chunk_blocks
from documents.models import DocumentError
from documents.parsing import PARSER_VERSION, SUPPORTED_EXTENSIONS, parse_document

logger = logging.getLogger(__name__)


def original_path(document_id, extension):
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentError("invalid_type", "不支持的文件类型。")
    # IDs come from UUID validation or the database, never from a filename.
    return config.DOCUMENTS_DIR / f"{document_id}{extension}"


def process(conn, document_id, path, extension):
    try:
        store.set_stage(conn, document_id, "parsing")
        parsed = parse_document(path, extension)
        parser_version = PARSER_VERSION
        if config.GOOGLE_DOCUMENT_AI_PROCESSOR:
            parser_version = "google-layout-v1"
        store.save_blocks(conn, document_id, parsed, parser_version)
        chunks = chunk_blocks(parsed.blocks)
        store.save_chunks(conn, document_id, chunks, CHUNKER_VERSION,
                          {"unit": "unicode_characters", "target": TARGET_CHARS,
                           "maximum": MAX_CHARS, "overlap": OVERLAP_CHARS})
    except DocumentError as exc:
        store.set_failed(conn, document_id, exc)
    except Exception:
        logger.exception("Document processing failed: %s", document_id)
        store.set_failed(conn, document_id, DocumentError(
            "processing_failed", "文件处理失败。请检查文件是否损坏、加密或格式异常后重试。"))
    return store.get_document(conn, document_id)


def upload_document(upload):
    filename = Path((upload.filename or "").replace("\\", "/")).name
    filename = "".join(char for char in filename if char.isprintable())[:240]
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentError("unsupported_type", "支持 PDF、TXT、Markdown、PNG、JPEG 和 WebP。", 415)
    with store.ingestion_connection() as conn:
        config.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            digest = hashlib.sha256()
            size = 0
            with tempfile.NamedTemporaryFile(dir=config.DOCUMENTS_DIR, prefix=".upload-", delete=False) as temp:
                temp_path = Path(temp.name)
                while data := upload.file.read(1024 * 1024):
                    size += len(data)
                    if size > config.MAX_UPLOAD_BYTES:
                        raise DocumentError("file_too_large", "文件不能超过 20 MiB。", 413)
                    digest.update(data)
                    temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
            if size == 0:
                raise DocumentError("empty_file", "文件为空。")
            existing = store.find_duplicate(conn, digest.hexdigest())
            if existing:
                return {"document": existing, "duplicate": True}
            document_id = uuid4()
            path = original_path(document_id, extension)
            temp_path.replace(path)
            try:
                store.insert_document(conn, document_id, filename, extension, digest.hexdigest(), size)
            except Exception:
                # Retain the original if the DB commit outcome is uncertain.
                logger.exception("Original saved but metadata write failed: %s", document_id)
                raise
            return {"document": process(conn, document_id, path, extension), "duplicate": False}
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)


def retry_document(document_id):
    with store.ingestion_connection() as conn:
        document = store.begin_retry(conn, document_id)
        return process(conn, document_id, original_path(document_id, document["extension"]), document["extension"])
