#!/usr/bin/env bash
set -euo pipefail
cd "$1"
python3 - <<'PY'
import json, subprocess
from pathlib import Path
release = Path('.current-release').resolve()
print('Active release:',release.name)
expected=(release/'scripts/bootstrap-owner.hash').read_text().strip()
env={}
for line in (release/'.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k,v=line.split('=',1);env[k.strip()]=v.strip().strip("'\"")
prod=json.loads(subprocess.check_output(['docker','compose','-p','rag-system','-f',str(release/'production.json'),'config','--format','json']))
container=json.loads(subprocess.check_output(['docker','inspect','rag-system-app-1']))[0]
actual=dict(x.split('=',1) for x in container['Config']['Env'])
for label,value in [('release env',env.get('OWNER_PASSWORD_HASH')),('resolved production config',prod['services']['app']['environment'].get('OWNER_PASSWORD_HASH')),('running container',actual.get('OWNER_PASSWORD_HASH'))]:
    print(label,'matches expected:', value==expected, 'length:', len(value or ''))
print('Running image matches release:',container['Config']['Image'].endswith(release.name))
PY
