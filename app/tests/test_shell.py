"""Regression tests for the remaining API boundary, without a real database."""

from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

import bcrypt
import jwt
import psycopg
from fastapi.testclient import TestClient

PASSWORD = "local-test-password"
# Lower cost is confined to tests; production uses bcrypt's default cost.
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
SECRET = "test-only-signing-key-with-at-least-32-bytes"

with patch.dict(os.environ, {
    "JWT_SECRET": SECRET,
    "OWNER_PASSWORD_HASH": PASSWORD_HASH,
    "JWT_EXPIRE_MINUTES": "60",
}):
    from core import config
    from api.security import hash_password, verify_password
    from main import app


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))

    def test_password_login_and_owner_session_work_without_user_database(self):
        with patch("db.connection.psycopg.connect") as connect:
            response = self.client.post("/api/auth/login", json={"password": PASSWORD})
            self.assertEqual(response.status_code, 200)
            token = response.json()["access_token"]
            response = self.client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"role": "owner"})
            connect.assert_not_called()

    def test_missing_and_invalid_credentials_are_rejected(self):
        for headers in ({}, {"Authorization": "Bearer invalid"},
                        {"Authorization": "Basic invalid"}):
            with self.subTest(headers=headers):
                response = self.client.get("/api/auth/me", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
        response = self.client.post("/api/auth/login", json={"password": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_old_tokens_and_invalid_claims_cannot_become_owner(self):
        now = datetime.now(timezone.utc)
        valid = {
            "sub": "owner", "iss": config.JWT_ISSUER, "aud": config.JWT_AUDIENCE,
            "iat": now, "exp": now + timedelta(hours=1),
        }
        cases = [
            ("legacy", {"sub": "old-user-id", "iat": now, "exp": valid["exp"]}, SECRET),
            ("different owner", {**valid, "sub": "old-user-id"}, SECRET),
            ("expired", {**valid, "exp": now - timedelta(seconds=1)}, SECRET),
            ("other audience", {**valid, "aud": "another-app"}, SECRET),
            ("other issuer", {**valid, "iss": "another-app"}, SECRET),
            ("invalid signature", valid, "another-test-secret-with-at-least-32-bytes"),
        ]
        for claim in ("sub", "iss", "aud", "iat", "exp"):
            cases.append((f"missing {claim}", {k: v for k, v in valid.items() if k != claim}, SECRET))
        for name, payload, secret in cases:
            with self.subTest(name=name):
                token = jwt.encode(payload, secret, algorithm="HS256")
                response = self.client.get(
                    "/api/auth/me", headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(response.status_code, 401)

    def test_long_passwords_are_rejected_without_server_errors(self):
        for password in ("a" * 73, "中" * 25):
            with self.subTest(password=password):
                response = self.client.post("/api/auth/login", json={"password": password})
                self.assertIn(response.status_code, (401, 422))
                self.assertFalse(verify_password(password, PASSWORD_HASH))

    def test_removed_business_and_registration_routes_are_not_exposed(self):
        routes = [
            ("POST", "/api/ask"), ("GET", "/api/conversations"),
            ("POST", "/api/auth/register"), ("GET", "/api/auth/config"),
            ("POST", "/api/upload"),
            ("POST", "/api/upload_async"), ("GET", "/api/tasks/old-task"),
            ("GET", "/api/traces"),
            ("GET", "/api/models"),
        ]
        for method, path in routes:
            with self.subTest(path=path):
                self.assertEqual(self.client.request(method, path).status_code, 404)

    def test_search_authentication_validation_and_method(self):
        self.assertEqual(self.client.get('/api/search?q=test').status_code, 401)
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        for query in ('', '  ', '\x00', ' '.join(str(i) for i in range(11)), 'a' * 201):
            self.assertEqual(self.client.get('/api/search', params={'q': query}, headers=headers).status_code, 422)
        with patch('db.documents.search_chunks', return_value={'items': [], 'has_more': False}) as search:
            response = self.client.get('/api/search', params={'q': '滤网 filter'}, headers=headers)
            self.assertEqual(response.status_code, 200)
            search.assert_called_once_with('滤网 filter', 30, 0)
        self.assertEqual(self.client.post('/api/search', headers=headers).status_code, 405)

    def test_semantic_search_requires_owner_configuration_and_an_index(self):
        params = {'q': 'How often should I clean it?', 'mode': 'semantic'}
        self.assertEqual(self.client.get('/api/search', params=params).status_code, 401)
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        with patch('embeddings.retrieval.active_profile', return_value=None), patch('embeddings.retrieval.VertexEmbedder') as vertex, \
                patch('db.embeddings.has_searchable_embeddings') as available:
            response = self.client.get('/api/search', params=params, headers=headers)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['code'], 'semantic_disabled')
            vertex.assert_not_called()
            available.assert_not_called()
        with patch('embeddings.retrieval.active_profile'), patch('db.embeddings.has_searchable_embeddings', return_value=False), \
                patch('embeddings.retrieval.VertexEmbedder') as vertex:
            response = self.client.get('/api/search', params=params, headers=headers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['code'], 'semantic_index_empty')
            vertex.assert_not_called()
        for invalid in ({**params, 'q': '   '}, {**params, 'q': '\x00'}, {**params, 'mode': 'hybrid'}):
            self.assertEqual(self.client.get('/api/search', params=invalid, headers=headers).status_code, 422)

    def test_health_reports_readiness_with_http_status(self):
        with patch("api.health.check_database"):
            response = self.client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"postgres": True})
        with patch("api.health.check_database", side_effect=psycopg.OperationalError("private DSN")):
            response = self.client.get("/api/health")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"postgres": False})
            self.assertNotIn("private DSN", response.text)
            self.assertEqual(self.client.get("/").status_code, 200)


class ConfigurationTests(unittest.TestCase):
    def test_startup_refuses_missing_or_placeholder_auth_configuration(self):
        cases = [
            {"JWT_SECRET": ""},
            {"JWT_SECRET": "change-me-to-a-long-random-string-1234"},
            {"OWNER_PASSWORD_HASH": ""},
            {"OWNER_PASSWORD_HASH": "not-a-bcrypt-hash"},
            {"JWT_EXPIRE_MINUTES": 0},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides), patch.multiple(config, **overrides):
                with self.assertRaises(RuntimeError), TestClient(app):
                    pass

    def test_password_hashing_rejects_weak_or_overlong_input(self):
        for password in ("short", "中" * 25):
            with self.subTest(password=password), self.assertRaises(ValueError):
                hash_password(password)
        self.assertTrue(verify_password(PASSWORD, hash_password(PASSWORD)))


if __name__ == "__main__":
    unittest.main()
