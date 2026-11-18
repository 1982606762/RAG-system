"""Provider contracts, source-preserving splits and private embedding endpoints."""

import math
import time
import unittest
from unittest.mock import Mock, patch

from test_shell import app, PASSWORD
from fastapi.testclient import TestClient
from core import config
from documents.models import DocumentError
from embeddings.provider import DIMENSIONS, InputTooLong, Profile, VertexEmbedder, active_profile, normalized
from embeddings.service import make_part, valid_parts


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.enterContext(patch('embeddings.provider.google.auth.default', return_value=(Mock(), 'test')))
        self.enterContext(patch('embeddings.provider.AuthorizedSession', return_value=self.session))
        self.profile = Profile('project-test', 'europe-west4', 'gemini-embedding-001')

    def reply(self, body, status=200):
        self.session.post.return_value = Mock(ok=status < 400, status_code=status, json=Mock(return_value=body))

    def embed(self):
        with VertexEmbedder(self.profile, time.monotonic() + 30) as provider:
            return provider.embed('Private document text')

    def test_rest_request_uses_document_task_and_disables_truncation(self):
        self.reply({'predictions': [{'embeddings': {'values': [2.0] * DIMENSIONS,
                     'statistics': {'truncated': False, 'token_count': 13.0}}}]})
        values, count = self.embed()
        self.assertEqual(count, 13)
        self.assertAlmostEqual(math.hypot(*values), 1)
        request = self.session.post.call_args
        self.assertIn('/locations/europe-west4/publishers/google/models/gemini-embedding-001:predict', request.args[0])
        self.assertEqual(request.kwargs['json'], {'instances': [{'content': 'Private document text', 'task_type': 'RETRIEVAL_DOCUMENT'}],
                         'parameters': {'autoTruncate': False, 'outputDimensionality': 768}})
        self.session.close.assert_called_once()

    def test_rest_request_uses_query_task_with_the_same_model_and_dimensions(self):
        self.reply({'predictions': [{'embeddings': {'values': [2.0] * DIMENSIONS,
                     'statistics': {'truncated': False, 'token_count': 5}}}]})
        with VertexEmbedder(self.profile, time.monotonic() + 12) as provider:
            provider.embed('How often should I clean it?', task='RETRIEVAL_QUERY')
        request = self.session.post.call_args
        self.assertIn(self.profile.resource, request.args[0])
        self.assertEqual(request.kwargs['json'], {
            'instances': [{'content': 'How often should I clean it?', 'task_type': 'RETRIEVAL_QUERY'}],
            'parameters': {'autoTruncate': False, 'outputDimensionality': DIMENSIONS},
        })

    def test_token_limit_errors_and_truncation_are_never_accepted(self):
        bodies = [({'error': {'message': 'The input token count exceeds the maximum token limit.'}}, 400),
                  ({'predictions': [{'embeddings': {'values': [1.0] * 768, 'statistics': {'truncated': True, 'token_count': 2048}}}]}, 200),
                  ({'predictions': [{'embeddings': {'values': [1.0] * 768, 'statistics': {'truncated': False, 'token_count': 2049}}}]}, 200)]
        for body, status in bodies:
            with self.subTest(status=status):
                self.reply(body, status)
                with self.assertRaises(InputTooLong):
                    self.embed()

    def test_configuration_permission_and_quota_failures_are_actionable(self):
        cases = [(403, {'details': [{'reason': 'SERVICE_DISABLED'}]}, 'embedding_api_disabled'),
                 (403, {}, 'embedding_permission'), (404, {}, 'embedding_configuration'), (429, {}, 'embedding_quota'),
                 (400, {'message': 'Private provider diagnostics'}, 'embedding_request')]
        for status, error, code in cases:
            with self.subTest(code=code):
                self.reply({'error': error}, status)
                with self.assertRaises(DocumentError) as caught:
                    self.embed()
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('Private', str(caught.exception))

    def test_invalid_vectors_statistics_and_response_shapes_fail(self):
        for values in ([0.0] * 768, [1.0] * 767, [float('nan')] * 768, [float('inf')] * 768, [True] * 768):
            with self.subTest(values=values[:1]), self.assertRaises(DocumentError):
                normalized(values)
        for body in ([], {}, {'predictions': []}, {'predictions': [{'embeddings': {
                'values': [1.0] * 768, 'statistics': {'truncated': False, 'token_count': 'invalid'}}}]}):
            self.reply(body)
            with self.assertRaises(DocumentError):
                self.embed()

    def test_profile_changes_isolate_models_regions_and_projects(self):
        variants = [self.profile, Profile('other', self.profile.location, self.profile.model),
                    Profile(self.profile.project, 'us-central1', self.profile.model),
                    Profile(self.profile.project, self.profile.location, 'text-multilingual-embedding-002')]
        self.assertEqual(len({profile.key for profile in variants}), 4)
        with patch.object(config, 'VERTEX_EMBEDDING_PROJECT', ''), patch.object(config, 'GOOGLE_DOCUMENT_AI_PROCESSOR', ''):
            self.assertIsNone(active_profile())
        with patch.object(config, 'VERTEX_EMBEDDING_PROJECT', ''), patch.object(config, 'GOOGLE_DOCUMENT_AI_PROCESSOR', 'projects/123/locations/eu/processors/id'):
            self.assertEqual(active_profile().project, '123')

    def test_parts_preserve_exact_input_and_block_ranges_across_joined_sources(self):
        chunk = {'text': 'Title\n\n😀维护说明', 'sources': [
            {'block_index': 0, 'page': 1, 'start': 3, 'end': 8},
            {'block_index': 1, 'page': 2, 'start': 10, 'end': 15}]}
        left, right = make_part(chunk, 0, 9), make_part(chunk, 9, 12)
        self.assertEqual(left['data']['text'] + right['data']['text'], chunk['text'])
        self.assertEqual(right['data']['sources'], [{'block_index': 1, 'page': 2, 'start': 12, 'end': 15}])
        self.assertTrue(valid_parts([left, right], chunk))
        self.assertFalse(valid_parts([right, left], chunk))
        changed = {**right, 'data': {**right['data'], 'text': 'different'}}
        self.assertFalse(valid_parts([left, changed], chunk))


class EmbeddingBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        self.headers = {'Authorization': f'Bearer {token}'}
        self.url = '/api/documents/00000000-0000-0000-0000-000000000001/embeddings'

    def test_owner_and_uuid_are_checked_before_any_embedding_call(self):
        with patch('embeddings.service.retry_embeddings') as index:
            self.assertEqual(self.client.post(self.url).status_code, 401)
            self.assertEqual(self.client.post('/api/documents/invalid/embeddings', headers=self.headers).status_code, 422)
            index.assert_not_called()

    def test_missing_configuration_does_not_open_a_cloud_request(self):
        with patch('embeddings.provider.active_profile', return_value=None), patch('embeddings.service.active_profile', return_value=None), \
                patch('db.documents.ingestion_connection') as connection, patch('embeddings.service.VertexEmbedder') as provider:
            response = self.client.post(self.url, headers=self.headers)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['code'], 'embedding_not_configured')
            provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()
