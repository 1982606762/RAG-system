"""Parser output is independent of storage and retrieval providers."""

from dataclasses import asdict, dataclass, field


class DocumentError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class Block:
    index: int
    kind: str
    text: str
    page: int | None = None
    bbox: list[float] | None = None
    section: list[str] = field(default_factory=list)
    method: str = "text"
    # Original-file coordinates, independent of offsets into the extracted text.
    location: dict | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class ParsedDocument:
    blocks: list[Block]
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Chunk:
    index: int
    text: str
    section: list[str]
    sources: list[dict]
    kind: str = "text"

    def to_dict(self):
        return asdict(self)
