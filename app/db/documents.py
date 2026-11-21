"""Document persistence; no queries touch the legacy public schema."""

from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core import config
from documents.models import DocumentError

INGEST_LOCK = 731982461


def connect():
    return psycopg.connect(config.PG_DSN, connect_timeout=5, autocommit=True,
                           row_factory=dict_row, options="-c statement_timeout=15000")


def initialize():
    with connect() as conn, conn.transaction():
        for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
            conn.execute(path.read_text())


def _recover(conn):
    conn.execute("""UPDATE knowledge_base_v1.documents
        SET status='failed', error_code='interrupted',
            error_message='上次处理已中断，请手动重试。', updated_at=now()
        WHERE status='processing'""")
    conn.execute("""UPDATE knowledge_base_v1.embedding_runs SET status='failed',
        error_code='embedding_interrupted',error_message='上次向量化已中断，可继续处理已保存的进度。',updated_at=now()
        WHERE status='processing'""")


@contextmanager
def ingestion_connection():
    # A session advisory lock serializes ingestion across API threads/processes.
    # The connection stays open, but no transaction stays open during parsing.
    with connect() as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (INGEST_LOCK,)).fetchone()["acquired"]:
            raise DocumentError("busy", "已有文件正在处理，请稍后重试。", 409)
        try:
            _recover(conn)
            yield conn
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (INGEST_LOCK,))


def recover_if_idle(conn):
    if conn.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (INGEST_LOCK,)).fetchone()["acquired"]:
        try:
            _recover(conn)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (INGEST_LOCK,))


def list_documents(limit: int, offset: int):
    with connect() as conn:
        recover_if_idle(conn)
        rows = conn.execute("""SELECT * FROM knowledge_base_v1.documents
            ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s""", (limit, offset)).fetchall()
        total = conn.execute("SELECT count(*) AS total FROM knowledge_base_v1.documents").fetchone()["total"]
        from db.embeddings import attach_status
        attach_status(conn, rows)
        return {"items": rows, "total": total}


def search_chunks(query: str, limit: int, offset: int, *, document_id=None):
    query = query.strip()
    terms = list(dict.fromkeys(query.split()))
    if not terms or len(terms) > 10 or '\x00' in query:
        raise DocumentError("invalid_query", "请输入 1–10 个以空格分隔的关键词。", 422)
    # Literal substring matching supports Chinese and treats %, _ and SQL text as data.
    # Only completed documents are visible, including while another document is retried.
    with connect() as conn:
        rows = conn.execute("""SELECT d.id AS document_id, d.filename,
                c.chunk_index, c.data AS chunk
            FROM knowledge_base_v1.chunks c
            JOIN knowledge_base_v1.documents d ON d.id=c.document_id
            WHERE d.status='ready' AND (%s::uuid IS NULL OR d.id=%s::uuid) AND NOT EXISTS (
                SELECT 1 FROM unnest(%s::text[]) AS terms(term)
                WHERE strpos(lower(c.data->>'text'), lower(term))=0
            )
            ORDER BY (strpos(lower(c.data->>'text'), lower(%s)) > 0) DESC,
                d.created_at DESC, d.id, c.chunk_index
            LIMIT %s OFFSET %s""", (document_id, document_id, terms, query, limit + 1, offset)).fetchall()
    return {"items": rows[:limit], "has_more": len(rows) > limit}


def search_chunk_variants(variants, limit, offset, *, document_id=None):
    """OR query alternatives, AND terms within each; paginate unique chunks in SQL."""
    if not isinstance(variants, list) or not 1 <= len(variants) <= 10 or any(
        not isinstance(query, str) or not 1 <= len(query.strip()) <= 200
        or len(query.split()) > 10 or '\x00' in query for query in variants
    ):
        raise DocumentError('invalid_query', '多语言检索词无效。', 422)
    variants = list(dict.fromkeys(' '.join(query.split()) for query in variants))
    with connect() as conn:
        rows = conn.execute("""WITH queries AS (
                SELECT query, string_to_array(query, ' ') AS terms FROM unnest(%s::text[]) AS q(query)
            )
            SELECT d.id AS document_id, d.filename, c.chunk_index, c.data AS chunk
            FROM knowledge_base_v1.chunks c
            JOIN knowledge_base_v1.documents d ON d.id=c.document_id
            CROSS JOIN LATERAL (
                SELECT max((strpos(lower(c.data->>'text'), lower(q.query)) > 0)::int) AS phrase_match
                FROM queries q WHERE NOT EXISTS (
                    SELECT 1 FROM unnest(q.terms) AS t(term)
                    WHERE strpos(lower(c.data->>'text'), lower(term))=0
                )
            ) matches
            WHERE d.status='ready' AND (%s::uuid IS NULL OR d.id=%s::uuid)
                AND matches.phrase_match IS NOT NULL
            ORDER BY matches.phrase_match DESC, d.created_at DESC, d.id, c.chunk_index
            LIMIT %s OFFSET %s""", (variants, document_id, document_id, limit + 1, offset)).fetchall()
    return {'items': rows[:limit], 'has_more': len(rows) > limit}


def read_chunk_context(hit):
    """Return the anchor and its immediate neighbors from the same document version."""
    with connect() as conn:
        return conn.execute("""SELECT d.id AS document_id, d.filename, c.chunk_index, c.data AS chunk
            FROM knowledge_base_v1.chunks anchor
            JOIN knowledge_base_v1.documents d ON d.id=anchor.document_id
            JOIN knowledge_base_v1.chunks c ON c.document_id=anchor.document_id
                AND c.chunk_index BETWEEN anchor.chunk_index - 1 AND anchor.chunk_index + 1
            WHERE d.status='ready' AND anchor.document_id=%s AND anchor.chunk_index=%s AND anchor.data=%s
            ORDER BY c.chunk_index""",
            (hit["document_id"], hit["chunk_index"], Jsonb(hit["chunk"]))).fetchall()


