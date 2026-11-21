"""REST retrieval shares the same service as MCP, without model query planning."""

import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from test_shell import app, PASSWORD
from documents.models import DocumentError


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        self.headers = {'Authorization': f'Bearer {token}'}

    def test_keyword_alternatives_require_owner_and_validate_before_database_access(self):
        self.assertEqual(self.client.post('/api/search/keywords', json={'queries': ['test']}).status_code, 401)
        with patch('db.documents.connect') as connect:
            for body in ({'queries': []}, {'queries': ['x'] * 11}, {'queries': ['x' * 201]},
                         {'queries': [' ']}, {'queries': ['\x00']}, {'queries': ['a ' * 11]},
                         {'queries': ['x'], 'limit': 51}, {'queries': ['x'], 'offset': -1},
                         {'queries': ['x'], 'document_id': 'invalid'}):
                response = self.client.post('/api/search/keywords', json=body, headers=self.headers)
                self.assertEqual(response.status_code, 422, response.text)
            connect.assert_not_called()

    def test_caller_supplies_translations_and_results_are_paginated_together(self):
        identifier = uuid4()
        with patch('db.documents.search_chunk_variants', return_value={'items': [], 'has_more': True}) as search:
            response = self.client.post('/api/search/keywords', headers=self.headers, json={
                'queries': ['利息', 'interest', 'renter'], 'limit': 2, 'offset': 2, 'document_id': str(identifier)})
            self.assertEqual(response.status_code, 200, response.text)
            search.assert_called_once_with(['利息', 'interest', 'renter'], 2, 2, document_id=identifier)

    def test_keyword_and_semantic_search_can_be_scoped_to_a_document(self):
        identifier = uuid4()
        for mode, target in [('keyword', 'db.documents.search_chunks'), ('semantic', 'search.service.semantic_search')]:
            with patch(target, return_value={'items': [], 'has_more': False}) as search:
                response = self.client.get('/api/search', headers=self.headers,
                    params={'q': 'filter', 'mode': mode, 'document_id': str(identifier), 'limit': 3, 'offset': 6})
                self.assertEqual(response.status_code, 200, response.text)
                search.assert_called_once_with('filter', 3, 6, document_id=identifier)

    def test_no_implicit_translation_or_answer_routes(self):
        self.assertEqual(self.client.get('/api/search', params={'q': 'test', 'mode': 'multilingual'}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post('/api/ask', json={'question': 'test'}, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get('/api/conversations', headers=self.headers).status_code, 404)

    def test_chunk_window_validation_authentication_and_missing_files(self):
        identifier = uuid4()
        path = f'/api/documents/{identifier}/chunks'
        self.assertEqual(self.client.get(path).status_code, 401)
        with patch('db.documents.read_document', return_value={'chunks': [], 'blocks': [], 'has_more': False, 'next_chunk': None}) as read:
            response = self.client.get(path, headers=self.headers, params={'start_chunk': 4, 'limit': 2})
            self.assertEqual(response.status_code, 200)
            read.assert_called_once_with(identifier, 4, 2)
            for params in ({'start_chunk': -1}, {'limit': 0}, {'limit': 21}):
                self.assertEqual(self.client.get(path, headers=self.headers, params=params).status_code, 422)
        with patch('db.documents.read_document', side_effect=DocumentError('not_found', 'missing', 404)):
            self.assertEqual(self.client.get(path, headers=self.headers).status_code, 404)
