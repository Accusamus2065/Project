from contextlib import closing
import datetime as dt
import gzip
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from harvest import backup


class FakeR2:
    def __init__(self):
        self.objects = {}
        self.extra = []
        self.uploads = 0
        self.corrupt = False
    def list_objects_v2(self, **kwargs):
        return {'Contents': self.extra + [{'Key': k, 'Size': len(v)} for k, v in self.objects.items()]}
    def list_multipart_uploads(self, **kwargs):
        return {}
    def put_object(self, **kwargs):
        self.uploads += 1
        self.objects[kwargs['Key']] = kwargs['Body'].read()
    def get_object(self, **kwargs):
        return {'Body': io.BytesIO(b'bad' if self.corrupt else self.objects[kwargs['Key']])}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'db.sqlite3'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE example (value TEXT)')
            db.execute("INSERT INTO example VALUES ('生产记录')")
        self.env = dict.fromkeys(backup.REQUIRED, 'test')
        self.client = FakeR2()
        self.now = dt.datetime(2026, 10, 21, 4, tzinfo=dt.timezone.utc)
    def run_backup(self, days=0):
        return backup.run_once(self.db, self.env, self.client, self.now + dt.timedelta(days=days))
    def test_success_is_restorable_and_once_per_day(self):
        self.assertEqual(self.run_backup(), 'ok')
        self.assertEqual(self.run_backup(), 'already_attempted')
        restored = Path(self.temp.name) / 'restored.db'
        restored.write_bytes(gzip.decompress(next(iter(self.client.objects.values()))))
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute('SELECT value FROM example').fetchone()[0], '生产记录')
        self.assertEqual(self.run_backup(1), 'ok')
        self.assertEqual(self.client.uploads, 2)
    def test_storage_limit_blocks_then_recovers_next_day(self):
        self.client.extra = [{'Key': 'other', 'Size': backup.MAX_BUCKET_BYTES}]
        self.assertEqual(self.run_backup(), 'blocked')
        self.assertEqual(self.client.uploads, 0)
        self.client.extra = []
        self.assertEqual(self.run_backup(), 'already_attempted')
        self.assertEqual(self.run_backup(1), 'ok')
    def test_monthly_budget_recovers_next_month(self):
        backup.write_state(self.db, {'month':'2026-10', 'month_bytes':backup.MAX_MONTH_BYTES, 'month_requests':0})
        self.assertEqual(self.run_backup(), 'blocked')
        self.assertEqual(self.client.uploads, 0)
        self.assertEqual(self.run_backup(11), 'ok')
    def test_request_budget_blocks(self):
        backup.write_state(self.db, {'month':'2026-10', 'month_bytes':0, 'month_requests':500})
        self.assertEqual(self.run_backup(), 'blocked')
        self.assertEqual(self.client.uploads, 0)
    def test_remote_verification_failure_is_not_success(self):
        self.client.corrupt = True
        self.assertEqual(self.run_backup(), 'blocked')
        self.assertIsNone(backup.read_state(self.db).get('last_success'))
    def test_network_failure_redacts_details_and_retries_next_day(self):
        with patch.object(self.client, 'put_object', side_effect=RuntimeError('SECRET')):
            self.assertEqual(self.run_backup(), 'failed')
        self.assertNotIn('SECRET', backup.state_path(self.db).read_text())
        self.assertEqual(self.run_backup(1), 'ok')
    def test_corrupt_accounting_fails_closed(self):
        backup.state_path(self.db).write_text('invalid')
        with self.assertRaises(ValueError): self.run_backup()
        self.assertEqual(self.client.uploads, 0)
        self.assertEqual(backup.public_status(self.db, self.env)['status'], 'failed')
    def test_incomplete_listing_and_multipart_block(self):
        with patch.object(self.client, 'list_objects_v2', return_value={'IsTruncated':True}):
            self.assertEqual(self.run_backup(), 'blocked')
        with patch.object(self.client, 'list_multipart_uploads', return_value={'Uploads':[{}]}):
            self.assertEqual(self.run_backup(1), 'blocked')
        self.assertEqual(self.client.uploads, 0)
    def test_nonstandard_blocks_and_disabled_does_no_io(self):
        self.assertEqual(backup.run_once(self.db, {}), 'disabled')
        self.assertFalse(backup.state_path(self.db).exists())
        self.client.extra = [{'Key':'old', 'Size':1, 'StorageClass':'STANDARD_IA'}]
        self.assertEqual(self.run_backup(), 'blocked')
    def test_large_database_blocks(self):
        with patch.object(backup, 'MAX_DATABASE_BYTES', 1):
            self.assertEqual(self.run_backup(), 'blocked')
        self.assertEqual(self.client.uploads, 0)
    def test_endpoint_rejects_non_cloudflare(self):
        with self.assertRaises(backup.BackupBlocked):
            backup.client_from_env({**self.env, 'R2_ENDPOINT_URL':'https://example.com'})

    def test_manager_only_status(self):
        from harvest import core
        app_db = Path(self.temp.name) / 'app.db'
        core.initialize(app_db)
        with closing(core.connect(app_db)) as db, db:
            for role in ('manager', 'employee'):
                db.execute('INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)',
                           (role, role, role, 0, 'unused'))
                user = db.execute('SELECT * FROM users WHERE username=?', (role,)).fetchone()
                result = core.state(db, user, '2026-10-21')
                self.assertEqual('backup' in result, role == 'manager')
