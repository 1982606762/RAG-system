"""Extraction and API boundary tests; no user files or running DB required."""

from pathlib import Path
import tempfile
import shutil
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

from test_shell import app, PASSWORD
from core import config
from documents.models import Block, DocumentError
from documents.chunking import chunk_blocks
from documents.parsing import parse_document, ocr_image


def create_pdf(path, pages=1, table=False):
    pdf = canvas.Canvas(str(path), pagesize=(600, 800))
    for index in range(pages):
        pdf.setFont('Helvetica', 16)
        pdf.drawString(50, 740, f'{index + 1}. Maintenance')
        pdf.setFont('Helvetica', 11)
        pdf.drawString(50, 710, 'Disconnect power before cleaning the equipment.')
        pdf.drawString(50, 695, 'Use a dry cloth and check all seals carefully.')
        if table:
            for x in [50, 220, 390]:
                pdf.line(x, 500, x, 620)
            for y in [500, 540, 580, 620]:
                pdf.line(50, y, 390, y)
            for y, left, right in [(595, 'Part', 'Interval'), (555, 'Filter', 'Monthly'), (515, 'Seal', 'Yearly')]:
                pdf.drawString(60, y, left)
                pdf.drawString(230, y, right)
        pdf.showPage()
    pdf.save()


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_markdown_preserves_sections_code_tables_and_chinese(self):
        path = self.directory / 'manual.md'
        path.write_text('# 手册\n\n维护说明。\n\n## Maintenance\n\nClean carefully.\n\n'
                        '| Part | Interval |\n| --- | --- |\n| Filter | Monthly |\n\n'
                        '```python\n# not a heading\nprint("hello")\n```\n', encoding='utf-8')
        parsed = parse_document(path, '.md')
        self.assertEqual([b.kind for b in parsed.blocks], ['heading', 'paragraph', 'heading', 'paragraph', 'table', 'code'])
        self.assertEqual(parsed.blocks[4].section, ['手册', 'Maintenance'])
        self.assertIn('Filter', parsed.blocks[4].text)
        self.assertIn('# not a heading', parsed.blocks[5].text)

    def test_invalid_encoding_binary_and_empty_text_fail_explicitly(self):
        path = self.directory / 'text.txt'
        for contents, code in [(b'\xff', 'text_encoding'), (b'hello\x00world', 'invalid_text'), (b'  ', 'no_text')]:
            path.write_bytes(contents)
            with self.subTest(code=code), self.assertRaises(DocumentError) as caught:
                parse_document(path, '.txt')
            self.assertEqual(caught.exception.code, code)

    def test_pdf_extracts_text_and_tables_without_duplicate_table_text(self):
        path = self.directory / 'manual.pdf'
        create_pdf(path, pages=2, table=True)
        parsed = parse_document(path, '.pdf')
        self.assertEqual(parsed.page_count, 2)
        self.assertEqual({b.page for b in parsed.blocks}, {1, 2})
        tables = [b for b in parsed.blocks if b.kind == 'table']
        self.assertEqual(len(tables), 2)
        self.assertIn('Filter | Monthly', tables[0].text)
        self.assertFalse(any('Filter' in b.text for b in parsed.blocks if b.kind != 'table'))
        self.assertTrue(all(b.bbox for b in parsed.blocks))

    def test_pdf_page_limit_and_invalid_signature(self):
        path = self.directory / 'manual.pdf'
        create_pdf(path, pages=2)
        with patch.object(config, 'MAX_PDF_PAGES', 1), self.assertRaises(DocumentError) as caught:
            parse_document(path, '.pdf')
        self.assertEqual(caught.exception.code, 'too_many_pages')
        path.write_text('not a PDF')
        with self.assertRaises(DocumentError) as caught:
            parse_document(path, '.pdf')
        self.assertEqual(caught.exception.code, 'invalid_pdf')

    def test_ocr_grouping_preserves_page_and_marks_low_confidence(self):
        data = {'text': ['Hello', 'world'], 'block_num': [1, 1], 'par_num': [1, 1],
                'line_num': [1, 1], 'conf': [95, 40]}
        blocks, warnings = [], []
        with patch('pytesseract.image_to_data', return_value=data) as recognize:
            ocr_image(Image.new('RGB', (200, 100)), 3, time.monotonic() + 30, blocks, warnings)
        self.assertEqual(blocks[0].text, 'Hello world')
        self.assertEqual(blocks[0].page, 3)
        self.assertEqual(blocks[0].method, 'ocr')
        self.assertTrue(warnings)
        self.assertLessEqual(recognize.call_args.kwargs['timeout'], 30)

    def test_scanned_pdf_routes_to_ocr(self):
        path = self.directory / 'scan.pdf'
        Image.new('RGB', (600, 800), 'white').save(path, 'PDF')
        def recognize(image, page, deadline, blocks, warnings):
            blocks.append(Block(0, 'paragraph', 'Scanned text', page=page, method='ocr'))
        with patch('documents.parsing.ocr_image', side_effect=recognize):
            result = parse_document(path, '.pdf')
        self.assertEqual(result.blocks[0].method, 'ocr')
        self.assertEqual(result.blocks[0].page, 1)

    def test_markdown_table_does_not_swallow_following_paragraph(self):
        path = self.directory / 'table.md'
        path.write_text('| Part | Cycle |\n| --- | --- |\n| Filter | Monthly |\nFollowing paragraph.\n')
        result = parse_document(path, '.md')
        self.assertEqual([block.kind for block in result.blocks], ['table', 'paragraph'])
        self.assertEqual(result.blocks[1].text, 'Following paragraph.')

    @unittest.skipUnless(shutil.which('tesseract'), 'Native OCR needs the Tesseract executable')
    def test_native_ocr_recognizes_image_and_scanned_pdf(self):
        image = Image.new('RGB', (1200, 400), 'white')
        draw = ImageDraw.Draw(image)
        draw.multiline_text((50, 50), 'FILTER MAINTENANCE\nClean the filter every month.\nDisconnect power before cleaning.',
                            font=ImageFont.load_default(size=40), fill='black', spacing=20)
        for extension, image_format in [('.png', 'PNG'), ('.pdf', 'PDF')]:
            path = self.directory / ('scan' + extension)
            image.save(path, image_format)
            with self.subTest(extension=extension):
                result = parse_document(path, extension)
                text = ' '.join(block.text for block in result.blocks).lower()
                self.assertIn('filter', text)
                self.assertIn('month', text)
                self.assertTrue(all(block.method == 'ocr' for block in result.blocks))


