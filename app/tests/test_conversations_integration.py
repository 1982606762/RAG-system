"""Saved follow-ups exercised through FastAPI and native PostgreSQL."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_shell import app, PASSWORD
from fastapi.testclient import TestClient
from core import config
from db import documents as store
from documents.models import DocumentError
from answers.service import SEARCH, SUBMIT


@unittest.skipUnless(os.getenv("RAG_TEST_PG_DSN"), "Set RAG_TEST_PG_DSN for conversation integration tests")
class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(config, "PG_DSN", os.environ["RAG_TEST_PG_DSN"]))
        self.enterContext(patch.object(config, "VERTEX_ANSWER_PROJECT", "conversation-test"))
        self.enterContext(patch.object(config, "VERTEX_EMBEDDING_PROJECT", ""))
        self.enterContext(patch.object(config, "GOOGLE_DOCUMENT_AI_PROCESSOR", ""))
        self.enterContext(patch.object(config, "DOCUMENTS_DIR", Path(self.enterContext(TemporaryDirectory()))))
        store.initialize()
        self.client = self.enterContext(TestClient(app))
        token = self.client.post("/api/auth/login", json={"password": PASSWORD}).json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.documents = []
        self.conversations = []

    def tearDown(self):
        with store.connect() as conn:
            for identifier in self.conversations:
                conn.execute("DELETE FROM knowledge_base_v1.conversations WHERE id=%s", (identifier,))
            for identifier in self.documents:
                conn.execute("DELETE FROM knowledge_base_v1.documents WHERE id=%s", (identifier,))

    def upload(self, filename, text):
        result = self.client.post("/api/documents", headers=self.headers,
                                  files={"file": (filename, text.encode(), "text/plain")})
        self.assertEqual(result.status_code, 200, result.text)
        identifier = result.json()["document"]["id"]
        self.documents.append(identifier)
        return identifier

    def test_three_turns_reload_same_document_and_retry(self):
        marker = f"合同-{uuid4()}"
        contract = self.upload("loan.md", f"# {marker}\n\n月供 3000 元。\n\n提前还款可于月中办理。\n\n提前还款免手续费。")
        self.upload("other.md", "# 另一份合同\n\n提前还款只能在月底办理。")
        question_queries = {f"{marker}的月供是多少？": marker, "那提前还款呢？": "提前还款", "手续费呢？": "手续费"}
        conversation_id, second_id, third_id = (str(uuid4()) for _ in range(3))
        self.conversations.append(conversation_id)
        root = "/api/conversations"
        path = f"{root}/{conversation_id}"

        def reply(contents, instruction, tools, allowed):
            raw_question = contents[0]["parts"][0]["text"]
            if len(contents) == 1:
                args = {"query": question_queries[raw_question], "mode": "keyword"} if raw_question in question_queries else None
                if args is None:
                    history = json.loads(raw_question)
                    args = {"query": question_queries[history["current_question"]], "mode": "keyword", "document_ref": "D1"}
                    self.assertIn("loan.md", history["recent_history"][-1]["previously_cited_documents"].values())
                    self.assertNotIn(contract, raw_question)
                name = SEARCH
            else:
                excerpts = contents[-1]["parts"][0]["functionResponse"]["response"]["excerpts"]
                self.assertTrue(excerpts)
                self.assertEqual({item["filename"] for item in excerpts}, {"loan.md"})
                args = {"paragraphs": [{"text": "合同中有相关说明。", "source_ids": [excerpts[0]["source_id"]]}],
                        "limitations": ""}
                name = SUBMIT
            self.assertIn(name, allowed)
            return {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}

        def send(url, question, identifier, parent=None):
            payload = {"question": question, "request_id": identifier}
            if parent:
                payload["after_turn_id"] = parent
            return self.client.post(url, headers=self.headers, json=payload)

        with patch("answers.service.Gemini") as gemini:
            model = gemini.return_value.__enter__.return_value
            model.generate.side_effect = reply
            first = send(root, next(iter(question_queries)), conversation_id)
            self.assertEqual(first.status_code, 200, first.text)
            second = send(path + "/turns", "那提前还款呢？", second_id, conversation_id)
            self.assertEqual(second.status_code, 200, second.text)
            reloaded = self.client.get(path, headers=self.headers).json()
            self.assertEqual([turn["id"] for turn in reloaded["turns"]], [conversation_id, second_id])
            third = send(path + "/turns", "手续费呢？", third_id, reloaded["turns"][-1]["id"])
            self.assertEqual(third.status_code, 200, third.text)
            replay = send(path + "/turns", "手续费呢？", third_id, second_id)
            self.assertEqual(replay.json(), third.json())
            stale = send(path + "/turns", "手续费呢？", str(uuid4()), second_id)
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(model.generate.call_count, 6)

        restored = self.client.get(path, headers=self.headers).json()
        self.assertEqual(len(restored["turns"]), 3)
        for turn in restored["turns"]:
            self.assertEqual(turn["answer"]["citations"]["S1"]["document_id"], contract)
            self.assertTrue(turn["answer"]["citations"]["S1"]["locations"])
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.delete(path).status_code, 401)
        self.assertEqual(self.client.delete(path, headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get(path, headers=self.headers).status_code, 404)

    def test_provider_failure_leaves_no_empty_conversation(self):
        identifier = str(uuid4())
        self.conversations.append(identifier)
        with patch("api.conversations.answer_question", side_effect=DocumentError("answer_unavailable", "offline", 503)):
            failed = self.client.post("/api/conversations", headers=self.headers,
                                      json={"question": "有没有合同？", "request_id": identifier})
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(self.client.get(f"/api/conversations/{identifier}", headers=self.headers).status_code, 404)
