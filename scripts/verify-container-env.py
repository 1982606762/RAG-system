"""Check rendered credentials inside a disposable container before any downtime."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

release = Path(os.environ['RAG_RELEASE'])
expected = {}
for line in (release / '.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        if key in ('OWNER_PASSWORD_HASH', 'JWT_SECRET'):
            expected[key] = hashlib.sha256(value.strip().strip("'\"").encode()).hexdigest()
assert len(expected) == 2
code = "import hashlib,json,os; print(json.dumps({key: hashlib.sha256(os.environ[key].encode()).hexdigest() for key in ('OWNER_PASSWORD_HASH','JWT_SECRET')}))"
actual = json.loads(subprocess.check_output([
    'docker', 'compose', '-p', 'rag-system', '--project-directory', str(release),
    '-f', str(release / 'production.json'), 'run', '--rm', '--no-deps', '-T',
    'app', 'python', '-c', code,
]))
assert actual == expected, 'Container credentials differ from release configuration'
print('Container owner verifier and signing key match release configuration')
