"""Multilingual plans, privacy boundaries and shared answer retrieval."""

import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from test_shell import app, PASSWORD
from answers.service import Evidence, SEARCH
from documents.models import DocumentError
from embeddings.provider import Profile
from search import expansion
from search.service import multilingual_search

PLAN = {'zh': ['车贷 利息', '利息总额'], 'en': ['loan interest', 'total interest'],
        'da': ['billån renter', 'renteomkostninger']}


def hit(identifier, index=0):
    return {'document_id': identifier, 'filename': f'{identifier}.txt', 'chunk_index': index,
            'chunk': {'text': 'Synthetic excerpt', 'section': [], 'sources': [{'block_index': index, 'page': None}]}}


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        expansion._cache.clear()
        self.profile = Profile('test-project', 'global', 'test-model')
        self.enterContext(patch('search.expansion.answer_profile', return_value=self.profile))
        self.model = self.enterContext(patch('search.expansion.Gemini'))
        self.generate = self.model.return_value.__enter__.return_value.generate
        self.generate.return_value = {'parts': [{'functionCall': {'name': expansion.TOOL['name'], 'args': PLAN}}]}

    def test_expands_only_query_and_caches_a_copy_not_search_results(self):
        result = expansion.expand_query('车贷利息')
        self.assertEqual(result, PLAN)
        request = self.generate.call_args
        self.assertEqual(request.args[0], [{'role': 'user', 'parts': [{'text': '车贷利息'}]}])
        self.assertEqual(request.args[3], [expansion.TOOL['name']])
        result['en'].append('modified')
        self.assertEqual(expansion.expand_query('车贷利息'), PLAN)
        self.generate.assert_called_once()

    def test_cache_expires_and_is_separated_by_model_profile(self):
        with patch('search.expansion.time.monotonic', return_value=100):
            expansion.expand_query('车贷利息')
        with patch('search.expansion.time.monotonic', return_value=100 + expansion.CACHE_TTL + 1):
            expansion.expand_query('车贷利息')
        with patch('search.expansion.answer_profile', return_value=Profile('test-project', 'global', 'another-model')):
            expansion.expand_query('车贷利息')
        self.assertEqual(self.generate.call_count, 3)

    def test_invalid_model_plans_never_reach_search(self):
        for payload in ({'zh': ['车贷']}, {**PLAN, 'da': []}, {**PLAN, 'en': [' ']},
                        {**PLAN, 'en': ['x' * 201]}, {**PLAN, 'en': ['x\x00']},
                        {**PLAN, 'en': [' '.join(['word'] * 11)]}, {**PLAN, 'en': 'loan'}):
            with self.subTest(payload=payload):
                self.generate.return_value = {'parts': [{'functionCall': {'name': expansion.TOOL['name'], 'args': payload}}]}
                with self.assertRaises(DocumentError) as error:
                    expansion.expand_query('车贷利息')
                self.assertEqual(error.exception.code, 'multilingual_response')
        self.generate.return_value = {'parts': [{'functionCall': 'invalid'}]}
        with self.assertRaises(DocumentError):
            expansion.expand_query('车贷利息')

    def test_translated_queries_can_preserve_original_identifiers(self):
        payload = {'zh': ['京A12345 保险'], 'en': ['京A12345 insurance'], 'da': ['京A12345 forsikring']}
        self.generate.return_value = {'parts': [{'functionCall': {'name': expansion.TOOL['name'], 'args': payload}}]}
        self.assertEqual(expansion.expand_query('京A12345 保险'), payload)

    def test_concurrent_expansion_uses_the_first_completed_cached_plan(self):
        first = {language: tuple(variants[:1]) for language, variants in PLAN.items()}
        def other_request_finishes(*args):
            expansion._cache[(self.profile.resource, '车贷利息')] = (time.monotonic() + 600, first)
            return {'parts': [{'functionCall': {'name': expansion.TOOL['name'], 'args': PLAN}}]}
        self.generate.side_effect = other_request_finishes
        self.assertEqual(expansion.expand_query('车贷利息'), {language: list(queries) for language, queries in first.items()})

    def test_invalid_input_and_expired_deadline_precede_the_model(self):
        for query in (' ', '\x00', 'x' * 201):
            with self.assertRaises(DocumentError) as error:
                expansion.expand_query(query)
            self.assertEqual(error.exception.code, 'multilingual_query_invalid')
        with self.assertRaises(DocumentError) as error:
            expansion.expand_query('车贷利息', deadline=0)
        self.assertEqual(error.exception.code, 'multilingual_timeout')
        self.generate.assert_not_called()

    def test_disabled_and_failed_models_are_explicit_not_empty_results(self):
        with patch('search.expansion.answer_profile', return_value=None), self.assertRaises(DocumentError) as error:
            expansion.expand_query('车贷利息')
        self.assertEqual(error.exception.code, 'multilingual_disabled')
        for original, expected in [('answer_unavailable', 'multilingual_unavailable'),
                                   ('answer_timeout', 'multilingual_timeout'),
                                   ('answer_response', 'multilingual_response')]:
            self.generate.side_effect = DocumentError(original, 'synthetic failure', 503)
            with self.assertRaises(DocumentError) as error:
                expansion.expand_query('车贷利息')
            self.assertEqual(error.exception.code, expected)


