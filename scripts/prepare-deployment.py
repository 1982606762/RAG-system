"""Prepare private production configuration without exposing environment values."""
import copy
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
database_service = copy.deepcopy(old['services']['postgres'])
assert old['name'] == 'rag-system'
front = old['services']['frontend']
runtime = json.loads(subprocess.check_output(['docker', 'inspect', 'rag-system-app-1']))[0]
runtime_env = dict(item.split('=', 1) for item in runtime['Config']['Env'])

for name, service in old['services'].items():
    cid = subprocess.check_output(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=rag-system', '--filter', f'label=com.docker.compose.service={name}']).decode().strip()
    if cid:
        info = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
        tag = f'rag-rollback-{name}:{revision[:12]}'
        subprocess.run(['docker', 'tag', info['Image'], tag], check=True)
        service['image'] = tag
        service.pop('build', None)
(backup / 'application-services').write_text(' '.join(name for name in ('app', 'frontend', 'celery_worker') if name in old['services']) + '\n')
# Docker Compose config already escapes literal dollars for round-tripping.
(backup / 'rollback.json').write_text(json.dumps(old))

caddy_ids = subprocess.check_output([
    'docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=rag-proxy',
    '--filter', 'label=com.docker.compose.service=caddy',
]).decode().split()
assert len(caddy_ids) == 1, 'Expected the existing RAG HTTPS proxy'
caddy = json.loads(subprocess.check_output([
    'docker', 'exec', caddy_ids[0], 'caddy', 'adapt', '--config', '/etc/caddy/Caddyfile'
], stderr=subprocess.DEVNULL))
domains = set()
def find_routes(value, hosts=()):
    if isinstance(value, dict):
        matched = [host for match in value.get('match', []) for host in match.get('host', [])]
        hosts = tuple(matched) or hosts
        if value.get('handler') == 'reverse_proxy' and any(
            upstream.get('dial', '').split(':')[0] == 'frontend'
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
for key in ('OWNER_PASSWORD_HASH', 'JWT_SECRET'):
    if runtime_env.get(key):
        values[key] = runtime_env[key]
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
if front.get('ports'):
    new['services']['frontend']['ports'] = front['ports']
else:
    new['services']['frontend'].pop('ports', None)
# Preserve provider settings and private credential mounts from the server.
# Resolved Compose values already escape literal dollar signs.
new['services']['app']['environment'].update(old['services']['app'].get('environment', {}))
new['services']['app']['networks'] = old['services']['app']['networks']
for name in ('app', 'frontend'):
    new['services'][name]['image'] = f'rag-mvp-{name}:{revision}'
for volume in new['services']['app']['volumes']:
    if volume['type'] == 'bind':
        volume['source'] = str(root / ('files/mvp' if volume['target'] == '/documents' else 'files'))
targets = {volume['target'] for volume in new['services']['app']['volumes']}
new['services']['app']['volumes'].extend(
    volume for volume in old['services']['app'].get('volumes', []) if volume['target'] not in targets
)
# Production reuses the running database and does not recreate it.
new['services']['postgres'] = database_service
new['volumes'] = old.get('volumes', {})
path = release / 'production.json'
path.write_text(json.dumps(new))
path.chmod(0o600)
