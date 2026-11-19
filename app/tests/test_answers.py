"""Gemini tool contracts and private document question/answer regressions."""

import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from test_shell import app, PASSWORD
from answers.provider import Gemini
from answers.service import READ, SEARCH, SUBMIT, TOOLS, answer_question
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
        self.enterContext(patch("db.documents.read_short_document_context", return_value=[]))

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
        self.assertEqual(result.json(), {"paragraphs": [], "limitations": "只有型号，缺少付款凭证。", "notes": "", "citations": {}})
        self.assertNotIn("Invented", result.text)

    def test_contract_estimate_notes_do_not_become_evidence_gaps(self):
        turns = [turn(SEARCH, query="Ejerudgifter", mode="keyword"),
                 turn(SUBMIT, paragraphs=[{"text": "合同预估每月业主支出为 3485 丹麦克朗。", "source_ids": ["S1"]}],
                      limitations="", notes="  合同预估值不代表实际扣款。  ")]
        with patch("answers.service.answer_profile", return_value=self.profile), patch("answers.service.Gemini") as gemini, \
                patch("db.documents.search_chunks", return_value={"items": [hit("contract", "Ejerudgifter pr. md. 3.485")], "has_more": False}):
            gemini.return_value.__enter__.return_value.generate.side_effect = turns
            response = self.ask("合同有没有说每个月交多少钱？")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["limitations"], "")
        self.assertEqual(response.json()["notes"], "合同预估值不代表实际扣款。")
        self.assertEqual(response.json()["citations"]["S1"]["document_id"], "contract")

    def test_empty_chinese_keywords_recover_danish_evidence_with_semantic_search(self):
        question = "车贷每月还款"
        excerpts = []
        def reply(contents, *args):
            if len(contents) == 1:
                return turn(SEARCH, query=question, mode="keyword")
            recovered = contents[-1]["parts"][0]["functionResponse"]["response"]
            self.assertEqual(recovered["fallback"], "semantic")
            excerpts.extend(recovered["excerpts"])
            return turn(SUBMIT, paragraphs=[{"text": "合同月供为 3150 丹麦克朗。", "source_ids": ["S1"]}], limitations="")

        with patch("answers.service.answer_profile", return_value=self.profile), patch("answers.service.Gemini") as gemini, \
                patch("db.documents.search_chunks", return_value={"items": [], "has_more": False}), \
                patch("answers.service.semantic_search", return_value={"items": [hit("new-loan", "Månedlige ydelser: 3.150,00 kr.")], "has_more": False}) as semantic:
            gemini.return_value.__enter__.return_value.generate.side_effect = reply
            result = self.ask(question)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(excerpts[0]["filename"], "new-loan.txt")
        self.assertEqual(result.json()["citations"]["S1"]["document_id"], "new-loan")
        semantic.assert_called_once_with(question, 4, deadline=unittest.mock.ANY)

    def test_no_evidence_after_scoped_search_requires_fresh_whole_library_search(self):
        old = hit("old-loan", "Earlier agreement without monthly terms")
        new = hit("new-loan", "Månedlige ydelser: 3.150,00 kr.")
        history = [{"question": "我的贷款有哪些条款？", "answer": {
            "paragraphs": [{"text": "找到旧合同。"}],
            "citations": {"S1": {"document_id": "old-loan", "filename": "old.txt"}},
        }}]
        replies = iter([
            turn(SEARCH, query="贷款月供", mode="keyword", document_ref="D1"),
            turn(SUBMIT, paragraphs=[], limitations="没有月供资料。"),
            turn(SUBMIT, paragraphs=[{"text": "新合同月供为 3150 丹麦克朗。", "source_ids": ["S2"]}], limitations=""),
        ])
        snapshots = []
        def reply(contents, *args):
            snapshots.append(list(contents))
            return next(replies)

        with patch("answers.service.answer_profile", return_value=self.profile), patch("answers.service.Gemini") as gemini, \
                patch("db.documents.search_chunks", return_value={"items": [old], "has_more": False}) as keywords, \
                patch("answers.service.semantic_search", return_value={"items": [new], "has_more": False}) as semantic:
            gemini.return_value.__enter__.return_value.generate.side_effect = reply
            result = answer_question("刚上传了新合同，现在月供多少？", "auto", history=history)
        keywords.assert_called_once_with("贷款月供", 4, 0, document_id="old-loan")
        semantic.assert_called_once_with("贷款月供", 4, deadline=unittest.mock.ANY)
        recovery = snapshots[-1][-1]["parts"][0]["functionResponse"]["response"]
        self.assertIn("review_required", recovery)
        self.assertEqual(recovery["library_search"]["excerpts"][0]["source_id"], "S2")
        self.assertEqual(result["citations"]["S2"]["document_id"], "new-loan")
        self.assertEqual(result["limitations"], "")

    def test_empty_keyword_fallback_reports_semantic_outage_without_retry_loop(self):
        from documents.models import DocumentError
        snapshots = []
        def reply(contents, *args):
            snapshots.append(list(contents))
            if len(contents) == 1:
                return turn(SEARCH, query="车贷", mode="keyword")
            return turn(SUBMIT, paragraphs=[], limitations="关键词未命中，语义服务暂不可用，尚无法完成核对。")

        with patch("answers.service.answer_profile", return_value=self.profile), patch("answers.service.Gemini") as gemini, \
                patch("db.documents.search_chunks", return_value={"items": [], "has_more": False}), \
                patch("answers.service.semantic_search", side_effect=DocumentError("embedding_quota", "quota", 503)) as semantic:
            gemini.return_value.__enter__.return_value.generate.side_effect = reply
            result = self.ask()
        self.assertEqual(result.status_code, 200, result.text)
        recovery = snapshots[-1][-1]["parts"][0]["functionResponse"]["response"]
        self.assertEqual(recovery["semantic_error"], "embedding_quota")
        self.assertEqual(recovery["excerpts"], [])
        self.assertEqual(result.json()["paragraphs"], [])
        self.assertEqual(semantic.call_count, 1)

    def test_short_schedule_includes_separate_fee_clause_before_answering(self):
        schedule = hit("updated-loan", "Månedlig ydelse: 3.000,00 DKK.", 1)
        fee = hit("updated-loan", "Månedligt gebyr: 25,00 DKK. I alt 3.025,00 DKK.", 4)
        snapshots = []
        def reply(contents, *args):
            snapshots.append(list(contents))
            if len(contents) == 1:
                return turn(SEARCH, query="车贷月供", mode="semantic")
            excerpts = contents[-1]["parts"][0]["functionResponse"]["response"]["excerpts"]
            self.assertEqual([excerpt["text"] for excerpt in excerpts], [schedule["chunk"]["text"], fee["chunk"]["text"]])
            return turn(SUBMIT, paragraphs=[{"text": "按计划每月合计 3025 DKK，含月供 3000 和手续费 25。",
                                             "source_ids": ["S1", "S2"]}], limitations="")

        with patch("answers.service.answer_profile", return_value=self.profile), patch("answers.service.Gemini") as gemini, \
                patch("answers.service.semantic_search", return_value={"items": [schedule], "has_more": False}), \
                patch("db.documents.read_short_document_context", return_value=[schedule, fee]) as context:
            gemini.return_value.__enter__.return_value.generate.side_effect = reply
            result = self.ask("我的车贷每月交多少钱？")
        self.assertEqual(result.status_code, 200, result.text)
        context.assert_called_once_with(schedule)
        self.assertEqual(result.json()["citations"]["S2"]["locations"], [{"block_index": 4, "page": 5}])

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
