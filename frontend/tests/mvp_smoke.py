"""Browser smoke test for a disposable, running MVP deployment.

Requires playwright, reportlab and installed Chromium. This uploads synthetic
fixtures to the target application. Never target the production database.
"""
import os
from pathlib import Path
import re
import tempfile
from io import BytesIO
from uuid import uuid4

from playwright.sync_api import sync_playwright, expect
from reportlab.pdfgen import canvas

base_url = os.environ.get('RAG_E2E_BASE_URL', 'http://127.0.0.1:3000')
password = os.environ['RAG_E2E_PASSWORD']
output = Path(os.environ.get('RAG_E2E_OUTPUT', tempfile.mkdtemp(prefix='rag-browser-')))
output.mkdir(parents=True, exist_ok=True)
name = f'manual-{uuid4().hex[:8]}.md'
content = ('# 设备维护手册\n\n清洁设备前，请先断开电源。\n\n'
           '## 保养周期\n\n| 部件 | 周期 | 方法 |\n| --- | --- | --- |\n'
           '| 滤网 | 每月 | 清水冲洗 |\n| 密封件 | 每年 | 检查磨损 |\n\n'
           '## 安全提醒\n\n在潮湿环境中，应缩短维护周期。\n\n'
           '<script>window.ragUnsafe = true</script>\n').encode()
errors = []

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base_url)
    page.get_by_label('访问密码').fill(password)
    page.get_by_role('button', name='登录', exact=True).click()
    expect(page.get_by_role('button', name='选择文件')).to_be_visible()
    expect(page.get_by_role('heading', name='从第一份资料开始')).to_be_visible()
    with page.expect_response(lambda response: response.url.endswith('/api/documents') and response.request.method == 'POST') as upload:
        page.locator('input[type=file]').set_input_files({'name': name, 'mimeType': 'text/markdown', 'buffer': content})
    assert upload.value.status == 200
    doc = upload.value.json()['document']
    assert doc['status'] == 'ready', doc
    expect(page.locator('.reader h2')).to_have_text(name)
    expect(page.locator('.reader')).to_contain_text('保养周期')
    page.get_by_role('button', name='分块结果', exact=True).click()
    expect(page.locator('.chunk-card').first).to_be_visible()
    page.screenshot(path=str(output / 'desktop-chunks.png'), full_page=True)
    page.get_by_role('button', name=re.compile('查看来源')).first.click()
    expect(page.locator('.original-text mark')).to_be_visible()
    page.get_by_role('button', name='原件', exact=True).click()
    expect(page.locator('.original-text')).to_contain_text('设备维护手册')
    assert page.evaluate('window.ragUnsafe') is None
    expect(page.get_by_role('button', name='选择文件')).to_be_enabled()
    page.locator('input[type=file]').set_input_files({'name': name, 'mimeType': 'text/markdown', 'buffer': content})
    expect(page.get_by_text('这份文件已存在，已打开原有记录。')).to_be_visible()
    expect(page.locator('.document-table tbody tr')).to_have_count(1)
    page.get_by_role('searchbox').fill('滤网')
    page.get_by_role('button', name='搜索', exact=True).click()
    page.locator('.search-panel .source-links button').first.click()
    expect(page.locator('.original-text mark')).to_be_visible()

    pdf_buffer = BytesIO()
    pdf = canvas.Canvas(pdf_buffer)
    for number in (1, 2):
        pdf.drawString(60, 750, f'{number}. Equipment maintenance')
        pdf.drawString(60, 710, f'Inspect the filter on page {number}. Disconnect power before cleaning.')
        pdf.showPage()
    pdf.save()
    expect(page.get_by_role('button', name='选择文件')).to_be_enabled()
    page.locator('input[type=file]').set_input_files({'name': 'equipment.pdf', 'mimeType': 'application/pdf', 'buffer': pdf_buffer.getvalue()})
    expect(page.locator('.reader h2')).to_have_text('equipment.pdf')
    page.get_by_role('button', name='提取内容', exact=True).click()
    page.get_by_role('button', name='页 2 ↗', exact=True).first.click()
    expect(page.locator('.page-preview > img')).to_have_attribute('alt', 'equipment.pdf · 页 2')
    expect(page.locator('.source-region')).to_be_visible()
    page.get_by_role('button', name='提取内容', exact=True).click()
    page.screenshot(path=str(output / 'desktop-pdf.png'), full_page=True)

    broken = b'This is not a PDF.'
    expect(page.get_by_role('button', name='选择文件')).to_be_enabled()
    page.locator('input[type=file]').set_input_files({'name': 'broken.pdf', 'mimeType': 'application/pdf', 'buffer': broken})
    expect(page.locator('.reader h2')).to_have_text('broken.pdf')
    expect(page.get_by_role('button', name='重新处理')).to_be_visible()
    page.get_by_role('button', name='重新处理').click()
    expect(page.get_by_role('button', name='重新处理')).to_be_enabled()
    expect(page.locator('.reader')).to_contain_text('文件内容不是有效的 PDF')
    with page.expect_download() as download:
        page.get_by_role('button', name='下载原件').click()
    downloaded = Path(download.value.path())
    assert downloaded.read_bytes() == broken

    page.get_by_role('button', name=re.compile(name)).click()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('button', name='分块结果', exact=True).click()
    expect(page.locator('.chunk-card').first).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile page overflows horizontally'
    page.screenshot(path=str(output / 'mobile-chunks.png'), full_page=True)
    assert not errors, errors
    print('Browser checks passed: login, upload, duplicate, chunks, search-to-original text highlight, PDF page highlight, failed retry, original download, safe text rendering, mobile layout.')
    print(f'Screenshots: {output}')
    browser.close()
