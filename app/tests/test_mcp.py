"""Exercise the official SDK over the actual authenticated ASGI HTTP endpoint."""

from datetime import datetime, timedelta, timezone
from functools import wraps
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx2
import jwt
import psycopg
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from test_shell import app, SECRET
from api.security import create_access_token, create_mcp_token
from core import config
from documents.models import DocumentError


class MCPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app, base_url='http://localhost'))
        self.headers = {'Authorization': f'Bearer {create_mcp_token()}',
                        'Accept': 'application/json, text/event-stream'}

    def test_all_http_methods_require_a_dedicated_mcp_credential(self):
        for method in ('GET', 'POST', 'DELETE'):
            for token in ('', 'invalid', create_access_token()):
                response = self.client.request(method, '/api/mcp', headers={'Authorization': f'Bearer {token}'})
                self.assertEqual(response.status_code, 401)
        now = datetime.now(timezone.utc)
        for claims in ({'exp': now - timedelta(seconds=1)}, {'sub': 'other'}, {'aud': 'other'}, {'iss': 'other'}):
            payload = {'sub': 'owner', 'aud': 'rag-mcp', 'iss': config.JWT_ISSUER,
                       'iat': now - timedelta(hours=1), 'exp': now + timedelta(hours=1), **claims}
            token = jwt.encode(payload, SECRET, algorithm='HS256')
            self.assertEqual(self.client.get('/api/mcp', headers={'Authorization': f'Bearer {token}'}).status_code, 401)

    def test_mcp_token_cannot_access_rest_or_write_documents(self):
        for method, path in [('GET', '/api/documents'), ('POST', '/api/documents'),
                             ('GET', '/api/auth/me'), ('GET', '/api/search?q=test'),
                             ('POST', f'/api/documents/{uuid4()}/retry')]:
            self.assertEqual(self.client.request(method, path, headers=self.headers).status_code, 401)
        for days in (0, 366):
            with self.assertRaises(ValueError):
                create_mcp_token(days)

    def test_invalid_origin_and_host_are_rejected(self):
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}
        for headers, status in [({'Origin': 'https://evil.example'}, 403), ({'Host': 'evil.example'}, 421)]:
            response = self.client.post('/api/mcp', headers={**self.headers, **headers}, json=payload)
            self.assertEqual(response.status_code, status, response.text)


def mcp_session(test):
    @wraps(test)
    async def run(self):
        # AnyIO cancel scopes must enter and exit in the same asyncio task.
        async with app.router.lifespan_context(app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={'Authorization': f'Bearer {create_mcp_token()}'},
        ) as http, streamable_http_client('http://localhost/api/mcp', http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                self.session = session
                await session.initialize()
                await test(self)
    return run


class MCPSDKTests(unittest.IsolatedAsyncioTestCase):

    @mcp_session
    async def test_tool_discovery_and_keyword_and_semantic_calls(self):
        listing = await self.session.list_tools()
        self.assertEqual({tool.name for tool in listing.tools},
                         {'search_documents', 'search_keywords', 'list_documents', 'get_document', 'read_document'})
        self.assertTrue(all(tool.annotations.read_only_hint for tool in listing.tools))
        for mode, target in [('keyword', 'db.documents.search_chunks'), ('semantic', 'search.service.semantic_search')]:
            with patch(target, return_value={'items': [], 'has_more': False}) as search:
                result = await self.session.call_tool('search_documents', {'query': 'filter', 'mode': mode})
                self.assertFalse(result.is_error, result)
                self.assertEqual(result.structured_content, {'items': [], 'has_more': False})
                search.assert_called_once_with('filter', 10, 0)

    @mcp_session
    async def test_variants_and_context_keep_scope_pagination_and_provenance(self):
        identifier = uuid4()
        with patch('db.documents.search_chunk_variants', return_value={'items': [], 'has_more': True}) as search:
            result = await self.session.call_tool('search_keywords', {
                'queries': ['利息', 'interest', 'renter'], 'limit': 2, 'offset': 2, 'document_id': str(identifier)})
            self.assertFalse(result.is_error, result)
            search.assert_called_once_with(['利息', 'interest', 'renter'], 2, 2, document_id=identifier)
        window = {'document': {'id': identifier, 'filename': 'manual.txt'}, 'chunks': [
            {'index': 1, 'text': 'Clean monthly.', 'sources': [{'block_index': 2, 'page': 3}]}],
            'blocks': [{'index': 2, 'location': {'type': 'page', 'page': 3}}], 'has_more': True, 'next_chunk': 2}
        with patch('db.documents.read_document', return_value=window) as read:
            result = await self.session.call_tool('read_document', {'document_id': str(identifier), 'start_chunk': 1, 'limit': 1})
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.structured_content['chunks'], window['chunks'])
            self.assertEqual(result.structured_content['blocks'], window['blocks'])
            read.assert_called_once_with(identifier, 1, 1)

    @mcp_session
    async def test_metadata_is_bounded_and_list_does_not_recover_ingestion(self):
        identifier = uuid4()
        document = {'id': identifier, 'filename': 'manual.txt', 'content_hash': 'internal'}
        with patch('db.documents.list_documents', return_value={'items': [document], 'total': 1}) as listing:
            result = await self.session.call_tool('list_documents', {})
            self.assertFalse(result.is_error, result)
            self.assertNotIn('content_hash', result.structured_content['items'][0])
            listing.assert_called_once_with(30, 0, recover=False)
        with patch('db.documents.connect'), patch('db.documents.get_document', return_value=document):
            result = await self.session.call_tool('get_document', {'document_id': str(identifier)})
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.structured_content, {'id': str(identifier), 'filename': 'manual.txt'})

    @mcp_session
    async def test_invalid_arguments_and_service_failures_are_tool_errors(self):
        with patch('db.documents.search_chunks') as search:
            for args in ({'query': ''}, {'query': 'x', 'limit': 51}, {'query': 'x', 'offset': -1},
                         {'query': 'x', 'document_id': 'not-a-uuid'}, {'query': 'x', 'mode': 'multilingual'}):
                result = await self.session.call_tool('search_documents', args)
                self.assertTrue(result.is_error, result)
            search.assert_not_called()
        for error in (DocumentError('semantic_index_empty', '先生成向量', 409), psycopg.OperationalError('private DSN')):
            with patch('search.service.semantic_search', side_effect=error):
                result = await self.session.call_tool('search_documents', {'query': 'test', 'mode': 'semantic'})
                self.assertTrue(result.is_error, result)
                self.assertNotIn('private DSN', str(result))
                self.assertIn('semantic_index_empty' if isinstance(error, DocumentError) else 'database_unavailable', str(result))
