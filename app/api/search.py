"""Owner-only retrieval; query planning belongs to the calling LLM."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from api.deps import require_owner
from search.service import SearchRequest, search_documents, search_keywords, KeywordRequest

router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(require_owner)])


@router.get("")
def search(q: str = Query(min_length=1, max_length=200),
           limit: int = Query(30, ge=1, le=50), offset: int = Query(0, ge=0, le=10000),
           mode: Literal["keyword", "semantic"] = "keyword", document_id: UUID | None = None):
    return search_documents(SearchRequest(query=q, mode=mode, limit=limit, offset=offset,
                                          document_id=document_id))


@router.post("/keywords")
def keywords(request: KeywordRequest):
    return search_keywords(request)
