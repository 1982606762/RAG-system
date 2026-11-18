"""Owner-only keyword and semantic search over completed document chunks."""

from typing import Literal

from fastapi import APIRouter, Depends, Query

from api.deps import require_owner
from db import documents
from documents.models import DocumentError
from embeddings.retrieval import semantic_search

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
    return semantic_search(q, limit, offset)
