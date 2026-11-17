#!/usr/bin/env bash
# Read-only inventory for the existing deployment; never print environment values.
set -euo pipefail
cd "$1"
printf 'Host: '; hostname
printf 'User: '; id -un
printf 'Directory: '; pwd
printf 'Git head: '; git rev-parse HEAD
printf 'Git changes:\n'; git status --short
printf 'Docker: '; docker version --format '{{.Server.Version}}'
printf 'Compose: '; docker compose version --short
printf 'Disk:\n'; df -h .
printf 'Services:\n'; docker compose ps --format json
printf 'Compose service names:\n'; docker compose config --services
printf 'File count: '; find files -type f | wc -l
printf 'File storage size: '; du -sh files
python3 - <<'PY'
from pathlib import Path
import re
keys = {}
for line in Path('.env').read_text().splitlines():
    if '=' not in line or line.lstrip().startswith('#'):
        continue
    key, value = line.split('=', 1)
    keys[key.strip()] = value.strip().strip("'\"")
for key in ('POSTGRES_PASSWORD', 'JWT_SECRET', 'OWNER_PASSWORD_HASH'):
    value = keys.get(key, '')
    print(f'{key}: {"configured" if value else "missing"}')
print('JWT_SECRET meets length requirement:', len(keys.get('JWT_SECRET', '').encode()) >= 32)
print('Config files:', ', '.join(str(p) for p in Path('.').glob('*compose*')))
PY
printf 'Container image IDs:\n'
for container in $(docker compose ps -q); do
  docker inspect --format '{{.Name}} {{.Image}} {{index .Config.Labels "com.docker.compose.project"}}' "$container"
done
printf 'HTTP status:\n'
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 http://127.0.0.1:8001/ || true

python3 - <<'PY'
import json, subprocess
config = json.loads(subprocess.check_output(['docker','compose','config','--format','json']))
front = config['services']['frontend']
print('Frontend routing:', json.dumps({k:front.get(k) for k in ('networks','ports')}))
labels = front.get('labels', {})
print('Routing labels:', json.dumps({k:v for k,v in labels.items() if k.endswith(('.rule','.loadbalancer.server.port','.entrypoints','.tls.certresolver')) or k in ('traefik.enable','traefik.docker.network')}))
print('Compose networks:', json.dumps(config.get('networks')))
ids = subprocess.check_output(['docker','ps','-q','--filter','network=web']).decode().split()
for cid in ids:
    item = json.loads(subprocess.check_output(['docker','inspect',cid]))[0]
    print('Web container:', json.dumps({'name':item['Name'], 'image':item['Config']['Image'], 'ports':item['NetworkSettings']['Ports']}))
PY
