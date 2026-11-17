"""Checkpoint embedding parts without keeping transactions open across cloud calls."""

from psycopg.types.json import Jsonb

from documents.models import DocumentError
from embeddings.provider import DIMENSIONS, active_profile


def attach_status(conn, documents):
    profile = active_profile()
    runs = {}
    if profile and documents:
        runs = {row['document_id']: row for row in conn.execute(
            "SELECT * FROM knowledge_base_v1.embedding_runs WHERE profile=%s AND document_id=ANY(%s::uuid[])",
            (profile.key, [doc['id'] for doc in documents]))}
    for doc in documents:
        run = runs.get(doc['id'])
        doc['embedding'] = {
            'status': run['status'] if run else 'pending' if profile else 'disabled',
            'model': profile.resource if profile else None, 'dimensions': DIMENSIONS,
            'completed_chunks': run['completed_chunks'] if run else 0,
            'total_chunks': doc['chunk_count'], 'vector_count': run['vector_count'] if run else 0,
            'error_code': run['error_code'] if run else None,
            'error_message': run['error_message'] if run else None,
        }


def start(conn, document_id, profile, total):
    conn.execute("""INSERT INTO knowledge_base_v1.embedding_runs
        (document_id,profile,model_resource,dimensions,status,total_chunks)
        VALUES (%s,%s,%s,%s,'processing',%s)
        ON CONFLICT (document_id,profile) DO UPDATE SET status='processing',total_chunks=excluded.total_chunks,
            error_code=NULL,error_message=NULL,updated_at=now()""",
        (document_id, profile.key, profile.resource, DIMENSIONS, total))


def progress(conn, document_id, profile, status='processing', error=None):
    conn.execute("""UPDATE knowledge_base_v1.embedding_runs SET
        completed_chunks=(SELECT count(*) FROM (
            SELECT chunk_index FROM knowledge_base_v1.embedding_parts
            WHERE document_id=%s AND profile=%s GROUP BY chunk_index HAVING bool_and(embedding IS NOT NULL)
        ) completed),
        vector_count=(SELECT count(*) FROM knowledge_base_v1.embedding_parts
            WHERE document_id=%s AND profile=%s AND embedding IS NOT NULL),
        status=%s,error_code=%s,error_message=%s,updated_at=now()
        WHERE document_id=%s AND profile=%s""",
        (document_id, profile.key, document_id, profile.key, status,
         error.code if error else None, str(error) if error else None, document_id, profile.key))


def parts(conn, document_id, chunk_index, profile):
    return conn.execute("""SELECT start_char,end_char,chunk_hash,input_hash,data,
        embedding IS NOT NULL AS complete FROM knowledge_base_v1.embedding_parts
        WHERE document_id=%s AND chunk_index=%s AND profile=%s ORDER BY start_char""",
        (document_id, chunk_index, profile.key)).fetchall()


def insert_part(conn, document_id, chunk_index, profile, part):
    conn.execute("""INSERT INTO knowledge_base_v1.embedding_parts
        (document_id,chunk_index,profile,start_char,end_char,chunk_hash,input_hash,data)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (document_id, chunk_index, profile.key, part['start_char'], part['end_char'],
         part['chunk_hash'], part['input_hash'], Jsonb(part['data'])))


def reset_parts(conn, document_id, chunk_index, profile, part):
    with conn.transaction():
        conn.execute("DELETE FROM knowledge_base_v1.embedding_parts WHERE document_id=%s AND chunk_index=%s AND profile=%s",
                     (document_id, chunk_index, profile.key))
        insert_part(conn, document_id, chunk_index, profile, part)


def split_part(conn, document_id, chunk_index, profile, parent, children):
    with conn.transaction():
        changed = conn.execute("""DELETE FROM knowledge_base_v1.embedding_parts
            WHERE document_id=%s AND chunk_index=%s AND profile=%s AND start_char=%s AND end_char=%s
                AND chunk_hash=%s AND embedding IS NULL""",
            (document_id, chunk_index, profile.key, parent['start_char'], parent['end_char'], parent['chunk_hash']))
        if changed.rowcount != 1:
            raise DocumentError('embedding_stale', '片段已改变，请刷新后继续生成向量。', 409)
        for child in children:
            insert_part(conn, document_id, chunk_index, profile, child)


def save_vector(conn, document_id, chunk_index, profile, part, vector, token_count):
    # Values have been validated and normalized by the provider boundary; use a
    # bound text parameter with an explicit cast, requiring no pgvector driver.
    value = '[' + ','.join(repr(number) for number in vector) + ']'
    changed = conn.execute("""UPDATE knowledge_base_v1.embedding_parts SET embedding=%s::vector,token_count=%s
        WHERE document_id=%s AND chunk_index=%s AND profile=%s AND start_char=%s AND end_char=%s
            AND chunk_hash=%s AND input_hash=%s AND embedding IS NULL""",
        (value, token_count, document_id, chunk_index, profile.key, part['start_char'], part['end_char'],
         part['chunk_hash'], part['input_hash']))
    if changed.rowcount != 1:
        raise DocumentError('embedding_stale', '片段已改变，请刷新后继续生成向量。', 409)
