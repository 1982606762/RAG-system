"""Exercise real viewport navigation with synthetic search results and a legacy PDF.

All API requests are intercepted; no database, cloud model or private documents
are used. Requires a running frontend, Playwright and installed Chromium.
"""
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

base_url = os.environ.get("RAG_E2E_BASE_URL", "http://127.0.0.1:3000")
output = Path(os.environ.get("RAG_E2E_OUTPUT", tempfile.mkdtemp(prefix="rag-citations-")))
output.mkdir(parents=True, exist_ok=True)
document = {
    "id": "citation-fixture", "filename": "contract-fixture.pdf", "extension": ".pdf",
    "size_bytes": 100, "status": "ready", "stage": "complete", "error_code": None,
    "error_message": None, "page_count": 3, "block_count": 2, "chunk_count": 1,
    "warnings": [], "created_at": "", "chunk_config": {},
    "blocks": [{"index": index, "kind": "paragraph", "text": "Synthetic contract excerpt",
                "page": index + 2, "bbox": None, "location": None, "section": [], "method": "text"}
               for index in range(2)],
    "chunks": [],
}
chunk = {"index": 0, "kind": "text", "text": "Synthetic contract excerpt", "section": [],
         "sources": [{"block_index": index, "page": index + 2, "start": 0, "end": 26}
                     for index in range(2)]}
document["chunks"] = [chunk]


def api(route):
    path = urlparse(route.request.url).path
    if path == "/api/auth/me":
        route.fulfill(json={"role": "owner"})
    elif path == "/api/search":
        route.fulfill(json={"items": [{"document_id": document["id"], "filename": document["filename"],
                                       "chunk_index": 0, "chunk": chunk}], "has_more": False})
    elif path == "/api/documents":
        route.fulfill(json={"items": [document], "total": 1})
    elif path == f"/api/documents/{document['id']}":
        route.fulfill(json=document)
    elif path == f"/api/documents/{document['id']}/original":
        route.fulfill(content_type="application/pdf", body=b"%PDF-1.4\nSynthetic fixture")
    elif path.startswith(f"/api/documents/{document['id']}/pages/"):
        route.fulfill(content_type="image/svg+xml", body=(
            '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800">'
            '<rect width="600" height="800" fill="white"/>'
            '<text x="50" y="80">Synthetic contract page</text></svg>'
        ))
    else:
        raise AssertionError(f"Unexpected API request: {path}")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    for label, viewport in [("desktop", {"width": 1440, "height": 1000}),
                            ("mobile", {"width": 390, "height": 844})]:
        page = browser.new_page(viewport=viewport)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/**", api)
        page.add_init_script("""
            localStorage.setItem('rag.owner.token', 'synthetic-owner-token');
            localStorage.setItem('lang', 'zh');
        """)
        page.goto(base_url)
        page.get_by_role("navigation").get_by_role("button", name="搜索", exact=True).click()
        page.get_by_role("searchbox").fill("contract")
        page.locator(".search-panel").get_by_role("button", name="搜索", exact=True).click()
        source = page.locator(".search-panel .source-links button")
        expect(source).to_have_count(2)
        # Reopen the same source, then another page in the same file, without bbox.
        for step, (index, source_page) in enumerate([(0, 2), (0, 2), (1, 3)]):
            source.nth(index).click()
            expect(page.locator(".reader h2")).to_be_in_viewport()
            expect(page.locator(".reader")).to_be_focused()
            expect(page.locator(".page-controls")).to_contain_text(f"页 {source_page} / 3")
            expect(page.locator(".page-preview > img")).to_have_attribute(
                "alt", f"contract-fixture.pdf · 页 {source_page}")
            expect(page.locator(".source-region")).to_have_count(0)
            if step < 2:
                page.get_by_role("button", name="关闭", exact=True).click()
                expect(source.nth(index)).to_be_focused()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / f"{label}-citation-navigation.png"))
        assert not errors, errors
        page.close()
    browser.close()
print("Citation browser checks passed: repeated same-file sources, PDF pages without bbox, focus, desktop/mobile.")
