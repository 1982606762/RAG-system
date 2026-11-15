"""Structure-first splitting with an explicit Unicode-character budget.

No embedding model has been selected. Character counts are deliberately not
reported as tokens. Source offsets always refer to the stored block text.
"""

import re

from documents.models import Block, Chunk

CHUNKER_VERSION = "structure-chars-v1"
TARGET_CHARS = 1600
MAX_CHARS = 2400
OVERLAP_CHARS = 200
SENTENCE_BOUNDARY = r"[。！？]|[.!?](?:\s|$)|\n"


def split_spans(text: str, limit: int, overlap: int = 0):
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            boundaries = list(re.finditer(SENTENCE_BOUNDARY, text[start:end]))
            candidates = [start + match.end() for match in boundaries
                          if match.end() >= limit // 2]
            if candidates:
                end = candidates[-1]
        yield start, end
        if end == len(text):
            break
        next_start = end
        if overlap:
            tail = text[max(start + 1, end - overlap):end]
            boundary = re.search(SENTENCE_BOUNDARY, tail)
            if boundary:
                next_start = end - len(tail) + boundary.end()
            # Do not invent a sentence boundary or duplicate an entire chunk.
        start = max(start + 1, next_start)


def source(block: Block, start: int, end: int):
    return {"block_index": block.index, "page": block.page,
            "start": start, "end": end}


def chunk_blocks(blocks: list[Block], target: int = TARGET_CHARS,
                 maximum: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[Chunk]:
    if not 0 <= overlap < target <= maximum:
        raise ValueError("Expected 0 <= overlap < target <= maximum")
    chunks: list[Chunk] = []
    pending: list[tuple[Block, int, int]] = []

    def emit(parts, kind="text"):
        if not parts:
            return
        text = "\n\n".join(block.text[start:end] for block, start, end in parts)
        chunks.append(Chunk(len(chunks), text, parts[0][0].section,
                            [source(*part) for part in parts], kind))

    def flush():
        emit(pending)
        pending.clear()

    for block in blocks:
        if not block.text.strip():
            continue
        if block.kind in ("heading", "table", "code"):
            flush()
        if block.kind == "heading":
            pending.append((block, 0, len(block.text)))
            # Pathological headings still obey the hard limit.
            if len(block.text) > maximum:
                pending.clear()
                for start, end in split_spans(block.text, maximum):
                    emit([(block, start, end)])
            continue
        if block.kind == "table":
            header_end = block.text.find("\n")
            if header_end < 0 or header_end > maximum // 3:
                for start, end in split_spans(block.text, maximum):
                    emit([(block, start, end)], "table")
                continue
            header = (block, 0, header_end)
            parts = [header]
            size = header_end
            offset = header_end + 1
            for line in block.text[offset:].splitlines(keepends=True):
                line_end = offset + len(line.rstrip("\r\n"))
                for start, end in split_spans(block.text[offset:line_end], maximum - header_end - 2):
                    part = (block, offset + start, offset + end)
                    if size + 2 + end - start > maximum:
                        emit(parts, "table")
                        parts, size = [header], header_end
                    parts.append(part)
                    size += 2 + end - start
                offset += len(line)
            if len(parts) > 1:
                emit(parts, "table")
            else:
                emit([header], "table")
            continue
        if block.kind == "code":
            for start, end in split_spans(block.text, maximum):
                emit([(block, start, end)], "code")
            continue
        if pending and pending[0][0].section != block.section:
            flush()
        if len(block.text) > maximum:
            flush()
            for start, end in split_spans(block.text, target, overlap):
                emit([(block, start, end)])
            continue
        size = sum(end - start for _, start, end in pending) + 2 * len(pending)
        if pending and size + len(block.text) > target:
            flush()
        pending.append((block, 0, len(block.text)))
    flush()
    return chunks