def read_short_document_context(hit):
    """Keep short agreements complete without expanding large files or stale anchors."""
    with connect() as conn:
        return conn.execute("""SELECT d.id AS document_id, d.filename, c.chunk_index, c.data AS chunk
            FROM knowledge_base_v1.chunks anchor
            JOIN knowledge_base_v1.documents d ON d.id=anchor.document_id
            JOIN knowledge_base_v1.chunks c ON c.document_id=anchor.document_id
            WHERE d.status='ready' AND d.chunk_count BETWEEN 1 AND 8
                AND anchor.document_id=%s AND anchor.chunk_index=%s AND anchor.data=%s
            ORDER BY c.chunk_index""",
            (hit["document_id"], hit["chunk_index"], Jsonb(hit["chunk"]))).fetchall()


def get_document(conn, document_id):
    row = conn.execute("SELECT * FROM knowledge_base_v1.documents WHERE id=%s", (document_id,)).fetchone()
    if row is None:
        raise DocumentError("not_found", "找不到这份文件。", 404)
    from db.embeddings import attach_status
    attach_status(conn, [row])
    return row


def invalidate_embeddings(conn, document_id, total=0):
    conn.execute("""UPDATE knowledge_base_v1.embedding_runs SET status='pending',completed_chunks=0,
        total_chunks=%s,vector_count=0,error_code=NULL,error_message=NULL,updated_at=now()
        WHERE document_id=%s""", (total, document_id))


def get_detail(document_id):
    with connect() as conn:
        recover_if_idle(conn)
        # One snapshot prevents a retry from mixing document metadata and blocks.
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            doc = get_document(conn, document_id)
            doc["blocks"] = [row["data"] for row in conn.execute(
                "SELECT data FROM knowledge_base_v1.blocks WHERE document_id=%s ORDER BY block_index", (document_id,))]
            doc["chunks"] = [row["data"] for row in conn.execute(
                "SELECT data FROM knowledge_base_v1.chunks WHERE document_id=%s ORDER BY chunk_index", (document_id,))]
            return doc


def find_duplicate(conn, content_hash):
    return conn.execute("SELECT * FROM knowledge_base_v1.documents WHERE content_hash=%s", (content_hash,)).fetchone()


def insert_document(conn, document_id, filename, extension, content_hash, size):
    conn.execute("""INSERT INTO knowledge_base_v1.documents
        (id,filename,extension,content_hash,size_bytes,status) VALUES (%s,%s,%s,%s,%s,'processing')""",
                 (document_id, filename, extension, content_hash, size))


def set_stage(conn, document_id, stage):
    conn.execute("UPDATE knowledge_base_v1.documents SET stage=%s,updated_at=now() WHERE id=%s", (stage, document_id))


def set_failed(conn, document_id, error):
    conn.execute("""UPDATE knowledge_base_v1.documents SET status='failed',error_code=%s,
        error_message=%s,updated_at=now() WHERE id=%s""", (error.code, str(error), document_id))


def save_blocks(conn, document_id, parsed, parser_version):
    with conn.transaction():
        conn.execute("DELETE FROM knowledge_base_v1.chunks WHERE document_id=%s", (document_id,))
        invalidate_embeddings(conn, document_id)
        conn.execute("DELETE FROM knowledge_base_v1.blocks WHERE document_id=%s", (document_id,))
        with conn.cursor() as cursor:
            cursor.executemany("INSERT INTO knowledge_base_v1.blocks VALUES (%s,%s,%s)",
                               [(document_id, block.index, Jsonb(block.to_dict())) for block in parsed.blocks])
        conn.execute("""UPDATE knowledge_base_v1.documents SET page_count=%s,block_count=%s,
            chunk_count=0,warnings=%s,parser_version=%s,stage='chunking',updated_at=now() WHERE id=%s""",
                     (parsed.page_count, len(parsed.blocks), Jsonb(parsed.warnings), parser_version, document_id))


def save_chunks(conn, document_id, chunks, chunker_version, chunk_config):
    with conn.transaction():
        conn.execute("DELETE FROM knowledge_base_v1.chunks WHERE document_id=%s", (document_id,))
        invalidate_embeddings(conn, document_id, len(chunks))
        with conn.cursor() as cursor:
            cursor.executemany("INSERT INTO knowledge_base_v1.chunks VALUES (%s,%s,%s)",
                               [(document_id, chunk.index, Jsonb(chunk.to_dict())) for chunk in chunks])
        conn.execute("""UPDATE knowledge_base_v1.documents SET status='ready',stage='complete',
            error_code=NULL,error_message=NULL,chunk_count=%s,chunker_version=%s,
            chunk_config=%s,updated_at=now() WHERE id=%s""",
                     (len(chunks), chunker_version, Jsonb(chunk_config), document_id))


def begin_retry(conn, document_id):
    row = get_document(conn, document_id)
    if row["status"] != "failed":
        raise DocumentError("not_failed", "只有处理失败的文件需要重试。", 409)
    with conn.transaction():
        conn.execute("DELETE FROM knowledge_base_v1.chunks WHERE document_id=%s", (document_id,))
        invalidate_embeddings(conn, document_id)
        conn.execute("DELETE FROM knowledge_base_v1.blocks WHERE document_id=%s", (document_id,))
        conn.execute("""UPDATE knowledge_base_v1.documents SET status='processing',stage='saved',
            error_code=NULL,error_message=NULL,block_count=0,chunk_count=0,page_count=NULL,
            warnings='[]',parser_version=NULL,chunker_version=NULL,chunk_config='{}',updated_at=now() WHERE id=%s""", (document_id,))
    return row
