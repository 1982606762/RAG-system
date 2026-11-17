"""Release preparation must retain the active credentials and Google mounts."""

from contextlib import redirect_stdout
import copy
from io import StringIO
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


class DeploymentPreparationTests(unittest.TestCase):
    def test_current_routing_credentials_and_private_provider_mounts_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release, backup = root / 'release', root / 'backup'
            release.mkdir()
            backup.mkdir()
            verifier = '$2b$12$' + 'a' * 53
            secret = 'runtime-signing-secret-with-at-least-32-bytes'
            (release / '.env').write_text("OWNER_PASSWORD_HASH='stale'\nJWT_SECRET=stale\n")
            (root / '.current-release').mkdir()
            (root / '.current-release' / '.env').write_text('OWNER_PASSWORD_HASH=also-stale\n')
            provider = {'GOOGLE_DOCUMENT_AI_PROCESSOR': 'projects/test/locations/eu/processors/test',
                        'GOOGLE_APPLICATION_CREDENTIALS': '/run/secrets/google.json'}
            old = {'name': 'rag-system', 'networks': {'default': {'name': 'rag-system_default'}},
                   'volumes': {'pgdata': {'name': 'rag-system_pgdata'}}, 'services': {
                       'app': {'environment': {**provider, 'OWNER_PASSWORD_HASH': verifier.replace('$', '$$'), 'JWT_SECRET': secret},
                               'networks': {'default': None}, 'volumes': [
                                   {'type': 'bind', 'source': '/srv/private/adc.json', 'target': '/run/secrets/google.json', 'read_only': True}]},
                       'frontend': {'networks': {'default': None}, 'ports': [{'host_ip': '127.0.0.1', 'published': '8001', 'target': 80}]},
                       'postgres': {'image': 'postgres:16', 'volumes': [{'type': 'volume', 'source': 'pgdata', 'target': '/var/lib/postgresql/data'}]},
                   }}
            (backup / 'rollback.json').write_text(json.dumps(old))
            new = copy.deepcopy(old)
            new['services']['app']['environment'] = {'OWNER_PASSWORD_HASH': 'stale', 'JWT_SECRET': 'stale'}
            new['services']['app']['volumes'] = [
                {'type': 'bind', 'source': 'release/files/mvp', 'target': '/documents'},
                {'type': 'bind', 'source': 'release/files', 'target': '/files', 'read_only': True}]

            def docker(command, **kwargs):
                if command[:3] == ['docker', 'inspect', 'rag-system-app-1']:
                    return json.dumps([{'Config': {'Env': [f'OWNER_PASSWORD_HASH={verifier}', f'JWT_SECRET={secret}']}}]).encode()
                if command[:2] == ['docker', 'ps']:
                    return b'proxy' if 'label=com.docker.compose.project=rag-proxy' in command else b'app-id'
                if command[:2] == ['docker', 'inspect']:
                    return b'[{"Image":"sha256:old"}]'
                if command[:3] == ['docker', 'exec', 'proxy']:
                    return json.dumps({'routes': [{'match': [{'host': ['rag.example.test']}],
                        'handle': [{'handler': 'reverse_proxy', 'upstreams': [{'dial': 'frontend:80'}]}]}]}).encode()
                if command[:2] == ['docker', 'compose']:
                    return json.dumps(new).encode()
                raise AssertionError(command)

            script = Path(__file__).resolve().parents[2] / 'scripts' / 'prepare-deployment.py'
            output = StringIO()
            with patch.dict(os.environ, {'RAG_ROOT': str(root), 'RAG_RELEASE': str(release),
                                        'RAG_BACKUP': str(backup), 'RAG_REVISION': 'a' * 40}), \
                    patch('subprocess.check_output', side_effect=docker), patch('subprocess.run') as run, redirect_stdout(output):
                runpy.run_path(str(script))
            config = json.loads((release / 'production.json').read_text())
            self.assertEqual(config['services']['frontend']['ports'], old['services']['frontend']['ports'])
            self.assertEqual(config['networks'], old['networks'])
            self.assertEqual(config['services']['postgres'], old['services']['postgres'])
            app = config['services']['app']
            self.assertEqual(app['environment']['GOOGLE_APPLICATION_CREDENTIALS'], provider['GOOGLE_APPLICATION_CREDENTIALS'])
            self.assertEqual(app['environment']['OWNER_PASSWORD_HASH'], verifier.replace('$', '$$'))
            self.assertEqual(app['volumes'][-1]['source'], '/srv/private/adc.json')
            self.assertTrue(app['volumes'][-1]['read_only'])
            self.assertEqual(app['volumes'][0]['source'], str(root / 'files/mvp'))
            self.assertIn(f"OWNER_PASSWORD_HASH='{verifier}'", (release / '.env').read_text())
            self.assertEqual((release / 'public-domain').read_text(), 'rag.example.test')
            self.assertNotIn(secret, output.getvalue())
            self.assertNotIn(verifier, output.getvalue())
            self.assertEqual(run.call_count, 3)


if __name__ == '__main__':
    unittest.main()
