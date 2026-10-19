import io
import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
from harvest import core
from harvest.production import application, prepare


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = {'HARVEST_DB': str(Path(self.temp.name)/'db.sqlite3'),
                    'HARVEST_ORIGIN': 'https://nebo.example', 'TZ': 'America/Toronto',
                    'HARVEST_ADMIN_PASSWORD': 'TestingPassword123!'}
        self.config = prepare(self.env)
        self.app = application(self.config)

    def request(self, path, data=None, **headers):
        env = {}; setup_testing_defaults(env)
        body = json.dumps(data).encode() if data is not None else b''
        env.update(PATH_INFO=path, REQUEST_METHOD='POST' if data is not None else 'GET',
                   CONTENT_LENGTH=str(len(body)), CONTENT_TYPE='application/json',
                   **{'wsgi.input':io.BytesIO(body)}, **headers)
        result = []
        body = b''.join(self.app(env, lambda status, values: result.extend([status, dict(values)])))
        return result[0], result[1], body

    def test_bootstrap_is_idempotent_and_requires_password(self):
        prepare({**self.env, 'HARVEST_ADMIN_PASSWORD':'ChangedPassword123!'})
        with closing(core.connect(self.config.database)) as db:
            rows = db.execute('SELECT * FROM users').fetchall()
            self.assertEqual(len(rows), 1)
            self.assertTrue(core.password_ok(self.env['HARVEST_ADMIN_PASSWORD'], rows[0]['password']))
        with self.assertRaises(ValueError):
            prepare({**self.env, 'HARVEST_DB':str(Path(self.temp.name)/'empty.db'), 'HARVEST_ADMIN_PASSWORD':''})

    def test_login_security_state_health_and_head(self):
        self.assertTrue(self.request('/healthz')[0].startswith('200'))
        self.assertTrue(self.request('/api/state')[0].startswith('401'))
        credentials = {'username':'admin', 'password':self.env['HARVEST_ADMIN_PASSWORD']}
        self.assertTrue(self.request('/api/login', credentials, HTTP_ORIGIN='https://evil.example')[0].startswith('403'))
        status, headers, _ = self.request('/api/login', credentials, HTTP_ORIGIN=self.config.origin)
        self.assertTrue(status.startswith('200'))
        self.assertIn('Secure', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        status, _, body = self.request('/api/state', HTTP_COOKIE=cookie)
        state = json.loads(body)
        self.assertTrue(status.startswith('200'))
        self.assertEqual(state['user']['username'], 'admin')
        status, _, _ = self.request('/api/user', {'username':'worker','name':'员工','role':'employee','rate':20,'password':'WorkerPassword123!'}, HTTP_COOKIE=cookie, HTTP_X_CSRF_TOKEN=state['csrf'], HTTP_ORIGIN=self.config.origin)
        self.assertTrue(status.startswith('200'), status)
        env = {}; setup_testing_defaults(env); env.update(PATH_INFO='/',REQUEST_METHOD='HEAD')
        self.assertEqual(b''.join(self.app(env, lambda *args:None)), b'')

    def test_render_requires_disk_unless_explicit_trial(self):
        with patch('pathlib.Path.is_mount', return_value=False):
            with self.assertRaises(ValueError):
                prepare({**self.env, 'RENDER':'true'})
            prepare({**self.env, 'RENDER':'true', 'HARVEST_ALLOW_EPHEMERAL':'1'})

    def test_configuration_and_errors(self):
        with self.assertRaises(ValueError):
            prepare({**self.env, 'HARVEST_ORIGIN':'http://example.com'})
        env = {**self.env}; env.pop('HARVEST_ORIGIN'); env['RENDER_EXTERNAL_URL']='https://nebo.onrender.com'
        self.assertEqual(prepare(env).origin, 'https://nebo.onrender.com')
        with patch('harvest.production.core.connect', side_effect=RuntimeError('private database detail')):
            with self.assertLogs(level='ERROR'):
                status, _, body = self.request('/healthz')
        self.assertTrue(status.startswith('503'))
        self.assertNotIn(b'private database detail', body)
