"""Mappings to immutable originals, separate from chunk-to-block offsets."""

from bisect import bisect_right
import math


def displayed_cropbox(page):
    """Express the raw PDF crop box in pdfplumber's displayed coordinates.

    A rotated asymmetric crop cannot be obtained by only swapping its axes.
    Use the same media-relative rotation as pdfminer, then add pdfplumber's
    media-box origin. PDFium displays the intersection of crop and media boxes.
    """
    mx0, my0, mx1, my1 = page.page_obj.mediabox
    cx0, cy0, cx1, cy1 = page.page_obj.cropbox
    cx0, cy0, cx1, cy1 = max(mx0, cx0), max(my0, cy0), min(mx1, cx1), min(my1, cy1)
    points = []
    for x, y in ((cx0, cy0), (cx1, cy1)):
        if page.rotation == 90:
            point = y - my0, x - mx0
        elif page.rotation == 180:
            point = mx1 - x, y - my0
        elif page.rotation == 270:
            point = my1 - y, mx1 - x
        else:
            point = x - mx0, my1 - y
        points.append((point[0] + page.mediabox[0], point[1] + page.mediabox[1]))
    return [min(x for x, _ in points), min(y for _, y in points),
            max(x for x, _ in points), max(y for _, y in points)]


def pdf_location(page, bbox, cropbox):
    """Convert pdfplumber's points to a top-left, normalized crop-box region."""
    left, top, right, bottom = cropbox
    if right <= left or bottom <= top or not all(math.isfinite(n) for n in [*bbox, *cropbox]):
        return {"type": "page", "page": page}
    x0, y0, x1, y1 = bbox
    region = [max(0, (x0 - left) / (right - left)), max(0, (y0 - top) / (bottom - top)),
              min(1, (x1 - left) / (right - left)), min(1, (y1 - top) / (bottom - top))]
    if region[0] >= region[2] or region[1] >= region[3]:
        return {"type": "page", "page": page}
    return {"type": "page", "page": page, "bbox": region}


def map_unique_text(blocks, original):
    """A provider may rewrite/reorder text. Map only unambiguous exact matches.

    Offsets count Unicode code points in UTF-8-sig decoded text, retaining CRLF.
    Normalized or repeated text deliberately has no original-text highlight.
    """
    starts = [0]
    offset = 0
    for line in original.splitlines(keepends=True):
        offset += len(line)
        starts.append(offset)
    for block in blocks:
        if not block.text:
            continue
        start = original.find(block.text)
        if start < 0 or original.find(block.text, start + 1) >= 0:
            continue
        end = start + len(block.text)
        block.location = {"type": "text", "start": start, "end": end,
                          "start_line": bisect_right(starts, start), "end_line": bisect_right(starts, end - 1)}
