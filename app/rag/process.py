"""Processing layer — file -> Claude API -> two-layer structured JSON.

A file (image or PDF) cannot be embedded directly — RAG only works on text.
We send the file to Claude and get back a two-layer JSON:
    common layer  -> fields every document has (doc_type, date, vendor, ...)
    details layer -> fields Claude freely decides based on the content.

Supported formats:
    Images (JPEG, PNG, GIF, WEBP) -> sent as "image" content block
    PDFs                          -> sent as "document" content block (Anthropic native PDF)
"""

import base64
import json
import mimetypes

import anthropic

from core.config import CLAUDE_MODEL


EXTRACTION_PROMPT = """你是一个文档分析助手。仔细查看这个文件，返回一个 JSON 对象。

JSON 必须包含以下"通用层"字段（没有就填 null）：
- doc_type: 文件类型，英文单词，如 invoice/receipt/contract/manual/warranty/id_card/music_score/photo/other
- doc_date: 主要日期，格式 YYYY-MM-DD，没有则 null
- vendor: 商家/机构/相关方名称，没有则 null
- amount: 金额数字（只要数字），没有则 null
- currency: 货币代码，如 CNY/EUR/USD/DKK，没有则 null
- summary: 一句话中文摘要，不超过30字
- tags: 关键词列表，最多5个中文标签

另外必须包含一个 "details" 对象，由你根据文件类型自由决定字段。

严格要求：只返回 JSON，不要任何解释、不要 markdown 代码块标记。"""


def _build_content_item(path: str) -> dict:
    """Return the Anthropic content block for the file (image or PDF)."""
    media_type, _ = mimetypes.guess_type(path)
    if media_type is None:
        media_type = "image/jpeg"

    with open(path, "rb") as f:
        data_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    if media_type == "application/pdf":
        # Anthropic's native PDF support: the model reads each page directly.
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data_b64},
        }
    else:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data_b64},
        }


def _parse_json_response(raw: str) -> dict:
    """Strip optional markdown fences and parse JSON from Claude's reply."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_parse_error": True, "_raw": raw}


# Module-level singleton — creating Anthropic() is cheap, but one instance is enough.
_client = anthropic.Anthropic()


def process_file(path: str) -> dict:
    """Send an image or PDF to Claude and return the two-layer structured JSON."""
    content_item = _build_content_item(path)
    message = _client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [content_item, {"type": "text", "text": EXTRACTION_PROMPT}],
        }],
    )
    return _parse_json_response(message.content[0].text)


# Backward-compat alias so existing code that calls process_image still works.
process_image = process_file


def build_embedding_text(doc: dict) -> str:
    """Flatten the JSON into a Chinese narrative for embedding.

    A narrative sentence embeds better than raw JSON, because the embedding
    model was trained on natural language, not on {"key": "value"} syntax.
    """
    parts = []
    if doc.get("doc_type"):
        parts.append(f"文件类型：{doc['doc_type']}")
    if doc.get("doc_date"):
        parts.append(f"日期：{doc['doc_date']}")
    if doc.get("vendor"):
        parts.append(f"相关方：{doc['vendor']}")
    if doc.get("amount"):
        parts.append(f"金额：{doc['amount']} {doc.get('currency') or ''}".strip())
    if doc.get("summary"):
        parts.append(f"摘要：{doc['summary']}")
    if doc.get("tags"):
        parts.append("标签：" + "、".join(doc["tags"]))
    for k, v in (doc.get("details") or {}).items():
        parts.append(f"{k}：{v}")
    return "；".join(parts)
