"""Offline guard tests; injected sender only, no sockets or provider access."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('g3_embedding_guard', Path(__file__).with_name('embedding_guard.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='g3-guard-test-')
        self.path = Path(self.temp.name) / 'ledger.json'
        self.bodies = [json.dumps({'offline': i}).encode() for i in range(11)]
        self.allowed = {g.sha(b): {'source_sha256': f'{i:064x}', 'material_id': f'material-{i}'}
                        for i, b in enumerate(self.bodies)}
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def fake(self, raw, auth):
        # The durable STARTED event must exist before the injected upstream sees a call.
        on_disk = json.loads(self.path.read_text())
        self.assertEqual(on_disk['attempts'][-1]['status'], 'STARTED')
        self.assertEqual(on_disk['attempts'][-1]['request_sha256'], g.sha(raw))
        self.calls.append(raw)
        return 200, b'{"data":[]}'

    def make(self, sender=None):
        return g.Guard(self.path, self.allowed, 'f' * 64, send=sender or self.fake)

    def test_success_exact_bytes_once_and_no_credentials_persisted(self):
        guard = self.make()
        secret = 'Bearer offline-test-secret-not-real'
        self.assertEqual(guard.request(self.bodies[0], secret)[0], 200)
        self.assertEqual(self.calls, [self.bodies[0]])
        self.assertEqual(guard.request(self.bodies[0], secret)[0], 409)
        self.assertNotIn(secret, self.path.read_text())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_failure_consumes_attempt_and_stops_other_sources(self):
        def fail(raw, auth):
            self.fake(raw, auth)
            return 503, b'failed'
        guard = self.make(fail)
        self.assertEqual(guard.request(self.bodies[0], 'Bearer test')[0], 503)
        self.assertEqual(guard.request(self.bodies[0], 'Bearer test')[0], 409)
        self.assertEqual(guard.request(self.bodies[1], 'Bearer test')[0], 409)
        self.assertEqual(len(self.calls), 1)

    def test_transport_exception_stops_run(self):
        def fail(raw, auth):
            self.fake(raw, auth)
            raise TimeoutError()
        guard = self.make(fail)
        self.assertEqual(guard.request(self.bodies[0], 'Bearer test')[0], 502)
        self.assertEqual(guard.request(self.bodies[1], 'Bearer test')[0], 409)
        self.assertTrue(json.loads(self.path.read_text())['stopped'])

    def test_unknown_body_and_missing_bearer_do_not_count(self):
        guard = self.make()
        self.assertEqual(guard.request(b'unknown', 'Bearer test')[0], 403)
        self.assertEqual(guard.request(self.bodies[0], '')[0], 401)
        self.assertEqual(guard.data['attempts'], [])
        self.assertEqual(self.calls, [])

    def test_eleven_unique_attempts_bound_and_existing_ledger_refused(self):
        guard = self.make()
        for raw in self.bodies:
            self.assertEqual(guard.request(raw, 'Bearer test')[0], 200)
        self.assertEqual(len(self.calls), 11)
        for raw in self.bodies:
            self.assertEqual(guard.request(raw, 'Bearer test')[0], 409)
        self.assertEqual(len(self.calls), 11)
        with self.assertRaisesRegex(RuntimeError, 'EXISTING_LEDGER'):
            self.make()

    def test_pre_send_accounting_failure_stops_all_sources(self):
        guard = self.make()
        with patch.object(guard, 'save', side_effect=OSError('offline disk failure')):
            self.assertEqual(guard.request(self.bodies[0], 'Bearer test')[0], 503)
        self.assertTrue(guard.data['stopped'])
        self.assertEqual(guard.request(self.bodies[1], 'Bearer test')[0], 409)
        self.assertEqual(self.calls, [])

    def test_post_send_accounting_failure_stops_all_sources(self):
        guard = self.make()
        original = guard.save
        count = 0
        def fail_after_started():
            nonlocal count
            count += 1
            if count > 1:
                raise OSError('offline disk failure')
            original()
        with patch.object(guard, 'save', side_effect=fail_after_started):
            self.assertEqual(guard.request(self.bodies[0], 'Bearer test')[0], 503)
        self.assertTrue(guard.data['stopped'])
        self.assertEqual(guard.request(self.bodies[1], 'Bearer test')[0], 409)
        self.assertEqual(len(self.calls), 1)

    def test_stale_exists_check_cannot_overwrite_reserved_ledger(self):
        self.make()
        before = self.path.read_bytes()
        # Emulate a second starter observing stale absence; exclusive creation must win.
        with patch.object(Path, 'exists', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'EXISTING_LEDGER'):
                self.make()
        self.assertEqual(self.path.read_bytes(), before)

    def test_real_frozen_bodies_load_but_are_never_sent(self):
        root = Path(__file__).resolve().parents[4]
        manifest = Path(__file__).with_name('embedding-transport-manifest.json')
        allowed = g.load_allowed(root, manifest, g.sha(manifest.read_bytes()))
        self.assertEqual(len(allowed), 11)
        with self.assertRaisesRegex(ValueError, 'FROZEN_MANIFEST_DRIFT'):
            g.load_allowed(root, manifest, '0' * 64)


if __name__ == '__main__':
    unittest.main()