class MultilingualSearchTests(unittest.TestCase):
    def test_alternatives_are_ored_preserve_original_and_paginate_in_sql(self):
        with patch('search.service.expand_query', return_value=PLAN), \
                patch('db.documents.search_chunk_variants', return_value={'items': [hit('danish')], 'has_more': True}) as search:
            result = multilingual_search('车贷利息', 30, 30, document_id='scope')
            again = multilingual_search('车贷利息', 30, 60, document_id='scope')
        args = search.call_args_list[0]
        self.assertEqual(args.args[1:], (30, 30))
        self.assertEqual(args.kwargs, {'document_id': 'scope'})
        self.assertEqual(args.args[0], ['车贷利息', *PLAN['zh'], *PLAN['en'], *PLAN['da']])
        self.assertEqual(result['queries'], PLAN)
        self.assertEqual(result['items'][0]['document_id'], 'danish')
        self.assertEqual(search.call_count, 2)  # Current documents are queried on every page.

    def test_all_languages_are_kept_for_an_identifier_without_duplicate_variants(self):
        with patch('search.service.expand_query', return_value={language: ['AX-410'] for language in PLAN}), \
                patch('db.documents.search_chunk_variants', return_value={'items': [], 'has_more': False}) as search:
            result = multilingual_search('AX-410', 30)
        self.assertEqual(search.call_args.args[0], ['AX-410'])
        self.assertEqual(set(result['queries']), set(PLAN))

    def test_chinese_answers_augment_semantic_hits_and_deduplicate_source_ids(self):
        english, danish = hit('english'), hit('danish')
        evidence = Evidence(time.monotonic() + 30, {'D1': 'scope'}, multilingual=True)
        with patch('answers.service.multilingual_search', return_value={'items': [danish, english], 'has_more': False, 'queries': PLAN}) as search, \
                patch('answers.service.semantic_search', return_value={'items': [english], 'has_more': False}), \
                patch('db.documents.read_short_document_context', return_value=[]):
            result = evidence.run(SEARCH, {'query': '车贷利息', 'mode': 'semantic', 'document_ref': 'D1'}, 4)
        search.assert_called_once_with('车贷利息', 4, deadline=evidence.deadline, document_id='scope')
        self.assertEqual([row['source_id'] for row in result['excerpts']], ['S1', 'S2'])
        answer = evidence.finish({'paragraphs': [{'text': 'Synthetic answer', 'source_ids': ['S2']}], 'limitations': ''})
        self.assertEqual(answer['citations']['S2']['document_id'], 'danish')
        self.assertEqual(answer['citations']['S2']['locations'], [{'block_index': 0, 'page': None}])

    def test_translation_failure_is_reported_to_the_model_while_literal_search_can_continue(self):
        evidence = Evidence(time.monotonic() + 30, {}, multilingual=True)
        with patch('answers.service.multilingual_search', side_effect=DocumentError('multilingual_unavailable', 'off', 503)), \
                patch('db.documents.search_chunks', return_value={'items': [hit('exact')], 'has_more': False}), \
                patch('db.documents.read_short_document_context', return_value=[]):
            result = evidence.run(SEARCH, {'query': 'AX-410', 'mode': 'keyword'}, 4)
        self.assertEqual(result['multilingual_error'], 'multilingual_unavailable')
        self.assertEqual(len(result['excerpts']), 1)

    def test_translated_hits_survive_an_unavailable_semantic_index(self):
        evidence = Evidence(time.monotonic() + 30, {}, multilingual=True)
        with patch('answers.service.multilingual_search', return_value={'items': [hit('danish')], 'has_more': False, 'queries': PLAN}), \
                patch('answers.service.semantic_search', side_effect=DocumentError('semantic_disabled', 'off', 503)), \
                patch('db.documents.read_short_document_context', return_value=[]):
            result = evidence.run(SEARCH, {'query': '车贷利息', 'mode': 'semantic'}, 4)
        self.assertEqual(result['semantic_error'], 'semantic_disabled')
        self.assertEqual(result['excerpts'][0]['filename'], 'danish.txt')


class SearchApiTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        self.headers = {'Authorization': f'Bearer {token}'}

    def test_owner_and_input_validation_precede_expansion(self):
        with patch('search.service.expand_query') as expand:
            self.assertEqual(self.client.get('/api/search', params={'q': '车贷', 'mode': 'multilingual'}).status_code, 401)
            for query in ('', ' ', '\x00', 'x' * 201):
                self.assertEqual(self.client.get('/api/search', params={'q': query, 'mode': 'multilingual'}, headers=self.headers).status_code, 422)
            expand.assert_not_called()

    def test_multilingual_api_preserves_legacy_keyword_mode_and_reports_failures(self):
        with patch('api.search.multilingual_search', return_value={'items': [], 'has_more': False, 'queries': PLAN}) as search:
            response = self.client.get('/api/search', params={'q': '车贷利息', 'mode': 'multilingual', 'offset': 30}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['queries'], PLAN)
        search.assert_called_once_with('车贷利息', 30, 30)
        with patch('search.expansion.answer_profile', return_value=None):
            response = self.client.get('/api/search', params={'q': '车贷利息', 'mode': 'multilingual'}, headers=self.headers)
        self.assertEqual(response.json()['code'], 'multilingual_disabled')
