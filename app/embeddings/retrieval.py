"""Shared semantic retrieval for search and document answers."""

import time

from db import embeddings
from documents.models import DocumentError
from embeddings.provider import InputTooLong, VertexEmbedder, active_profile


def semantic_search(query, limit, offset=0, *, deadline=float("inf")):
    profile = active_profile()
    if profile is None:
        raise DocumentError("semantic_disabled", "语义搜索尚未配置，请使用关键词搜索。", 503)
    if not embeddings.has_searchable_embeddings(profile):
        raise DocumentError("semantic_index_empty", "请先为至少一份资料完成向量生成。", 409)
    try:
        with VertexEmbedder(profile, min(deadline, time.monotonic() + 12)) as provider:
            vector, _ = provider.embed(query, task="RETRIEVAL_QUERY")
    except InputTooLong as exc:
        raise DocumentError("semantic_query_invalid", "搜索问题过长，请缩短后重试。", 422) from exc
    return embeddings.search_chunks(profile, vector, limit, offset)
