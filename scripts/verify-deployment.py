"""Exercise the deployed owner-only document pipeline and remove only our fixture."""
import json
import os
import urllib.request
import urllib.error
import urllib.parse
import uuid
from api.security import create_access_token
from db.documents import connect

base = os.getenv('RAG_VERIFY_URL', 'http://frontend')
try:
    urllib.request.urlopen(base + '/api/documents')
    raise AssertionError('Unauthenticated document access succeeded')
except urllib.error.HTTPError as error:
    assert error.code == 401

headers = {'Authorization': 'Bearer ' + create_access_token()}
marker = str(uuid.uuid4())
filename = f'deployment-check-{marker}.txt'
payload = f'Deployment verification {marker}\n\nThis document verifies parsing and chunking.\n'.encode()
boundary = 'rag-' + marker
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        'Content-Type: text/plain\r\n\r\n').encode() + payload + f'\r\n--{boundary}--\r\n'.encode()
request = urllib.request.Request(base + '/api/documents', data=body, headers={
    **headers, 'Content-Type': 'multipart/form-data; boundary=' + boundary
})
document_id = None
try:
    with urllib.request.urlopen(request, timeout=150) as response:
        result = json.load(response)
    document_id = result.get('id') or result.get('document', {}).get('id')
    assert document_id, 'Upload did not return a document ID'
    with urllib.request.urlopen(urllib.request.Request(base + '/api/documents/' + document_id, headers=headers)) as response:
        detail = json.load(response)
    assert detail['status'] == 'ready', 'Document not ready'
    assert detail['blocks'] and detail['chunks'], 'Parsed content missing'
    assert detail['parser_version'] in ('local-blocks-v2', 'google-layout-v2'), 'Source mapping parser not deployed'
    query = urllib.parse.urlencode({'q': marker})
    with urllib.request.urlopen(urllib.request.Request(base + '/api/search?' + query, headers=headers)) as response:
        assert any(hit['document_id'] == document_id for hit in json.load(response)['items']), 'Search cannot find uploaded fixture'
    missing_page = base + '/api/documents/' + str(uuid.uuid4()) + '/pages/1/preview'
    try:
        urllib.request.urlopen(urllib.request.Request(missing_page, headers=headers))
        raise AssertionError('Missing document preview unexpectedly succeeded')
    except urllib.error.HTTPError as error:
        assert error.code == 404 and json.load(error).get('code') == 'not_found', 'Page preview route not deployed'
    with urllib.request.urlopen(urllib.request.Request(base + '/api/documents/' + document_id + '/original', headers=headers)) as response:
        assert response.read() == payload
    print('Verified: authentication, upload, source mapping parser, chunks, search, preview route and original download')
finally:
    # The fixture is unique to this invocation; never delete user documents.
    from pathlib import Path
    from core.config import DOCUMENTS_DIR
    with connect() as conn:
        rows = conn.execute('DELETE FROM knowledge_base_v1.documents WHERE filename = %s RETURNING id', (filename,)).fetchall()
    for row in rows:
        (DOCUMENTS_DIR / f'{row["id"]}.txt').unlink(missing_ok=True)
