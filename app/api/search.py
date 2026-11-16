"""Owner-only literal keyword search over completed document chunks."""

from fastapi import APIRouter, Depends, Query

from api.deps import require_owner
from db import documents as store

router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(require_owner)])


@router.get("")
def search(q: str = Query(min_length=1, max_length=200),
           limit: int = Query(30, ge=1, le=50), offset: int = Query(0, ge=0, le=10000)):
    return store.search_chunks(q, limit, offset)
