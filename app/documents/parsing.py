"""Local text/PDF extraction and bounded, sequential OCR."""

from collections import defaultdict
from pathlib import Path
import re
import time

from core import config
from documents.models import Block, DocumentError, ParsedDocument

PARSER_VERSION = "local-blocks-v2"
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"}
MAX_TEXT_CHARS = 1_000_000
MAX_IMAGE_PIXELS = 25_000_000


def check_deadline(deadline: float):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DocumentError("processing_timeout", "处理超时，请拆分文件后重试。")
    return remaining


def parse_text(path: Path, markdown: bool) -> ParsedDocument:
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentError("text_encoding", "文本文件必须使用 UTF-8 编码。") from exc
    if "\x00" in text:
        raise DocumentError("invalid_text", "文件包含二进制内容，无法作为文本读取。")
    if len(text) > MAX_TEXT_CHARS:
        raise DocumentError("text_too_large", "文本过长，请拆分文件。")
    blocks: list[Block] = []
    section: list[str] = []
    paragraph: list[str] = []
    positions: list[dict] = []
    fence: str | None = None

    def flush(kind="paragraph"):
        value = "\n".join(paragraph).strip()
        if value:
            location = {**positions[0], "end": positions[-1]["end"], "end_line": positions[-1]["end_line"]}
            blocks.append(Block(len(blocks), kind, value, section=list(section), location=location))
        paragraph.clear()
        positions.clear()

    offset = 0
    for line_number, raw_line in enumerate(text.splitlines(keepends=True), 1):
        line = raw_line.rstrip("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")
        position = {"type": "text", "start": offset, "end": offset + len(line),
                    "start_line": line_number, "end_line": line_number}
        offset += len(raw_line)
        if markdown and fence is None and len(paragraph) > 1 and re.match(r"^\s*\|?\s*:?-{3,}", paragraph[1]) and "|" not in line:
            flush()
        marker = re.match(r"^\s*(`{3,}|~{3,})", line) if markdown else None
        if marker and fence is None:
            flush()
            fence = marker.group(1)
            paragraph.append(line)
            positions.append(position)
            continue
        if fence is not None:
            paragraph.append(line)
            positions.append(position)
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                flush("code")
                fence = None
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if markdown else None
        if heading:
            flush()
            level = len(heading.group(1))
            section = section[:level - 1] + [heading.group(2)]
            blocks.append(Block(len(blocks), "heading", heading.group(2), section=list(section), location=position))
        elif not line.strip():
            flush()
        else:
            # Markdown table rows remain together, even without blank separators.
            if markdown and "|" in line and paragraph and re.match(r"^\s*\|?\s*:?-{3,}", line):
                header = paragraph.pop()
                header_position = positions.pop()
                flush()
                paragraph.append(header)
                paragraph.append(line)
                positions.extend([header_position, position])
            else:
                paragraph.append(line)
                positions.append(position)
    flush("code" if fence else "paragraph")
    for block in blocks:
        lines = block.text.splitlines()
        if markdown and block.kind == "paragraph" and len(lines) > 1 and re.match(r"^\s*\|?\s*:?-{3,}", lines[1]):
            block.kind = "table"
            block.text = "\n".join([lines[0], *lines[2:]])
    return ParsedDocument(blocks)


