"""Owner-only keyword and semantic search over completed document chunks."""

import time
from typing import Literal

from fastapi import APIRouter, Depends, Query

from api.deps import require_owner
from db import documents, embeddings
from documents.models import DocumentError
from embeddings.provider import InputTooLong, VertexEmbedder, active_profile

router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(require_owner)])


@router.get("")
def search(q: str = Query(min_length=1, max_length=200),
           limit: int = Query(30, ge=1, le=50), offset: int = Query(0, ge=0, le=10000),
           mode: Literal["keyword", "semantic"] = "keyword"):
    if mode == "keyword":
        return documents.search_chunks(q, limit, offset)

    q = q.strip()
    if not q or '\x00' in q:
        raise DocumentError("semantic_query_invalid", "请输入有效的搜索问题。", 422)
    profile = active_profile()
    if profile is None:
        raise DocumentError("semantic_disabled", "语义搜索尚未配置，请使用关键词搜索。", 503)
    if not embeddings.has_searchable_embeddings(profile):
        raise DocumentError("semantic_index_empty", "请先为至少一份资料完成向量生成。", 409)
    try:
        with VertexEmbedder(profile, time.monotonic() + 12) as provider:
            vector, _ = provider.embed(q, task="RETRIEVAL_QUERY")
    except InputTooLong as exc:
        raise DocumentError("semantic_query_invalid", "搜索问题过长，请缩短后重试。", 422) from exc
    return embeddings.search_chunks(profile, vector, limit, offset)
