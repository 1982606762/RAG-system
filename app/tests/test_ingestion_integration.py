"""Opt-in tests against a disposable PostgreSQL database.

Set RAG_TEST_PG_DSN to a test database only. Tests initialize the MVP schema,
create their own records, and delete only the records they created.
"""

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from test_shell import app, PASSWORD
from core import config
from db import documents as store
from documents.models import DocumentError, Chunk
from documents.service import original_path


@unittest.skipUnless(os.getenv('RAG_TEST_PG_DSN'), 'Set RAG_TEST_PG_DSN to run database integration tests')
class IngestionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = patch.object(config, 'PG_DSN', os.environ['RAG_TEST_PG_DSN'])
        cls.patch.start()
        cls.connection_patch = None
        if os.getenv('RAG_TEST_DB_FLAVOR') == 'pglite':
            native_connect = store.connect
            def connect_without_prepared_statements():
                conn = native_connect()
                # PGlite shares a backend across client sessions, including
                # prepared-statement names. Production connections are unchanged.
                conn.prepare_threshold = None
                return conn
            cls.connection_patch = patch.object(store, 'connect', connect_without_prepared_statements)
            cls.connection_patch.start()
        store.initialize()
        store.initialize()

    @classmethod
    def tearDownClass(cls):
        if cls.connection_patch:
            cls.connection_patch.stop()
        cls.patch.stop()

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(config, 'DOCUMENTS_DIR', self.directory))
        self.client = self.enterContext(TestClient(app))
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        self.headers = {'Authorization': f'Bearer {token}'}
        self.ids = []
        self.content = f'# Maintenance {uuid4()}\n\nClean the filter monthly.\n\n## Warning\n\nDisconnect power first.'.encode()

    def tearDown(self):
        with store.connect() as conn:
            for document_id in self.ids:
                conn.execute('DELETE FROM knowledge_base_v1.documents WHERE id=%s', (document_id,))

    def upload(self, filename='manual.md', content=None):
        response = self.client.post('/api/documents', headers=self.headers,
                                    files={'file': (filename, self.content if content is None else content)})
        if response.status_code == 200:
            document_id = response.json()['document']['id']
            if document_id not in self.ids:
                self.ids.append(document_id)
        return response

    def test_upload_list_detail_and_original_round_trip(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.text)
        doc = response.json()['document']
        self.assertEqual(doc['status'], 'ready', doc)
        self.assertGreater(doc['chunk_count'], 0)
        self.assertTrue(original_path(doc['id'], '.md').exists())
        detail = self.client.get(f"/api/documents/{doc['id']}", headers=self.headers).json()
        self.assertEqual(len(detail['blocks']), doc['block_count'])
        self.assertEqual(len(detail['chunks']), doc['chunk_count'])
        self.assertEqual(detail['chunk_config']['unit'], 'unicode_characters')
        listing = self.client.get('/api/documents?limit=100', headers=self.headers).json()
        self.assertIn(doc['id'], [row['id'] for row in listing['items']])
        original = self.client.get(f"/api/documents/{doc['id']}/original", headers=self.headers)
        self.assertEqual(original.content, self.content)
        self.assertEqual(original.headers['x-content-type-options'], 'nosniff')
        self.assertIn('attachment', original.headers['content-disposition'])

    def test_duplicate_reuses_record_and_original(self):
        first = self.upload().json()
        second = self.upload('different-name.md').json()
        self.assertTrue(second['duplicate'])
        self.assertEqual(first['document']['id'], second['document']['id'])
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_invalid_pdf_preserves_original_and_failure(self):
        content = f'not a PDF {uuid4()}'.encode()
        doc = self.upload('broken.pdf', content).json()['document']
        self.assertEqual(doc['status'], 'failed')
        self.assertEqual(doc['error_code'], 'invalid_pdf')
        self.assertEqual(doc['stage'], 'parsing')
        self.assertEqual(original_path(doc['id'], '.pdf').read_bytes(), content)

    def test_transient_failure_then_retry_creates_one_set_of_chunks(self):
        with patch('documents.service.parse_document', side_effect=DocumentError('ocr_unavailable', 'OCR not installed')):
            doc = self.upload().json()['document']
        self.assertEqual(doc['status'], 'failed')
        response = self.client.post(f"/api/documents/{doc['id']}/retry", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'ready')
        detail = self.client.get(f"/api/documents/{doc['id']}", headers=self.headers).json()
        self.assertEqual(len(detail['chunks']), response.json()['chunk_count'])
        self.assertEqual(len({chunk['index'] for chunk in detail['chunks']}), len(detail['chunks']))
        self.assertEqual(self.client.post(f"/api/documents/{doc['id']}/retry", headers=self.headers).status_code, 409)

    def test_chunk_failure_keeps_parsed_blocks_for_inspection(self):
        with patch('documents.service.chunk_blocks', side_effect=DocumentError('chunk_error', 'Chunking failed')):
            doc = self.upload().json()['document']
        self.assertEqual(doc['status'], 'failed')
        self.assertEqual(doc['stage'], 'chunking')
        detail = self.client.get(f"/api/documents/{doc['id']}", headers=self.headers).json()
        self.assertGreater(len(detail['blocks']), 0)
        self.assertEqual(detail['chunks'], [])
        response = self.client.post(f"/api/documents/{doc['id']}/retry", headers=self.headers)
        self.assertEqual(response.json()['status'], 'ready')

    def test_interrupted_processing_becomes_retryable_when_lock_is_free(self):
        doc = self.upload().json()['document']
        with store.connect() as conn:
            conn.execute("UPDATE knowledge_base_v1.documents SET status='processing' WHERE id=%s", (doc['id'],))
        response = self.client.get(f"/api/documents/{doc['id']}", headers=self.headers)
        self.assertEqual(response.json()['status'], 'failed')
        self.assertEqual(response.json()['error_code'], 'interrupted')

    def test_size_empty_and_path_traversal(self):
        with patch.object(config, 'MAX_UPLOAD_BYTES', 8):
            self.assertEqual(self.upload().status_code, 413)
        self.assertEqual(self.upload(content=b'').status_code, 422)
        self.assertEqual(list(self.directory.iterdir()), [])
        doc = self.upload('../../outside.md').json()['document']
        self.assertEqual(doc['filename'], 'outside.md')
        self.assertTrue(original_path(doc['id'], '.md').is_file())
        self.assertFalse((self.directory.parent / 'outside.md').exists())

    def test_chunk_write_is_atomic(self):
        import psycopg
        doc = self.upload().json()['document']
        with store.connect() as conn:
            old = conn.execute('SELECT data FROM knowledge_base_v1.chunks WHERE document_id=%s ORDER BY chunk_index', (doc['id'],)).fetchall()
            chunks = [Chunk(0, 'one', [], []), Chunk(0, 'duplicate index', [], [])]
            with self.assertRaises(psycopg.errors.UniqueViolation):
                store.save_chunks(conn, doc['id'], chunks, 'test', {})
            current = conn.execute('SELECT data FROM knowledge_base_v1.chunks WHERE document_id=%s ORDER BY chunk_index', (doc['id'],)).fetchall()
            self.assertEqual(current, old)

    @unittest.skipIf(os.getenv('RAG_TEST_DB_FLAVOR') == 'pglite', 'PGlite multiplexes one backend; advisory-lock concurrency needs native PostgreSQL')
    def test_second_request_is_busy_and_active_job_is_not_recovered(self):
        doc = self.upload().json()['document']
        with store.ingestion_connection() as conn:
            conn.execute("UPDATE knowledge_base_v1.documents SET status='processing' WHERE id=%s", (doc['id'],))
            self.assertEqual(self.upload(content=b'other content').status_code, 409)
            detail = self.client.get(f"/api/documents/{doc['id']}", headers=self.headers).json()
            self.assertEqual(detail['status'], 'processing')


if __name__ == '__main__':
    unittest.main()
