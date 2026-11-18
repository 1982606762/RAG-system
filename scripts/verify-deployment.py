"""Exercise the deployed owner-only document pipeline and remove only our fixture."""
import json
import os
import urllib.request
import urllib.error
import urllib.parse
import uuid
from api.security import create_access_token
from answers.provider import answer_profile
from db.documents import connect

base = os.getenv('RAG_VERIFY_URL', 'http://frontend')
try:
    urllib.request.urlopen(base + '/api/documents')
    raise AssertionError('Unauthenticated document access succeeded')
except urllib.error.HTTPError as error:
    assert error.code == 401

headers = {'Authorization': 'Bearer ' + create_access_token()}
marker = str(uuid.uuid4())
conversation_id = str(uuid.uuid4())
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


def conversation_request(path='', body=None):
    request_headers = headers if body is None else {**headers, 'Content-Type': 'application/json'}
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + '/api/conversations' + path, data=data, headers=request_headers)
    with urllib.request.urlopen(request, timeout=130) as response:
        return json.load(response)


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
    question = f'What does the document containing {marker} verify? Use the exact marker as the only keyword when searching.'
    first = {'question': question, 'request_id': conversation_id}
    if answer_profile() is None:
        try:
            conversation_request(body=first)
            raise AssertionError('Unconfigured Gemini unexpectedly accepted a question')
        except urllib.error.HTTPError as error:
            assert error.code == 503 and json.load(error).get('code') == 'answer_disabled'
    else:
        try:
            conversation = '/' + conversation_id
            result = conversation_request(body=first)
            assert result['conversation']['id'] == conversation_id
            for index, follow_up in enumerate((
                'How often is it reviewed? Search the same document using the keyword frequency.',
                'What about its retention period? Search the same document using the keyword retention.',
            ), start=1):
                saved = conversation_request(conversation)['turns']
                assert len(saved) == index
                result = conversation_request(conversation + '/turns', {
                    'question': follow_up, 'request_id': str(uuid.uuid4()), 'after_turn_id': saved[-1]['id'],
                })
            saved = conversation_request(conversation)['turns']
            assert len(saved) == 3 and saved[-1]['id'] == result['turn']['id']
            cited = sum(any(source['document_id'] == document_id for source in turn['answer']['citations'].values())
                        for turn in saved)
            print(f'Gemini conversation verification: {cited}/3 turns cited the fixture')
        except urllib.error.HTTPError as error:
            if error.code not in (502, 503, 504):
                raise
            # A hosted model outage should not roll back a healthy document library.
            print('Gemini conversation verification: unavailable (HTTP', error.code, ')')
        except (TimeoutError, urllib.error.URLError):
            print('Gemini conversation verification: connection unavailable')
    missing_page = base + '/api/documents/' + str(uuid.uuid4()) + '/pages/1/preview'
    try:
        urllib.request.urlopen(urllib.request.Request(missing_page, headers=headers))
        raise AssertionError('Missing document preview unexpectedly succeeded')
    except urllib.error.HTTPError as error:
        assert error.code == 404 and json.load(error).get('code') == 'not_found', 'Page preview route not deployed'
    with urllib.request.urlopen(urllib.request.Request(base + '/api/documents/' + document_id + '/original', headers=headers)) as response:
        assert response.read() == payload
    print('Verified: authentication, upload, source mapping, chunks, pgvector, embedding state, search, preview route and original download')
finally:
    # The fixture is unique to this invocation; never delete user documents.
    from pathlib import Path
    from core.config import DOCUMENTS_DIR
    with connect() as conn:
        conn.execute('DELETE FROM knowledge_base_v1.conversations WHERE id = %s', (conversation_id,))
        rows = conn.execute('DELETE FROM knowledge_base_v1.documents WHERE filename = %s RETURNING id', (filename,)).fetchall()
    for row in rows:
        (DOCUMENTS_DIR / f'{row["id"]}.txt').unlink(missing_ok=True)
