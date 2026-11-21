"""Exercise the deployed owner-only document pipeline and remove only our fixture."""
import json
import os
import urllib.request
import urllib.error
import urllib.parse
import uuid
from api.security import create_access_token
from api.security import create_mcp_token
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
payload = (f'Deployment verification {marker}\n\nThis document verifies parsing and chunking.\n\n'
           'Review frequency: once a month. Retention period: 90 days.\n').encode()
boundary = 'rag-' + marker
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        'Content-Type: text/plain\r\n\r\n').encode() + payload + f'\r\n--{boundary}--\r\n'.encode()
request = urllib.request.Request(base + '/api/documents', data=body, headers={
    **headers, 'Content-Type': 'multipart/form-data; boundary=' + boundary
})
document_id = None


def mcp_request(method, arguments=None, *, base_url=base):
    params = {'name': method, 'arguments': arguments or {}} if arguments is not None else {}
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call' if arguments is not None else method,
            'params': params}
    request = urllib.request.Request(base_url + '/api/mcp', data=json.dumps(body).encode(), headers={
        'Authorization': 'Bearer ' + create_mcp_token(1), 'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25'})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
        assert 'result' in payload, payload
        assert not payload['result'].get('isError'), payload
        return payload['result']


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
    state = detail['embedding']
    assert state['status'] in ('ready', 'failed', 'disabled'), 'New uploads did not complete their embedding attempt'
    assert state['dimensions'] == 768
    if state['status'] == 'failed':
        assert state['error_code'] and state['error_message'], 'Embedding failure must be visible without failing the document'
    with connect() as conn:
        assert conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone(), 'pgvector migration missing'
    print('Embedding readiness:', state['status'], state.get('error_code') or '')
    query = urllib.parse.urlencode({'q': marker})
    with urllib.request.urlopen(urllib.request.Request(base + '/api/search?' + query, headers=headers)) as response:
        assert any(hit['document_id'] == document_id for hit in json.load(response)['items']), 'Search cannot find uploaded fixture'
    names = {tool['name'] for tool in mcp_request('tools/list')['tools']}
    assert names == {'search_documents', 'search_keywords', 'list_documents', 'get_document', 'read_document'}
    public_url = os.getenv('MCP_PUBLIC_URL', '').rstrip('/')
    if public_url:
        assert {tool['name'] for tool in mcp_request('tools/list', base_url=public_url)['tools']} == names
    hits = mcp_request('search_documents', {'query': marker})['structuredContent']['items']
    assert any(hit['document_id'] == document_id for hit in hits), 'MCP search cannot find fixture'
    context = mcp_request('read_document', {'document_id': document_id, 'limit': 1})['structuredContent']
    assert context['chunks'][0]['text'] == detail['chunks'][0]['text']
    assert context['blocks'] and context['chunks'][0]['sources'], 'MCP source provenance missing'
    try:
        urllib.request.urlopen(base + '/api/mcp')
        raise AssertionError('Unauthenticated MCP access succeeded')
    except urllib.error.HTTPError as error:
        assert error.code == 401
    for path in ('/api/ask', '/api/conversations'):
        try:
            urllib.request.urlopen(urllib.request.Request(base + path, headers=headers))
            raise AssertionError('Removed answer route still exposed')
        except urllib.error.HTTPError as error:
            assert error.code == 404
    missing_page = base + '/api/documents/' + str(uuid.uuid4()) + '/pages/1/preview'
    try:
        urllib.request.urlopen(urllib.request.Request(missing_page, headers=headers))
        raise AssertionError('Missing document preview unexpectedly succeeded')
    except urllib.error.HTTPError as error:
        assert error.code == 404 and json.load(error).get('code') == 'not_found', 'Page preview route not deployed'
    with urllib.request.urlopen(urllib.request.Request(base + '/api/documents/' + document_id + '/original', headers=headers)) as response:
        assert response.read() == payload
    print('Verified: authentication, upload, source mapping, chunks, pgvector, embedding state, search, authenticated MCP tools, source context, preview route and original download')
finally:
    # The fixture is unique to this invocation; never delete user documents.
    from pathlib import Path
    from core.config import DOCUMENTS_DIR
    with connect() as conn:
        rows = conn.execute('DELETE FROM knowledge_base_v1.documents WHERE filename = %s RETURNING id', (filename,)).fetchall()
    for row in rows:
        (DOCUMENTS_DIR / f'{row["id"]}.txt').unlink(missing_ok=True)
