"""Prepare private production configuration without exposing environment values."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess

root = Path(os.environ['RAG_ROOT'])
release = Path(os.environ['RAG_RELEASE'])
backup = Path(os.environ['RAG_BACKUP'])
revision = os.environ['RAG_REVISION']
old = json.loads((backup / 'rollback.json').read_text())
assert old['name'] == 'rag-system'
front = old['services']['frontend']
assert front['networks']['web']['aliases'] == ['rag_frontend']
assert not front.get('ports')
assert old['networks']['web']['external']

for name, service in old['services'].items():
    cid = subprocess.check_output(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=rag-system', '--filter', f'label=com.docker.compose.service={name}']).decode().strip()
    if cid:
        info = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
        tag = f'rag-rollback-{name}:{revision[:12]}'
        subprocess.run(['docker', 'tag', info['Image'], tag], check=True)
        service['image'] = tag
        service.pop('build', None)
(backup / 'application-services').write_text(' '.join(name for name in ('app', 'frontend', 'celery_worker') if name in old['services']) + '\n')
# Compose interpolates resolved JSON again; preserve literal dollars in secrets.
(backup / 'rollback.json').write_text(json.dumps(old).replace('$', '$$'))

caddy = json.loads(subprocess.check_output([
    'docker', 'exec', 'caddy', 'caddy', 'adapt', '--config', '/etc/caddy/Caddyfile'
], stderr=subprocess.DEVNULL))
domains = set()
def find_routes(value, hosts=()):
    if isinstance(value, dict):
        matched = [host for match in value.get('match', []) for host in match.get('host', [])]
        hosts = tuple(matched) or hosts
        if value.get('handler') == 'reverse_proxy' and any(
            upstream.get('dial', '').split(':')[0] == 'rag_frontend'
            for upstream in value.get('upstreams', [])
        ):
            domains.update(hosts)
        for child in value.values():
            find_routes(child, hosts)
    elif isinstance(value, list):
        for child in value:
            find_routes(child, hosts)
find_routes(caddy)
assert len(domains) == 1, 'Expected exactly one RAG hostname'
domain = domains.pop()
assert re.fullmatch(r'[A-Za-z0-9.-]+', domain)
(release / 'public-domain').write_text(domain)
print('Preserved HTTPS entry:', domain)

# Keep a stable owner credential across releases; initialize only when missing.
env_file = release / '.env'
lines = env_file.read_text().splitlines()
values = {}
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip("'\"")
current = root / '.current-release' / '.env'
if current.exists():
    for line in current.read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key in ('OWNER_PASSWORD_HASH', 'JWT_SECRET'):
                values[key] = value.strip().strip("'\"")
owner_hash = values.get('OWNER_PASSWORD_HASH') or (release / 'scripts/bootstrap-owner.hash').read_text().strip()
assert re.fullmatch(r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}', owner_hash)
jwt_secret = values.get('JWT_SECRET', '')
if len(jwt_secret.encode()) < 32 or jwt_secret.startswith('change-me'):
    jwt_secret = secrets.token_urlsafe(48)
lines = [line for line in lines if line.split('=', 1)[0].strip() not in ('OWNER_PASSWORD_HASH', 'JWT_SECRET')]
lines += [f"OWNER_PASSWORD_HASH='{owner_hash}'", f"JWT_SECRET='{jwt_secret}'"]
env_file.write_text('\n'.join(lines) + '\n')
env_file.chmod(0o600)

new = json.loads(subprocess.check_output([
    'docker', 'compose', '--project-name', 'rag-system', '--project-directory', str(release),
    '-f', str(release / 'docker-compose.yml'), 'config', '--format', 'json'
]))
new['networks'] = old['networks']
new['services']['frontend']['networks'] = front['networks']
new['services']['frontend'].pop('ports', None)
for name in ('app', 'frontend'):
    new['services'][name]['image'] = f'rag-mvp-{name}:{revision}'
for volume in new['services']['app']['volumes']:
    if volume['type'] == 'bind':
        volume['source'] = str(root / ('files/mvp' if volume['target'] == '/documents' else 'files'))
# Production reuses the running database and does not recreate it.
new['services']['postgres'] = old['services']['postgres']
new['volumes'] = old.get('volumes', {})
path = release / 'production.json'
path.write_text(json.dumps(new).replace('$', '$$'))
path.chmod(0o600)