def ocr_image(image, page: int, deadline: float, blocks: list[Block], warnings: list[str]):
    from PIL import ImageOps

    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise DocumentError("image_too_large", "图片像素过大，请缩小后重试。")
    image = ImageOps.exif_transpose(image).convert("RGB")
    import pytesseract

    try:
        data = pytesseract.image_to_data(
            image, lang=config.OCR_LANGUAGES, output_type=pytesseract.Output.DICT,
            timeout=min(45, check_deadline(deadline)),
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise DocumentError("ocr_unavailable", "需要 OCR，但服务未安装 Tesseract。请安装后重试。") from exc
    except pytesseract.TesseractError as exc:
        raise DocumentError("ocr_failed", "OCR 失败，请检查识别语言包和图片质量。") from exc
    except RuntimeError as exc:
        raise DocumentError("ocr_timeout", "OCR 超时，请缩小图片或拆分文件后重试。") from exc
    groups = defaultdict(list)
    for i, word in enumerate(data["text"]):
        if word.strip():
            key = (data["block_num"][i], data["par_num"][i])
            groups[key].append(i)
    for indices in groups.values():
        lines = defaultdict(list)
        for i in indices:
            lines[data["line_num"][i]].append(data["text"][i])
        text = "\n".join(" ".join(words) for words in lines.values())
        # Keep the legacy point-coordinate bbox empty; location has an explicit
        # normalized coordinate system shared by PDF and image previews.
        blocks.append(Block(len(blocks), "paragraph", text, page=page, method="ocr"))
        if all(key in data for key in ("left", "top", "width", "height")):
            from documents.locations import pdf_location
            box = [min(data["left"][i] for i in indices), min(data["top"][i] for i in indices),
                   max(data["left"][i] + data["width"][i] for i in indices),
                   max(data["top"][i] + data["height"][i] for i in indices)]
            blocks[-1].location = pdf_location(page, box, [0, 0, image.width, image.height])
    if not groups:
        warnings.append(f"第 {page} 页 OCR 未识别到文字，请核对原件。")
    elif any(0 <= float(data["conf"][i]) < 50 for indices in groups.values() for i in indices):
        warnings.append(f"第 {page} 页部分 OCR 文字置信度较低，请核对原件。")


def parse_pdf(path: Path, deadline: float) -> ParsedDocument:
    import pdfplumber

    blocks: list[Block] = []
    warnings: list[str] = []
    section: list[str] = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        if page_count > config.MAX_PDF_PAGES:
            raise DocumentError("too_many_pages", f"PDF 最多支持 {config.MAX_PDF_PAGES} 页，请拆分后上传。")
        for page_number, page in enumerate(pdf.pages, 1):
            check_deadline(deadline)
            text = page.extract_text() or ""
            image_area = sum(max(0, image["x1"] - image["x0"]) * max(0, image["bottom"] - image["top"])
                             for image in page.images)
            scanned = len(text.strip()) < 20 or (image_area > page.width * page.height * .6 and len(text.strip()) < 150)
            if scanned and (page.images or text.strip()):
                if page.width * page.height * (160 / 72) ** 2 > MAX_IMAGE_PIXELS:
                    raise DocumentError("image_too_large", "PDF 页面尺寸过大，请缩小后重试。")
                ocr_image(page.to_image(resolution=160).original, page_number, deadline, blocks, warnings)
                warnings.append(f"第 {page_number} 页使用 OCR；表格布局和数字需核对原件。")
                page.close()
                continue
            if not text.strip():
                warnings.append(f"第 {page_number} 页没有可提取文字。")
                page.close()
                continue
            if page.images:
                warnings.append(f"第 {page_number} 页包含图片；文字层已提取，图片内容未单独识别。")
            tables = [table for table in page.find_tables() if len(table.rows) > 1]
            boxes = [table.bbox for table in tables]

            def outside_tables(obj):
                x = (obj.get("x0", 0) + obj.get("x1", 0)) / 2
                y = (obj.get("top", 0) + obj.get("bottom", 0)) / 2
                return not any(x0 <= x <= x1 and top <= y <= bottom for x0, top, x1, bottom in boxes)

            events = []
            for line in page.filter(outside_tables).extract_text_lines():
                value = line["text"].strip()
                if value:
                    events.append((line["top"], line["x0"], "line", value,
                                   [line["x0"], line["top"], line["x1"], line["bottom"]]))
            for table in tables:
                rows = table.extract()
                value = "\n".join(" | ".join((cell or "").replace("\n", " ") for cell in row) for row in rows)
                events.append((table.bbox[1], table.bbox[0], "table", value, list(table.bbox)))
            pending = None

            def flush():
                nonlocal pending
                if pending:
                    blocks.append(Block(len(blocks), "paragraph", pending[0], page_number,
                                        pending[1], list(section)))
                    pending = None

            for _, _, kind, value, bbox in sorted(events):
                heading = len(value) < 160 and re.match(r"^(?:\d+(?:\.\d+)*[.)]?\s+|第.{1,12}[章节]\s*)\S", value)
                if kind == "table" or heading:
                    flush()
                    if heading and kind != "table":
                        section = [value]
                    blocks.append(Block(len(blocks), "table" if kind == "table" else "heading",
                                        value, page_number, bbox, list(section)))
                elif pending and bbox[1] - pending[1][3] < max(5, (bbox[3] - bbox[1]) * .8) and abs(bbox[0] - pending[1][0]) < 30:
                    pending[0] += "\n" + value
                    pending[1] = [min(pending[1][0], bbox[0]), pending[1][1], max(pending[1][2], bbox[2]), bbox[3]]
                else:
                    flush()
                    pending = [value, bbox]
            flush()
            # pdfplumber uses top-left coordinates on the rotated media box;
            # both the page preview and OCR render the crop box instead.
            from documents.locations import displayed_cropbox, pdf_location
            cropbox = displayed_cropbox(page)
            for block in blocks:
                if block.page == page_number and block.bbox:
                    block.location = pdf_location(page_number, block.bbox, cropbox)
            if sum(len(block.text) for block in blocks) > MAX_TEXT_CHARS:
                raise DocumentError("text_too_large", "解析文本过长，请拆分文件。")
            page.close()
    return ParsedDocument(blocks, page_count, warnings)


def parse_document(path: Path, extension: str) -> ParsedDocument:
    deadline = time.monotonic() + config.PROCESSING_TIMEOUT_SECONDS
    if config.GOOGLE_DOCUMENT_AI_PROCESSOR:
        from documents.google_ocr import parse_google_document
        return parse_google_document(path, extension, deadline)
    if extension in (".txt", ".md"):
        result = parse_text(path, extension == ".md")
    elif extension == ".pdf":
        with path.open("rb") as source:
            signature = source.read(1024)
        if not signature.lstrip().startswith(b"%PDF-"):
            raise DocumentError("invalid_pdf", "文件内容不是有效的 PDF。")
        result = parse_pdf(path, deadline)
    else:
        from PIL import Image
        result = ParsedDocument([], 1, ["图片使用 OCR；请核对表格布局和识别文字。"])
        with Image.open(path) as image:
            ocr_image(image, 1, deadline, result.blocks, result.warnings)
    check_deadline(deadline)
    if not result.blocks:
        raise DocumentError("no_text", "未识别到可用文字，请检查文件内容或图片清晰度。")
    if sum(len(block.text) for block in result.blocks) > MAX_TEXT_CHARS:
        raise DocumentError("text_too_large", "解析文本过长，请拆分文件。")
    return result
