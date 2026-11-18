"""Vertex Gemini REST transport for the document answer tool loop."""

import re
import time

import google.auth
from google.auth import exceptions as auth_errors
from google.auth.transport.requests import AuthorizedSession
import requests

from core import config
from documents.models import DocumentError
from embeddings.provider import Profile, active_profile


def answer_profile():
    project = config.VERTEX_ANSWER_PROJECT
    if not project:
        embedding = active_profile()
        if embedding is None:
            return None
        project = embedding.project
    return Profile(project, config.VERTEX_ANSWER_LOCATION, config.VERTEX_ANSWER_MODEL)


class Gemini:
    def __init__(self, profile, deadline):
        self.profile = profile
        self.deadline = deadline

    def __enter__(self):
        profile = self.profile
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", profile.project)
                or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", profile.location)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}", profile.model)):
            raise DocumentError("answer_configuration", "Gemini 项目、区域或模型配置无效。", 503)
        try:
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            self.session = AuthorizedSession(credentials, refresh_timeout=10, max_refresh_attempts=1)
        except auth_errors.GoogleAuthError as exc:
            raise DocumentError("answer_configuration", "无法读取 Gemini 的 Google ADC 凭据。", 503) from exc
        return self

    def __exit__(self, *errors):
        self.session.close()

    def generate(self, contents, instruction, tools, allowed):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DocumentError("answer_timeout", "本次问答超时，请缩小查询范围后重试。", 504)
        profile = self.profile
        host = "aiplatform.googleapis.com" if profile.location == "global" else f"{profile.location}-aiplatform.googleapis.com"
        try:
            response = self.session.post(
                f"https://{host}/v1/{profile.resource}:generateContent",
                json={
                    "systemInstruction": {"parts": [{"text": instruction}]},
                    "contents": contents,
                    "tools": [{"functionDeclarations": tools}],
                    "toolConfig": {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": allowed}},
                    "generationConfig": {"maxOutputTokens": 4096},
                },
                timeout=min(18, remaining), max_allowed_time=remaining,
            )
        except (requests.Timeout, auth_errors.TimeoutError) as exc:
            raise DocumentError("answer_timeout", "本次问答超时，请缩小查询范围后重试。", 504) from exc
        except auth_errors.GoogleAuthError as exc:
            raise DocumentError("answer_configuration", "Gemini 的 Google ADC 认证失败。", 503) from exc
        except requests.RequestException as exc:
            raise DocumentError("answer_unavailable", "暂时无法连接 Gemini。", 503) from exc
        if response.status_code in (401, 403, 404):
            raise DocumentError("answer_configuration", "无法访问 Gemini，请检查 Vertex AI 权限、模型和区域。", 503)
        if response.status_code == 429 or response.status_code >= 500:
            raise DocumentError("answer_unavailable", "Gemini 暂时不可用，请稍后重试。", 503)
        if not response.ok:
            raise DocumentError("answer_response", "Gemini 请求失败。", 502)
        try:
            candidate = response.json()["candidates"][0]
            content = candidate["content"]
            if (candidate.get("finishReason") != "STOP" or content["role"] != "model"
                    or not isinstance(content["parts"], list)):
                raise ValueError("Incomplete model content")
            return content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DocumentError("answer_response", "Gemini 未返回完整的工具调用。", 502) from exc
