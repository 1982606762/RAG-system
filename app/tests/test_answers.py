"""Gemini tool contracts and private document question/answer regressions."""

import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from test_shell import app, PASSWORD
from answers.provider import Gemini
from answers.service import READ, SEARCH, SUBMIT, TOOLS
from embeddings.provider import Profile


def turn(name, **args):
    return {"role": "model", "parts": [{
        "functionCall": {"name": name, "args": args, "id": name},
        "thoughtSignature": "model-signature",
    }]}


def hit(document_id, text, index=0):
    return {"document_id": document_id, "filename": f"{document_id}.txt", "chunk_index": index,
            "chunk": {"text": text, "section": [], "sources": [{"block_index": index, "page": index + 1}]}}


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))
        token = self.client.post("/api/auth/login", json={"password": PASSWORD}).json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.profile = Profile("answer-test", "global", "gemini-3.1-flash-lite")

    def ask(self, question="本期实际付了多少？", depth="auto"):
        return self.client.post("/api/ask", json={"question": question, "depth": depth}, headers=self.headers)

    def test_owner_validation_and_disabled_mode_precede_google(self):
        with patch("answers.service.Gemini") as provider, patch("answers.service.answer_profile", return_value=None):
            self.assertEqual(self.client.post("/api/ask", json={"question": "test"}).status_code, 401)
            for invalid in (" ", "\x00", "x" * 2001):
                self.assertEqual(self.ask(invalid).status_code, 422)
            self.assertEqual(self.ask(depth="other").status_code, 422)
            self.assertEqual(self.ask().json()["code"], "answer_disabled")
            provider.assert_not_called()

    def test_deep_search_reads_context_and_multiple_files_and_validates_citations(self):
        first = turn(SEARCH, query="已付", mode="semantic")
        second = turn(READ, source_id="S1")
        third = turn(SEARCH, query="二月 已付", mode="keyword")
        final = turn(SUBMIT, paragraphs=[{"text": "一月实付 300 元，二月实付 200 元，合计 500 元。",
                                         "source_ids": ["S1", "S3"]}], limitations="缺少三月凭证。")
        january = hit("jan", "一月已付 300 元。")
        neighbor = hit("jan", "三月为计划金额。", 1)
        february = hit("feb", "二月已付 200 元。")

        # Copy contents at call time because the tool loop appends in place.
        snapshots = []
        def model_reply(contents, instruction, tools, allowed):
            snapshots.append((list(contents), list(allowed)))
            return next(replies)
        replies = iter([first, second, third, final])
        with patch("answers.service.answer_profile", return_value=self.profile), \
                patch("answers.service.Gemini") as gemini, \
                patch("answers.service.semantic_search", return_value={"items": [january], "has_more": False}), \
                patch("db.documents.read_chunk_context", return_value=[january, neighbor]) as read, \
                patch("db.documents.search_chunks", return_value={"items": [february], "has_more": False}) as search:
            gemini.return_value.__enter__.return_value.generate.side_effect = model_reply
            response = self.ask(depth="deep")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["paragraphs"][0]["source_ids"], ["S1", "S3"])
        self.assertEqual(data["limitations"], "缺少三月凭证。")
        self.assertEqual(data["citations"]["S3"]["locations"], [{"block_index": 0, "page": 1}])
        self.assertEqual(set(data["citations"]), {"S1", "S3"})
        self.assertEqual(snapshots[0][1], [SEARCH])
        self.assertNotIn(SUBMIT, snapshots[1][1])
        self.assertEqual(snapshots[1][0][1], first)
        self.assertEqual(snapshots[1][0][2]["parts"][0]["functionResponse"]["id"], SEARCH)
        read.assert_called_once_with(january)
        search.assert_called_once_with("二月 已付", 5, 0)

    def test_semantic_outage_allows_keyword_and_fabricated_citations_cannot_escape(self):
        from documents.models import DocumentError
        turns = [
            turn(SEARCH, query="付款", mode="semantic"),
            turn(SEARCH, query="AX-410", mode="keyword"),
            turn(SUBMIT, paragraphs=[{"text": "Invented", "source_ids": ["S99"]}], limitations=""),
            turn(SUBMIT, paragraphs=[], limitations="只有型号，缺少付款凭证。"),
        ]
        with patch("answers.service.answer_profile", return_value=self.profile), patch("answers.service.Gemini") as gemini, \
                patch("answers.service.semantic_search", side_effect=DocumentError("semantic_disabled", "off", 503)), \
                patch("db.documents.search_chunks", return_value={"items": [hit("model", "AX-410")], "has_more": False}):
            provider = gemini.return_value.__enter__.return_value
            provider.generate.side_effect = turns
            result = self.ask()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"paragraphs": [], "limitations": "只有型号，缺少付款凭证。", "citations": {}})
        self.assertNotIn("Invented", result.text)

    def test_vertex_transport_requests_forced_tools(self):
        session = Mock()
        session.post.return_value = Mock(ok=True, status_code=200, json=Mock(return_value={"candidates": [
            {"finishReason": "STOP", "content": turn(SEARCH, query="滤网", mode="keyword")}
        ]}))
        with patch("answers.provider.google.auth.default", return_value=(Mock(), "project")), \
                patch("answers.provider.AuthorizedSession", return_value=session):
            with Gemini(self.profile, time.monotonic() + 15) as provider:
                result = provider.generate([{"role": "user", "parts": [{"text": "滤网"}]}], "instruction", TOOLS, [SEARCH])
        self.assertEqual(result["parts"][0]["functionCall"]["name"], SEARCH)
        request = session.post.call_args
        self.assertIn("https://aiplatform.googleapis.com/v1/projects/answer-test/locations/global/", request.args[0])
        self.assertTrue(request.args[0].endswith(":generateContent"))
        self.assertEqual(request.kwargs["json"]["toolConfig"]["functionCallingConfig"],
                         {"mode": "ANY", "allowedFunctionNames": [SEARCH]})
        session.close.assert_called_once()
