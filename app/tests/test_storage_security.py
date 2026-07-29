"""Focused regression tests for the agent's database boundary."""

import importlib.util
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _stub_optional_runtime_modules() -> None:
    """Let this pure SQL-builder test run without the large app dependencies."""
    if importlib.util.find_spec("chromadb") is None:
        chromadb = types.ModuleType("chromadb")
        chromadb.HttpClient = MagicMock()
        sys.modules["chromadb"] = chromadb
    if importlib.util.find_spec("psycopg") is None:
        psycopg = types.ModuleType("psycopg")
        psycopg.connect = MagicMock()
        sys.modules["psycopg"] = psycopg
    if importlib.util.find_spec("sentence_transformers") is None:
        sentence_transformers = types.ModuleType("sentence_transformers")
        sentence_transformers.SentenceTransformer = MagicMock
        sys.modules["sentence_transformers"] = sentence_transformers


_stub_optional_runtime_modules()

from db.storage import structured_document_search  # noqa: E402


class StructuredDocumentSearchTests(unittest.TestCase):
    def test_ignores_model_supplied_sql_and_always_scopes_user(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchall.return_value = []

        with patch("db.storage.psycopg.connect", return_value=connection):
            result = structured_document_search(
                "user-a",
                {
                    "mode": "rows",
                    "sql": "SELECT email FROM users",
                    "limit": 9999,
                },
            )

        query, params = connection.execute.call_args.args
        self.assertNotIn("users", query.lower())
        self.assertIn("where user_id = %s", query.lower())
        self.assertEqual(params, ["user-a", 100])
        self.assertEqual(result, {"mode": "rows", "rows": []})

    def test_count_keeps_user_filter_and_returns_integer(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchall.return_value = [(3,)]

        with patch("db.storage.psycopg.connect", return_value=connection):
            result = structured_document_search(
                "user-b",
                {"mode": "count", "doc_type": "invoice"},
            )

        query, params = connection.execute.call_args.args
        self.assertIn("count(*)", query.lower())
        self.assertEqual(params, ["user-b", "invoice"])
        self.assertEqual(result, {"mode": "count", "value": 3})


if __name__ == "__main__":
    unittest.main()
