"""Bounded PDF page rendering in a separate process (PDFium is not thread-safe)."""

from pathlib import Path
import subprocess
import sys

from documents.models import DocumentError

MAX_PREVIEW_SIDE = 1600


def render_page(path: Path, page: int) -> bytes:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "documents.preview", str(path.resolve()), str(page)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DocumentError("preview_timeout", "页面预览超时，请下载原件查看。", 504) from exc
    if result.returncode == 3:
        raise DocumentError("page_not_found", "找不到这个 PDF 页面。", 404)
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise DocumentError("preview_failed", "页面预览失败，请下载原件查看。", 422)
    return result.stdout


def _main():
    from io import BytesIO
    import pdfplumber

    try:
        with pdfplumber.open(sys.argv[1]) as pdf:
            index = int(sys.argv[2]) - 1
            if not 0 <= index < len(pdf.pages):
                return 3
            page = pdf.pages[index]
            left, top, right, bottom = page.cropbox
            width, height = right - left, bottom - top
            if width <= 0 or height <= 0:
                return 2
            resolution = 72 * min(2, MAX_PREVIEW_SIDE / max(width, height))
            image = page.to_image(resolution=resolution, antialias=True).original
            with BytesIO() as output:
                image.save(output, format="PNG")
                sys.stdout.buffer.write(output.getvalue())
        return 0
    except Exception:
        # The parent supplies a stable public error, never parser diagnostics.
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
