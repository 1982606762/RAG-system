"""Transport-independent retrieval shared by REST and MCP; no answer model."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from db import documents
from documents.models import DocumentError
from embeddings.retrieval import semantic_search

Query = Annotated[str, Field(min_length=1, max_length=200)]


class SearchRequest(BaseModel):
    query: Query
    mode: Literal['keyword', 'semantic'] = 'keyword'
    limit: int = Field(default=30, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10000)
    document_id: UUID | None = None


class KeywordRequest(BaseModel):
    queries: list[Query] = Field(min_length=1, max_length=10)
    limit: int = Field(default=30, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10000)
    document_id: UUID | None = None


def search_documents(request: SearchRequest):
    query = request.query.strip()
    if not query or '\x00' in query:
        raise DocumentError('invalid_query', '请输入有效的搜索内容。', 422)
    scope = {'document_id': request.document_id} if request.document_id else {}
    if request.mode == 'semantic':
        return semantic_search(query, request.limit, request.offset, **scope)
    return documents.search_chunks(query, request.limit, request.offset, **scope)


def search_keywords(request: KeywordRequest):
    scope = {'document_id': request.document_id} if request.document_id else {}
    return documents.search_chunk_variants(request.queries, request.limit, request.offset, **scope)
