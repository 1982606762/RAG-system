"""Opt-in pgvector tests with fake cloud responses, never real user documents."""

import hashlib
from contextlib import redirect_stdout
from io import StringIO
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_shell import app, PASSWORD
from fastapi.testclient import TestClient
from core import config
from db import documents as store
from documents.models import Block, Chunk, DocumentError, ParsedDocument
from embeddings.provider import InputTooLong, active_profile
from embeddings.retrieval import semantic_search
from embeddings.service import index_document

VECTOR = [1.0] + [0.0] * 767
ORTHOGONAL_VECTOR = [0.0, 1.0] + [0.0] * 766


@unittest.skipUnless(os.getenv('RAG_TEST_PG_DSN'), 'Set RAG_TEST_PG_DSN to test pgvector integration')
class EmbeddingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(config, 'PG_DSN', os.environ['RAG_TEST_PG_DSN']))
        self.enterContext(patch.object(config, 'VERTEX_EMBEDDING_PROJECT', 'embedding-test'))
        self.enterContext(patch.object(config, 'GOOGLE_DOCUMENT_AI_PROCESSOR', ''))
        if os.getenv('RAG_TEST_DB_FLAVOR') == 'pglite':
            native = store.connect
            def connect():
                connection = native()
                connection.prepare_threshold = None
                return connection
            self.enterContext(patch.object(store, 'connect', connect))
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(config, 'DOCUMENTS_DIR', self.directory))
        store.initialize()
        self.ids = []
        self.client = self.enterContext(TestClient(app))
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        self.headers = {'Authorization': f'Bearer {token}'}

    def tearDown(self):
        with store.connect() as conn:
            for identifier in self.ids:
                conn.execute('DELETE FROM knowledge_base_v1.documents WHERE id=%s', (identifier,))

    def create(self, texts):
        identifier = uuid4()
        self.ids.append(identifier)
        with store.ingestion_connection() as conn:
            store.insert_document(conn, identifier, 'fixture.txt', '.txt', str(identifier), 1)
            blocks = [Block(i, 'paragraph', text) for i, text in enumerate(texts)]
            store.save_blocks(conn, identifier, ParsedDocument(blocks), 'test')
            chunks = [Chunk(i, text, [], [{'block_index': i, 'page': None, 'start': 0, 'end': len(text)}]) for i, text in enumerate(texts)]
            store.save_chunks(conn, identifier, chunks, 'test', {})
        return identifier

    def index(self, identifier, responses=None):
        with patch('embeddings.service.VertexEmbedder') as provider, store.ingestion_connection() as conn:
            provider.return_value.__enter__.return_value.embed.side_effect = responses
            provider.return_value.__enter__.return_value.embed.return_value = (VECTOR, 10)
            result = index_document(conn, identifier)
            return result, provider

    def test_partial_failure_preserves_readiness_and_retry_skips_saved_vectors(self):
        identifier = self.create(['first', 'second', 'third'])
        result, _ = self.index(identifier, [(VECTOR, 10), DocumentError('embedding_quota', 'Quota reached', 503)])
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['embedding']['status'], 'failed')
        self.assertEqual(result['embedding']['completed_chunks'], 1)
        self.assertEqual(result['embedding']['vector_count'], 1)
        self.assertIn(identifier, [hit['document_id'] for hit in store.search_chunks('first', 50, 0)['items']])
        result, provider = self.index(identifier)
        self.assertEqual(result['embedding']['status'], 'ready')
        self.assertEqual(provider.return_value.__enter__.return_value.embed.call_count, 2)
        result, provider = self.index(identifier)
        provider.assert_not_called()
        self.assertEqual(result['embedding']['vector_count'], 3)

    def test_semantic_search_ranks_unique_chunks_and_preserves_sources(self):
        indexed = self.create(['每月清洁滤网。设备型号 AX-410。', '采购发票'])
        self.index(indexed, [InputTooLong(), (VECTOR, 5), (VECTOR, 5), (ORTHOGONAL_VECTOR, 2)])
        partial = self.create(['未完成的部分命中', '未生成向量的段落'])
        self.index(partial, [(VECTOR, 4), DocumentError('embedding_quota', 'Quota reached', 503)])
        old_model = self.create(['来自旧模型的命中'])
        with patch.object(config, 'VERTEX_EMBEDDING_MODEL', 'text-multilingual-embedding-002'):
            self.index(old_model)
        unreadable = self.create(['不可阅读的命中'])
        self.index(unreadable)
        with store.connect() as conn:
            conn.execute("UPDATE knowledge_base_v1.documents SET status='failed' WHERE id=%s", (unreadable,))

        query = '零件多久维护一次'
        params = {'mode': 'semantic', 'q': f'  {query}  ', 'limit': 1}
        with patch('embeddings.retrieval.VertexEmbedder') as provider:
            embed = provider.return_value.__enter__.return_value.embed
            embed.return_value = (VECTOR, 4)
            first = self.client.get('/api/search', params=params, headers=self.headers)
            self.assertEqual(first.status_code, 200, first.text)
            embed.assert_called_once_with(query, task='RETRIEVAL_QUERY')
            match, = first.json()['items']
            self.assertEqual(match['document_id'], str(indexed))
            self.assertEqual(match['chunk']['text'], '每月清洁滤网。设备型号 AX-410。')
            self.assertEqual(match['chunk']['sources'][0]['block_index'], 0)
            self.assertTrue(first.json()['has_more'])
            second = self.client.get('/api/search', params={**params, 'offset': 1}, headers=self.headers)
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual([hit['chunk_index'] for hit in second.json()['items']], [1])
            self.assertFalse(second.json()['has_more'])

        literal = self.client.get('/api/search', params={'q': 'AX-410'}, headers=self.headers)
        self.assertEqual([hit['document_id'] for hit in literal.json()['items']], [str(indexed)])
        literal = self.client.get('/api/search', params={'q': query}, headers=self.headers)
        self.assertEqual(literal.json()['items'], [])

    def test_context_reads_only_current_neighbors_in_the_same_document(self):
        identifier = self.create(['前一段', '上下文锚点', '后一段', '更远的段落'])
        self.create(['其他文件'])
        anchor, = store.search_chunks('上下文锚点', 10, 0)['items']
        neighbors = store.read_chunk_context(anchor)
        self.assertEqual([hit['chunk']['text'] for hit in neighbors], ['前一段', '上下文锚点', '后一段'])
        self.assertEqual({hit['document_id'] for hit in neighbors}, {identifier})
        complete = store.read_short_document_context(anchor)
        self.assertEqual([hit['chunk']['text'] for hit in complete], ['前一段', '上下文锚点', '后一段', '更远的段落'])
        self.assertEqual({hit['document_id'] for hit in complete}, {identifier})
        with store.connect() as conn:
            conn.execute("""UPDATE knowledge_base_v1.chunks SET data=jsonb_set(data, '{text}', to_jsonb('已改变'::text))
                WHERE document_id=%s AND chunk_index=1""", (identifier,))
        self.assertEqual(store.read_chunk_context(anchor), [])
        self.assertEqual(store.read_short_document_context(anchor), [])
        large = self.create([f'Large document part {index}' for index in range(9)])
        large_anchor, = store.search_chunks('Large document part 0', 1, 0, document_id=large)['items']
        self.assertEqual(store.read_short_document_context(large_anchor), [])

    def test_scoped_semantic_search_only_uses_vectors_from_the_requested_document(self):
        target = self.create(['目标合同'])
        self.index(target, [(ORTHOGONAL_VECTOR, 4)])
        other = self.create(['更相似的另一份合同'])
        self.index(other)
        unindexed = self.create(['尚未生成向量的合同'])
        with patch('embeddings.retrieval.VertexEmbedder') as provider:
            provider.return_value.__enter__.return_value.embed.return_value = (VECTOR, 4)
            result = semantic_search('付款条款', 4, document_id=target)
            self.assertEqual([hit['document_id'] for hit in result['items']], [target])
            with self.assertRaises(DocumentError) as caught:
                semantic_search('付款条款', 4, document_id=unindexed)
            self.assertEqual(caught.exception.code, 'semantic_index_empty')
            provider.assert_called_once()

    def test_overlong_input_is_split_and_completed_children_are_reused(self):
        identifier = self.create(['abcd'])
        result, _ = self.index(identifier, [InputTooLong(), (VECTOR, 2), DocumentError('embedding_quota', 'Quota reached', 503)])
        self.assertEqual(result['embedding']['completed_chunks'], 0)
        self.assertEqual(result['embedding']['vector_count'], 1)
        result, provider = self.index(identifier)
        provider.return_value.__enter__.return_value.embed.assert_called_once_with('cd')
        self.assertEqual(result['embedding']['completed_chunks'], 1)
        with store.connect() as conn:
            rows = conn.execute('SELECT start_char,end_char,input_hash,data,embedding::text AS vector FROM knowledge_base_v1.embedding_parts WHERE document_id=%s ORDER BY start_char', (identifier,)).fetchall()
        self.assertEqual([(row['start_char'], row['end_char']) for row in rows], [(0, 2), (2, 4)])
        self.assertEqual(''.join(row['data']['text'] for row in rows), 'abcd')
        for row in rows:
            self.assertEqual(row['input_hash'], hashlib.sha256(row['data']['text'].encode()).hexdigest())
            self.assertAlmostEqual(math.hypot(*json.loads(row['vector'])), 1)
            self.assertEqual(row['data']['sources'][0]['start'], row['start_char'])
            self.assertEqual(row['data']['sources'][0]['end'], row['end_char'])

    def test_model_switch_uses_a_new_profile_and_reparsing_invalidates_all_vectors(self):
        identifier = self.create(['same text'])
        first, _ = self.index(identifier)
        with patch.object(config, 'VERTEX_EMBEDDING_MODEL', 'text-multilingual-embedding-002'):
            with store.connect() as conn:
                self.assertEqual(store.get_document(conn, identifier)['embedding']['status'], 'pending')
            second, provider = self.index(identifier)
            self.assertNotEqual(first['embedding']['model'], second['embedding']['model'])
            provider.assert_called_once()
        with store.ingestion_connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS count FROM knowledge_base_v1.embedding_parts WHERE document_id=%s', (identifier,)).fetchone()['count'], 2)
            store.save_blocks(conn, identifier, ParsedDocument([Block(0, 'paragraph', 'changed')]), 'new')
            self.assertEqual(conn.execute('SELECT count(*) AS count FROM knowledge_base_v1.embedding_parts WHERE document_id=%s', (identifier,)).fetchone()['count'], 0)
            self.assertEqual(store.get_document(conn, identifier)['embedding']['status'], 'pending')
            store.save_chunks(conn, identifier, [Chunk(0, 'changed', [], [{'block_index': 0, 'page': None, 'start': 0, 'end': 7}])], 'new', {})
        result, provider = self.index(identifier)
        provider.return_value.__enter__.return_value.embed.assert_called_once_with('changed')
        self.assertEqual(result['embedding']['status'], 'ready')

    def test_upload_indexes_after_commit_but_cloud_failure_does_not_fail_document(self):
        with patch('embeddings.service.VertexEmbedder') as provider:
            provider.return_value.__enter__.side_effect = DocumentError('embedding_api_disabled', 'Enable Vertex API', 503)
            response = self.client.post('/api/documents', files={'file': ('upload.txt', f'Fixture {uuid4()}'.encode())}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        doc = response.json()['document']
        self.ids.append(doc['id'])
        self.assertEqual(doc['status'], 'ready')
        self.assertEqual(doc['embedding']['error_code'], 'embedding_api_disabled')
        self.assertTrue((self.directory / f"{doc['id']}.txt").is_file())
        with patch('embeddings.service.VertexEmbedder') as provider, patch('documents.service.parse_document') as parse:
            provider.return_value.__enter__.return_value.embed.return_value = (VECTOR, 10)
            response = self.client.post(f"/api/documents/{doc['id']}/embeddings", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['embedding']['status'], 'ready')
            parse.assert_not_called()

    def test_abandoned_run_is_retryable_without_losing_completed_parts(self):
        identifier = self.create(['saved'])
        self.index(identifier)
        with store.connect() as conn:
            conn.execute("UPDATE knowledge_base_v1.embedding_runs SET status='processing' WHERE document_id=%s", (identifier,))
        result = self.client.get(f'/api/documents/{identifier}', headers=self.headers).json()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['embedding']['error_code'], 'embedding_interrupted')
        self.assertEqual(result['embedding']['vector_count'], 1)
        result, provider = self.index(identifier)
        provider.assert_not_called()
        self.assertEqual(result['embedding']['status'], 'ready')

    def test_timeout_before_first_request_is_persisted_and_next_call_continues(self):
        identifier = self.create(['bounded work'])
        with store.ingestion_connection() as conn, patch('embeddings.service.VertexEmbedder') as provider:
            result = index_document(conn, identifier, budget_seconds=0)
            provider.return_value.__enter__.return_value.embed.assert_not_called()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['embedding']['error_code'], 'embedding_timeout')
        result, _ = self.index(identifier)
        self.assertEqual(result['embedding']['status'], 'ready')

    def test_cli_backfill_reuses_chunks_without_parsing_or_duplicate_vectors(self):
        from cli import main
        identifier = self.create(['backfill only'])
        with patch('sys.argv', ['cli.py', 'embed-documents', '--document-id', str(identifier)]), \
                patch('embeddings.service.VertexEmbedder') as provider, patch('documents.service.parse_document') as parse, redirect_stdout(StringIO()):
            provider.return_value.__enter__.return_value.embed.return_value = (VECTOR, 10)
            self.assertEqual(main(), 0)
            self.assertEqual(main(), 0)
            provider.assert_called_once()
            parse.assert_not_called()

    @unittest.skipIf(os.getenv('RAG_TEST_DB_FLAVOR') == 'pglite', 'Needs native PostgreSQL session locks')
    def test_reading_does_not_mark_an_active_embedding_request_interrupted(self):
        identifier = self.create(['active work'])
        self.index(identifier)
        with store.ingestion_connection() as conn:
            conn.execute("UPDATE knowledge_base_v1.embedding_runs SET status='processing' WHERE document_id=%s", (identifier,))
            response = self.client.get(f'/api/documents/{identifier}', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['embedding']['status'], 'processing')
            self.assertEqual(self.client.post(f'/api/documents/{identifier}/embeddings', headers=self.headers).status_code, 409)


if __name__ == '__main__':
    unittest.main()