class ChunkingTests(unittest.TestCase):
    def assert_sources(self, blocks, chunks, maximum):
        by_id = {b.index: b for b in blocks}
        covered = {b.index: set() for b in blocks}
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), maximum)
            reconstructed = []
            for source in chunk.sources:
                block = by_id[source['block_index']]
                self.assertEqual(source['page'], block.page)
                self.assertTrue(0 <= source['start'] < source['end'] <= len(block.text))
                reconstructed.append(block.text[source['start']:source['end']])
                covered[block.index].update(range(source['start'], source['end']))
            self.assertEqual(chunk.text, '\n\n'.join(reconstructed))
        for block in blocks:
            self.assertTrue(all(i in covered[block.index] for i, char in enumerate(block.text) if not char.isspace()))

    def test_long_multilingual_text_is_bounded_and_has_exact_source_offsets(self):
        text = ('这是维护说明。注意检查密封件！ ' * 80) + ('Clean the filter carefully. ' * 80)
        blocks = [Block(0, 'paragraph', text, page=2, section=['Maintenance'])]
        chunks = chunk_blocks(blocks, target=180, maximum=260, overlap=35)
        self.assertGreater(len(chunks), 3)
        self.assert_sources(blocks, chunks, 260)
        self.assertTrue(any(a.sources[-1]['end'] > b.sources[0]['start'] for a, b in zip(chunks, chunks[1:])))

    def test_sections_do_not_merge_and_page_breaks_can_merge(self):
        blocks = [Block(0, 'heading', 'Install', section=['Install']),
                  Block(1, 'paragraph', 'First part', page=1, section=['Install']),
                  Block(2, 'paragraph', 'continued', page=2, section=['Install']),
                  Block(3, 'heading', 'Repair', section=['Repair']),
                  Block(4, 'paragraph', 'Other topic', page=2, section=['Repair'])]
        chunks = chunk_blocks(blocks)
        self.assertEqual(len(chunks), 2)
        self.assertEqual({s['page'] for s in chunks[0].sources}, {None, 1, 2})
        self.assert_sources(blocks, chunks, 2400)

    def test_chinese_sentences_without_spaces_are_not_split_mid_sentence(self):
        text = '请先断开电源。然后清洁滤网。最后检查密封。' * 20
        blocks = [Block(0, 'paragraph', text)]
        chunks = chunk_blocks(blocks, target=40, maximum=60, overlap=10)
        self.assertTrue(all(chunk.text.endswith('。') for chunk in chunks))
        self.assert_sources(blocks, chunks, 60)

    def test_large_table_repeats_header_and_covers_all_rows(self):
        text = 'Part | Interval\n' + '\n'.join(f'Filter {i} | Monthly' for i in range(40))
        blocks = [Block(0, 'table', text, page=5)]
        chunks = chunk_blocks(blocks, target=100, maximum=160, overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.text.startswith('Part | Interval') for chunk in chunks))
        self.assert_sources(blocks, chunks, 160)

    def test_pathological_headings_rows_and_unpunctuated_text_obey_limit(self):
        blocks = [Block(0, 'heading', 'h' * 500), Block(1, 'table', 'Header\n' + 'x' * 600),
                  Block(2, 'paragraph', '中' * 700), Block(3, 'code', 'a' * 400)]
        self.assert_sources(blocks, chunk_blocks(blocks, target=100, maximum=150, overlap=20), 150)


class DocumentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))
        token = self.client.post('/api/auth/login', json={'password': PASSWORD}).json()['access_token']
        self.headers = {'Authorization': f'Bearer {token}'}

    def test_all_document_routes_require_owner_before_storage_access(self):
        routes = [('GET', '/api/documents'), ('POST', '/api/documents'),
                  ('GET', '/api/documents/00000000-0000-0000-0000-000000000001'),
                  ('POST', '/api/documents/00000000-0000-0000-0000-000000000001/retry'),
                  ('GET', '/api/documents/00000000-0000-0000-0000-000000000001/original')]
        with patch('db.documents.connect') as connect:
            for method, path in routes:
                self.assertEqual(self.client.request(method, path).status_code, 401)
            connect.assert_not_called()

    def test_unsupported_upload_and_invalid_ids_do_not_reach_storage(self):
        with patch('db.documents.connect') as connect:
            response = self.client.post('/api/documents', files={'file': ('test.html', b'<script>bad</script>')}, headers=self.headers)
            self.assertEqual(response.status_code, 415)
            response = self.client.get('/api/documents/not-a-uuid', headers=self.headers)
            self.assertEqual(response.status_code, 422)
            connect.assert_not_called()

    def test_schema_errors_return_actionable_response_without_database_details(self):
        import psycopg
        with patch('db.documents.connect', side_effect=psycopg.errors.UndefinedTable('private DSN')):
            response = self.client.get('/api/documents', headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'schema_missing')
        self.assertNotIn('private DSN', response.text)


if __name__ == '__main__':
    unittest.main()
