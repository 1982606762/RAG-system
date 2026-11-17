"""Synchronous, resumable vectorization over existing chunks; never reparse originals."""

from collections import deque
import hashlib
import logging
import time

from core import config
from db import documents, embeddings as store
from documents.models import DocumentError
from embeddings.provider import InputTooLong, VertexEmbedder, active_profile

logger = logging.getLogger(__name__)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def make_part(chunk, start, end):
    text = chunk['text'][start:end]
    sources = []
    cursor = 0
    for source in chunk['sources']:
        length = source['end'] - source['start']
        left, right = max(start, cursor), min(end, cursor + length)
        if left < right:
            sources.append({**source, 'start': source['start'] + left - cursor,
                            'end': source['start'] + right - cursor})
        cursor += length + 2  # chunk_blocks joins source spans with two newlines.
    return {'start_char': start, 'end_char': end, 'chunk_hash': digest(chunk['text']),
            'input_hash': digest(text), 'data': {'text': text, 'sources': sources}, 'complete': False}


def valid_parts(parts, chunk):
    cursor = 0
    for part in parts:
        if (part['start_char'] != cursor or part['end_char'] <= cursor or part['end_char'] > len(chunk['text'])
                or part['chunk_hash'] != digest(chunk['text'])
                or part['input_hash'] != digest(chunk['text'][cursor:part['end_char']])):
            return False
        expected = make_part(chunk, cursor, part['end_char'])
        if part['data'] != expected['data']:
            return False
        cursor = part['end_char']
    return bool(parts) and cursor == len(chunk['text'])


def index_document(conn, document_id, budget_seconds=None):
    """Caller holds the shared ingestion lock, including during cloud requests."""
    profile = active_profile()
    if profile is None:
        raise DocumentError('embedding_not_configured', '请先配置 Vertex AI embedding 项目及 ADC 凭据。', 503)
    doc = documents.get_document(conn, document_id)
    if doc['status'] != 'ready':
        raise DocumentError('document_not_ready', '请先完成文档解析和分块。', 409)
    chunks = [row['data'] for row in conn.execute(
        'SELECT data FROM knowledge_base_v1.chunks WHERE document_id=%s ORDER BY chunk_index', (document_id,))]
    if not chunks:
        raise DocumentError('no_chunks', '文档还没有可生成向量的片段。', 409)
    deadline = time.monotonic() + (config.EMBEDDING_BUDGET_SECONDS if budget_seconds is None else budget_seconds)
    store.start(conn, document_id, profile, len(chunks))
    try:
        pending = deque()
        for chunk in chunks:
            saved = store.parts(conn, document_id, chunk['index'], profile)
            if not valid_parts(saved, chunk):
                part = make_part(chunk, 0, len(chunk['text']))
                store.reset_parts(conn, document_id, chunk['index'], profile, part)
                saved = [part]
            pending.extend((chunk, part) for part in saved if not part['complete'])
        store.progress(conn, document_id, profile)
        # A second invocation with unchanged inputs does not even refresh ADC.
        if pending:
            with VertexEmbedder(profile, deadline) as provider:
                while pending:
                    if time.monotonic() >= deadline:
                        raise DocumentError('embedding_timeout', '向量化时间预算已用完，已保存的进度可继续处理。', 504)
                    chunk, part = pending.popleft()
                    try:
                        vector, count = provider.embed(part['data']['text'])
                    except InputTooLong:
                        start, end = part['start_char'], part['end_char']
                        if end - start < 2:
                            raise DocumentError('embedding_input', '这个片段无法在模型 token 限制内生成向量。', 422)
                        middle = (start + end) // 2
                        children = [make_part(chunk, start, middle), make_part(chunk, middle, end)]
                        store.split_part(conn, document_id, chunk['index'], profile, part, children)
                        pending.extendleft((chunk, child) for child in reversed(children))
                        continue
                    store.save_vector(conn, document_id, chunk['index'], profile, part, vector, count)
                    store.progress(conn, document_id, profile)
        store.progress(conn, document_id, profile, 'ready')
    except DocumentError as exc:
        store.progress(conn, document_id, profile, 'failed', exc)
    except Exception:
        logger.exception('Embedding failed for document %s', document_id)
        store.progress(conn, document_id, profile, 'failed', DocumentError(
            'embedding_failed', '向量化未完成，文档仍可阅读；可继续已保存的进度。', 503))
    return documents.get_document(conn, document_id)


def retry_embeddings(document_id):
    with documents.ingestion_connection() as conn:
        return index_document(conn, document_id)


def backfill(limit=100, document_id=None):
    results = []
    with documents.ingestion_connection() as conn:
        if document_id:
            ids = [document_id]
        else:
            ids = [row['id'] for row in conn.execute("""SELECT id FROM knowledge_base_v1.documents
                WHERE status='ready' ORDER BY created_at,id LIMIT %s""", (limit,))]
        for identifier in ids:
            results.append(index_document(conn, identifier, budget_seconds=120))
    return results
