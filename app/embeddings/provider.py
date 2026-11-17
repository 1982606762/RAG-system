"""Vertex REST adapter using the Google authentication dependencies already installed."""

from dataclasses import dataclass
import hashlib
import math
import re
import time

import google.auth
from google.auth import exceptions as auth_errors
from google.auth.transport.requests import AuthorizedSession
import requests

from core import config
from documents.models import DocumentError

DIMENSIONS = 768
MAX_TOKENS = 2048
TASK = "RETRIEVAL_DOCUMENT"


class InputTooLong(Exception):
    """The provider rejected or truncated this input; it must be split."""


@dataclass(frozen=True)
class Profile:
    project: str
    location: str
    model: str

    @property
    def resource(self):
        return f"projects/{self.project}/locations/{self.location}/publishers/google/models/{self.model}"

    @property
    def key(self):
        # Include provider, task, dimensions and input/splitting policy. A new
        # model or region can never masquerade as the current index.
        return hashlib.sha256(f"vertex|{self.resource}|{TASK}|{DIMENSIONS}|parts-v1".encode()).hexdigest()


def active_profile():
    project = config.VERTEX_EMBEDDING_PROJECT
    if not project:
        match = re.fullmatch(r"projects/([^/]+)/locations/[^/]+/processors/[^/]+", config.GOOGLE_DOCUMENT_AI_PROCESSOR)
        project = match[1] if match else ""
    return Profile(project, config.VERTEX_EMBEDDING_LOCATION, config.VERTEX_EMBEDDING_MODEL) if project else None


def normalized(values):
    if not isinstance(values, list) or len(values) != DIMENSIONS or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values
    ):
        raise DocumentError("embedding_response", "向量服务返回了无效的维度或数值。", 502)
    norm = math.hypot(*values)
    if norm == 0 or not math.isfinite(norm):
        raise DocumentError("embedding_response", "向量服务返回了无效的零向量或数值。", 502)
    return [value / norm for value in values]


class VertexEmbedder:
    def __init__(self, profile, deadline):
        self.profile = profile
        self.deadline = deadline
        self.session = None

    def __enter__(self):
        p = self.profile
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", p.project)
                or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", p.location)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}", p.model)):
            raise DocumentError("embedding_configuration", "Vertex AI 项目、区域或模型配置无效。", 503)
        try:
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            self.session = AuthorizedSession(credentials, refresh_timeout=15, max_refresh_attempts=1)
        except auth_errors.GoogleAuthError as exc:
            raise DocumentError("embedding_credentials", "无法读取 Google ADC 凭据，请检查向量服务认证配置。", 503) from exc
        return self

    def __exit__(self, *args):
        if self.session:
            self.session.close()

    def embed(self, text):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DocumentError("embedding_timeout", "向量化时间预算已用完，已保存的进度可继续处理。", 504)
        p = self.profile
        host = "aiplatform.googleapis.com" if p.location == "global" else f"{p.location}-aiplatform.googleapis.com"
        try:
            response = self.session.post(
                f"https://{host}/v1/{p.resource}:predict",
                json={"instances": [{"content": text, "task_type": TASK}],
                      "parameters": {"autoTruncate": False, "outputDimensionality": DIMENSIONS}},
                timeout=min(15, remaining), max_allowed_time=remaining,
            )
        except auth_errors.GoogleAuthError as exc:
            raise DocumentError("embedding_credentials", "Google ADC 认证失败，请检查凭据和权限。", 503) from exc
        except requests.RequestException as exc:
            raise DocumentError("embedding_unavailable", "向量服务连接失败或超时，已保存的进度可继续处理。", 503) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise DocumentError("embedding_response", "向量服务返回了无效响应。", 502) from exc
        if not isinstance(body, dict):
            raise DocumentError("embedding_response", "向量服务返回了无效响应。", 502)
        if not response.ok:
            error = body.get("error", {})
            if not isinstance(error, dict):
                raise DocumentError("embedding_response", "向量服务返回了无效错误响应。", 502)
            message = error.get("message", "")
            if not isinstance(message, str):
                message = ""
            details = error.get("details", [])
            if not isinstance(details, list):
                details = []
            if response.status_code == 400 and re.search(
                r"token.{0,100}(?:limit|exceed|maximum|long)|(?:exceed|maximum).{0,100}token|text.{0,40}too long",
                message, re.I,
            ):
                raise InputTooLong()
            if any(isinstance(detail, dict) and detail.get("reason") == "SERVICE_DISABLED" for detail in details):
                raise DocumentError("embedding_api_disabled", "Google 项目尚未启用 Vertex AI API，请启用后继续生成向量。", 503)
            if response.status_code in (401, 403):
                raise DocumentError("embedding_permission", "Vertex AI 无法访问，请检查 ADC 身份的 Vertex AI User 权限。", 503)
            if response.status_code == 404:
                raise DocumentError("embedding_configuration", "当前项目或区域无法使用所配置的 embedding 模型。", 503)
            if response.status_code == 429:
                raise DocumentError("embedding_quota", "向量服务暂时达到调用额度，请稍后继续。", 503)
            raise DocumentError("embedding_request", "向量服务请求失败，已保存的进度可继续处理。", 502)
        try:
            embeddings = body["predictions"][0]["embeddings"]
            stats = embeddings["statistics"]
            count = stats["token_count"]
            if stats["truncated"] is True or count > MAX_TOKENS:
                raise InputTooLong()
            if stats["truncated"] is not False or isinstance(count, bool) or not isinstance(count, (int, float)) or not 0 < count <= MAX_TOKENS or int(count) != count:
                raise ValueError("Invalid token statistics")
            return normalized(embeddings["values"]), int(count)
        except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
            raise DocumentError("embedding_response", "向量服务返回了无效的 token 统计或向量。", 502) from exc
