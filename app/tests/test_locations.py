"""Original-file mappings, rendered geometry and private page previews."""

from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen import canvas

from test_shell import app, PASSWORD
from core import config
from documents.locations import map_unique_text
from documents.models import Block, DocumentError
from documents.parsing import parse_document
from documents.preview import render_page


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(config, 'GOOGLE_DOCUMENT_AI_PROCESSOR', ''))

    def test_markdown_positions_retain_bom_crlf_emoji_and_table_syntax(self):
        original = '# 😀手册\r\n\r\n  清洁滤网。  \r\n\r\n| 部件 | 周期 |\r\n| --- | --- |\r\n| 滤网 | 每月 |\r\n'
        path = self.directory / 'manual.md'
        path.write_bytes(b'\xef\xbb\xbf' + original.encode())
        blocks = parse_document(path, '.md').blocks
        self.assertEqual([b.kind for b in blocks], ['heading', 'paragraph', 'table'])
        self.assertEqual([(b.location['start_line'], b.location['end_line']) for b in blocks], [(1, 1), (3, 3), (5, 7)])
        slices = [original[b.location['start']:b.location['end']] for b in blocks]
        self.assertEqual(slices, ['# 😀手册', '  清洁滤网。  ', '| 部件 | 周期 |\r\n| --- | --- |\r\n| 滤网 | 每月 |'])
        self.assertNotIn('---', blocks[-1].text)

    def test_duplicate_paragraphs_and_fenced_code_have_distinct_original_ranges(self):
        original = 'same\n\nsame\n\n```python\n# heading in code\n```\n'
        path = self.directory / 'code.md'
        path.write_text(original)
        blocks = parse_document(path, '.md').blocks
        self.assertEqual([b.location['start'] for b in blocks], [0, 6, 12])
        self.assertEqual(original[blocks[-1].location['start']:blocks[-1].location['end']], '```python\n# heading in code\n```')

    def test_provider_mapping_only_accepts_unique_exact_text(self):
        original = '😀 Header\r\n\r\nUnique text\r\nRepeated\r\nRepeated\r\nChanged   spacing'
        blocks = [Block(i, 'paragraph', value) for i, value in enumerate(['Unique text', 'Repeated', 'Changed spacing'])]
        map_unique_text(blocks, original)
        self.assertEqual(blocks[0].location, {'type': 'text', 'start': 12, 'end': 23, 'start_line': 3, 'end_line': 3})
        self.assertIsNone(blocks[1].location)
        self.assertIsNone(blocks[2].location)

    def test_google_text_parser_maps_original_without_trusting_rewritten_text(self):
        path = self.directory / 'google.txt'
        path.write_bytes(b'\xef\xbb\xbfOriginal text\r\n\r\nAnother   paragraph')
        with patch.object(config, 'GOOGLE_DOCUMENT_AI_PROCESSOR', 'configured'), \
                patch('documents.google_ocr.process_content', return_value=[('paragraph', 'Original text'), ('paragraph', 'Another paragraph')]):
            blocks = parse_document(path, '.txt').blocks
        self.assertEqual(blocks[0].location['start'], 0)
        self.assertEqual(blocks[0].location['end'], len('Original text'))
        self.assertIsNone(blocks[1].location)

    def test_pdf_regions_match_rendered_crop_box_and_rotated_pages(self):
        import pypdfium2 as pdfium
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source = self.directory / 'source.pdf'
                pdf = canvas.Canvas(str(source), pagesize=(600, 800))
                pdf.setFont('Helvetica', 16)
                pdf.drawString(60, 700, '1. Source paragraph to highlight')
                pdf.save()
                path = self.directory / f'cropped-{rotation}.pdf'
                with pdfium.PdfDocument(source) as document:
                    page = document[0]
                    page.set_cropbox(20, 20, 500, 780)
                    page.set_rotation(rotation)
                    document.save(path)
                    page.close()
                blocks = parse_document(path, '.pdf').blocks
                with Image.open(BytesIO(render_page(path, 1))) as image:
                    self.assertLessEqual(max(image.size), 1601)
                    # Independently find the rasterized text. Every dark pixel
                    # should lie in one of the normalized source regions.
                    dark = [(x / image.width, y / image.height) for y in range(image.height) for x in range(image.width)
                            if max(image.getpixel((x, y))[:3]) < 100]
                self.assertGreater(len(dark), 100)
                boxes = [b.location['bbox'] for b in blocks if b.location and 'bbox' in b.location]
                covered = sum(any(x0 - .005 <= x <= x1 + .005 and y0 - .005 <= y <= y1 + .005
                                  for x0, y0, x1, y1 in boxes) for x, y in dark)
                self.assertGreater(covered / len(dark), .95)

    def test_preview_missing_page_bad_pdf_and_timeout_have_stable_errors(self):
        path = self.directory / 'document.pdf'
        pdf = canvas.Canvas(str(path))
        pdf.drawString(60, 700, 'A page')
        pdf.save()
        with self.assertRaises(DocumentError) as caught:
            render_page(path, 2)
        self.assertEqual(caught.exception.code, 'page_not_found')
        path.write_text('not a PDF')
        with self.assertRaises(DocumentError) as caught:
            render_page(path, 1)
        self.assertEqual(caught.exception.code, 'preview_failed')
        with patch('documents.preview.subprocess.run', side_effect=subprocess.TimeoutExpired('render', 30)):
            with self.assertRaises(DocumentError) as caught:
                render_page(path, 1)
        self.assertEqual(caught.exception.code, 'preview_timeout')


class PreviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        self.headers = {'Authorization': f'Bearer {token}'}
        self.url = '/api/documents/00000000-0000-0000-0000-000000000001/pages/1/preview'

    def test_preview_requires_owner_and_valid_page_before_storage(self):
        with patch('db.documents.connect') as connect:
            self.assertEqual(self.client.get(self.url).status_code, 401)
            for page in (0, 51, 'bad'):
                self.assertEqual(self.client.get(self.url.replace('/1/preview', f'/{page}/preview'), headers=self.headers).status_code, 422)
            connect.assert_not_called()

    def test_preview_response_is_private_and_uses_original_uuid_path(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, 'DOCUMENTS_DIR', Path(directory)):
            path = Path(directory) / '00000000-0000-0000-0000-000000000001.pdf'
            path.write_bytes(b'original')
            with patch('db.documents.connect'), patch('db.documents.get_document', return_value={'extension': '.pdf'}), \
                    patch('api.documents.render_page', return_value=b'png') as render:
                response = self.client.get(self.url, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['content-type'], 'image/png')
                self.assertEqual(response.headers['cache-control'], 'no-store')
                render.assert_called_once_with(path, 1)
            with patch('db.documents.connect'), patch('db.documents.get_document', return_value={'extension': '.md'}):
                self.assertEqual(self.client.get(self.url, headers=self.headers).status_code, 415)


if __name__ == '__main__':
    unittest.main()
