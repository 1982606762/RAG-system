"""Search all translated keyword alternatives before deduplicating and paginating."""

import time

from db import documents
from documents.models import DocumentError
from search.expansion import expand_query, validate_query


def multilingual_search(query, limit, offset=0, *, deadline=float('inf'), document_id=None):
    query = validate_query(query)
    queries = expand_query(query, deadline=deadline)
    # Preserve exact source-language text/identifiers as an additional alternative.
    variants = [query] if len(query.split()) <= 10 else []
    variants.extend(variant for group in queries.values() for variant in group)
    variants = list(dict.fromkeys(variants))
    if time.monotonic() >= deadline:
        raise DocumentError('multilingual_timeout', '多语言搜索超时，请重试。', 504)
    result = documents.search_chunk_variants(variants, limit, offset, document_id=document_id)
    return {**result, 'queries': queries}
