"""Adapt supported uploads to Google Document AI Layout Parser."""

from functools import lru_cache
import html
from io import BytesIO
import re

from google.api_core import exceptions
from google.auth import exceptions as auth_exceptions
from google.cloud import documentai

from core import config
from documents.models import Block, DocumentError, ParsedDocument

PROCESSOR_PATTERN = re.compile(r"projects/[^/\s]+/locations/(eu|us)/processors/[^/\s]+")


@lru_cache(maxsize=2)
def client_for(location):
    return documentai.DocumentProcessorServiceClient(
        client_options={"api_endpoint": f"{location}-documentai.googleapis.com"},
        transport="rest",
    )


def layout_blocks(blocks):
    for block in blocks:
        if "text_block" in block:
            item = block.text_block
            value = item.text.strip()
            if value:
                kind = "heading" if item.type_ == "title" or item.type_.startswith("heading") else "paragraph"
                yield kind, value
            yield from layout_blocks(item.blocks)
        elif "table_block" in block:
            table = block.table_block
            rows = [
                " | ".join(" ".join(text.replace("\n", " ") for _, text in layout_blocks(cell.blocks))
                           for cell in row.cells)
                for row in (*table.header_rows, *table.body_rows)
            ]
            if any(row.strip(" |") for row in rows):
                yield "table", "\n".join(rows)
        elif "list_block" in block:
            for entry in block.list_block.list_entries:
                yield from layout_blocks(entry.blocks)


def process_content(content, mime_type, timeout):
    processor = config.GOOGLE_DOCUMENT_AI_PROCESSOR
    match = PROCESSOR_PATTERN.fullmatch(processor)
    if not match:
        raise DocumentError("ocr_configuration", "Google Document AI 处理器配置无效。")

    if len(content) > 20_000_000:
        raise DocumentError("file_too_large", "发送到 Google 的文件超过 20 MB，请拆分文件。")
    document = documentai.RawDocument(content=content, mime_type=mime_type)
    try:
        response = client_for(match[1]).process_document(
            request=documentai.ProcessRequest(name=processor, raw_document=document),
            timeout=timeout,
            retry=None,
        )
    except (auth_exceptions.GoogleAuthError, exceptions.Forbidden, exceptions.Unauthenticated,
            exceptions.PermissionDenied, exceptions.NotFound) as exc:
        raise DocumentError("ocr_configuration", "Google Document AI 无法访问，请检查凭据、权限和处理器配置。") from exc
    except exceptions.DeadlineExceeded as exc:
        raise DocumentError("ocr_timeout", "Google Document AI OCR 超时，请重试。") from exc
    except exceptions.GoogleAPICallError as exc:
        raise DocumentError("ocr_failed", "Google Document AI OCR 请求失败，请稍后重试。") from exc

    blocks = list(layout_blocks(response.document.document_layout.blocks))
    if not blocks and (text := response.document.text.strip()):
        blocks.append(("paragraph", text))
    return blocks


def parse_google_document(path, extension, deadline):
    """Send every supported input to Layout Parser; never fall back locally."""
    from documents.parsing import check_deadline, MAX_IMAGE_PIXELS, MAX_TEXT_CHARS

    blocks = []

    def append(content, mime_type, page):
        for kind, value in process_content(content, mime_type, check_deadline(deadline)):
            blocks.append(Block(len(blocks), kind, value, page=page, method="google"))
        if sum(len(block.text) for block in blocks) > MAX_TEXT_CHARS:
            raise DocumentError("text_too_large", "解析文本过长，请拆分文件。")

    page_count = None
    if extension in (".txt", ".md"):
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentError("text_encoding", "文本文件必须使用 UTF-8 编码。") from exc
        if "\x00" in text:
            raise DocumentError("invalid_text", "文件包含二进制内容，无法作为文本读取。")
        if len(text) > MAX_TEXT_CHARS:
            raise DocumentError("text_too_large", "文本过长，请拆分文件。")
        content = f'<!doctype html><html><head><meta charset="utf-8"></head><body><pre>{html.escape(text)}</pre></body></html>'
        append(content.encode("utf-8"), "text/html", None)
    elif extension == ".pdf":
        import pypdfium2 as pdfium
        try:
            pdf = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError as exc:
            raise DocumentError("invalid_pdf", "文件内容不是有效的 PDF。") from exc
        try:
            page_count = len(pdf)
            if page_count > config.MAX_PDF_PAGES:
                raise DocumentError("too_many_pages", f"PDF 最多支持 {config.MAX_PDF_PAGES} 页，请拆分后上传。")
            for index in range(page_count):
                check_deadline(deadline)
                page_pdf = pdfium.PdfDocument.new()
                try:
                    page_pdf.import_pages(pdf, [index])
                    with BytesIO() as content:
                        page_pdf.save(content)
                        append(content.getvalue(), "application/pdf", index + 1)
                finally:
                    page_pdf.close()
        finally:
            pdf.close()
    else:
        from PIL import Image, ImageOps
        with Image.open(path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise DocumentError("image_too_large", "图片像素过大，请缩小后重试。")
            image = ImageOps.exif_transpose(image).convert("RGB")
            with BytesIO() as content:
                image.save(content, format="PDF", resolution=160)
                append(content.getvalue(), "application/pdf", 1)
        page_count = 1
    check_deadline(deadline)
    if not blocks:
        raise DocumentError("no_text", "未识别到可用文字，请检查文件内容或图片清晰度。")
    return ParsedDocument(blocks, page_count)
