"""Offline G3 embedding guard tests; no sockets, provider, or runtime effects."""
from __future__ import annotations

import base64
import copy
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'g3_embedding_guard', Path(__file__).with_name('embedding_manifest_guard.py'))
g = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(g)

OBSERVED_07_ORDINALS = [
    2, 21, 32, 7, 26, 10, 14, 18, 24, 30, 3, 9, 11, 25, 28, 1, 4,
    16, 19, 27, 33, 0, 12, 13, 17, 29, 6, 8, 15, 23, 31, 5, 20, 22,
]


def marker(text: str) -> int:
    return int(g.sha(text.encode())[:6], 16)


def embedding_response(inputs: list[str], *, reverse: bool = True) -> bytes:
    rows = [
        {'embedding': [marker(item), *([0] * 1023)], 'index': index}
        for index, item in enumerate(inputs)
    ]
    if reverse:
        rows.reverse()
    return g.go_json({'object': 'list', 'data': rows, 'usage': {'total_tokens': 1}})


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(__file__).resolve().parents[4]
        cls.manifest = Path(__file__).with_name('embedding-transport-manifest.json')
        original_manifest = json.loads(cls.manifest.read_bytes())
        cls.manifest_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.manifest_tmp.cleanup)
        cls.manifest = Path(cls.manifest_tmp.name) / 'manifest.json'
        original_manifest.update(contract='830-g3-prepared-embedding-transport.v2', max_materials=11, max_attempts=17)
        cls.manifest.write_bytes(g.go_json(original_manifest))
        cls.manifest_sha = g.sha(cls.manifest.read_bytes())
        cls.allowed = g.load_allowed(cls.repo, cls.manifest, cls.manifest_sha)
        manifest = json.loads(cls.manifest.read_bytes())
        cls.rows = {row['material_id']: row for row in manifest['requests']}
        cls.bodies = {
            material: (cls.repo / row['persisted_path']).read_bytes()
            for material, row in cls.rows.items()
        }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='g3-guard-test-')
        self.path = Path(self.temp.name) / 'ledger.json'
        self.calls: list[bytes] = []

    def tearDown(self):
        self.temp.cleanup()

    def sender(self, raw: bytes, authorization: str, remaining: float):
        self.assertTrue(authorization.startswith('Bearer '))
        self.assertGreater(remaining, 0)
        value = g.strict_json(raw)
        self.assertLessEqual(len(value['input']), 20)
        on_disk = json.loads(self.path.read_bytes())
        self.assertEqual(on_disk['materials'][-1]['status'], 'STARTED')
        self.assertEqual(on_disk['attempts'][-1]['status'], 'STARTED')
        self.assertEqual(on_disk['attempts'][-1]['request_sha256'], g.sha(raw))
        self.calls.append(raw)
        return 200, embedding_response(value['input'])

    def make(self, sender=None, clock=None, allowed=None):
        kwargs = {}
        if clock is not None:
            kwargs['clock'] = clock
        return g.Guard(self.path, allowed or self.allowed, self.manifest_sha,
                       send=sender or self.sender, **kwargs)

    def request(self, material: str, ordinals=None) -> bytes:
        value = json.loads(self.bodies[material])
        if ordinals is not None:
            value['input'] = [value['input'][i] for i in ordinals]
        return g.go_json(value)

    def assert_response_matches(self, response: bytes, inputs: list[str]):
        data = json.loads(response)['data']
        self.assertEqual([row['index'] for row in data], list(range(len(inputs))))
        self.assertEqual([row['embedding'][0] for row in data],
                         [marker(item) for item in inputs])

    def test_loads_all_unchanged_frozen_bodies_and_exact_split_totals(self):
        self.assertEqual(len(self.allowed), 11)
        self.assertEqual(sum(row['input_count'] for row in self.allowed.values()), 204)
        self.assertEqual(sum(row['body_bytes'] for row in self.allowed.values()), 693129)
        self.assertEqual(sum(row['part_count'] for row in self.allowed.values()), 17)
        self.assertEqual(sum(row['part_bytes'] for row in self.allowed.values()), 693723)
        with self.assertRaisesRegex(ValueError, 'FROZEN_MANIFEST_DRIFT'):
            g.load_allowed(self.repo, self.manifest, '0' * 64)

    def test_all_eleven_frozen_materials_make_seventeen_bounded_calls(self):
        guard = self.make()
        for material in self.rows:
            raw = self.request(material)
            status, response = guard.request(raw, 'Bearer offline-secret')
            self.assertEqual(status, 200)
            self.assert_response_matches(response, json.loads(raw)['input'])
        self.assertEqual(len(self.calls), 17)
        self.assertEqual(sum(len(json.loads(raw)['input']) for raw in self.calls), 204)
        self.assertEqual(sum(map(len, self.calls)), 693723)
        ledger = json.loads(self.path.read_bytes())
        self.assertEqual(set(ledger), {
            'contract', 'upstream', 'manifest_sha256', 'max_attempts',
            'max_materials', 'stopped', 'materials', 'attempts',
        })
        self.assertEqual(ledger['contract'], '830-g3-embedding-attempts.v2')
        self.assertEqual((ledger['max_materials'], ledger['max_attempts']), (11, 17))
        self.assertEqual(len(ledger['materials']), 11)
        self.assertEqual(len(ledger['attempts']), 17)
        self.assertTrue(all(row['status'] == 'RESPONSE' for row in ledger['materials']))

    def test_all_eleven_reversed_materials_preserve_received_vector_order(self):
        guard = self.make()
        for material in self.rows:
            count = self.rows[material]['input_count']
            raw = self.request(material, list(reversed(range(count))))
            status, response = guard.request(raw, 'Bearer offline')
            self.assertEqual(status, 200)
            self.assert_response_matches(response, json.loads(raw)['input'])
        self.assertEqual(len(self.calls), 17)
        self.assertEqual(sum(map(len, self.calls)), 693723)

    def test_observed_material_07_permutation_has_distinct_actual_identity(self):
        raw = self.request('g3-material-07', OBSERVED_07_ORDINALS)
        self.assertEqual(g.sha(raw),
                         '292f8aec8e27c9d43e98582d216014d49eaa8474c0969a3a464b1937ddd5af25')
        guard = self.make()
        status, response = guard.request(raw, 'Bearer offline')
        self.assertEqual(status, 200)
        self.assert_response_matches(response, json.loads(raw)['input'])
        self.assertEqual([len(json.loads(part)['input']) for part in self.calls], [20, 14])
        row = json.loads(self.path.read_bytes())['materials'][0]
        self.assertEqual(row['frozen_request_sha256'], self.rows['g3-material-07']['request_sha256'])
        self.assertEqual(row['actual_request_sha256'], g.sha(raw))
        self.assertNotEqual(row['actual_request_sha256'], row['frozen_request_sha256'])
        self.assertEqual(len(row['input_multiset_sha256']), 64)

    def test_duplicate_multiplicity_is_preserved_and_not_reduced_to_a_set(self):
        allowed = copy.deepcopy(self.allowed)
        key = next(iter(allowed))
        document = allowed[key]
        old_signature = document['signature']
        raw_value = {'model': 'qwen3.7-text-embedding', 'input': ['same', 'same', 'other'],
                     'encoding_format': 'float', 'truncate_prompt_tokens': 511}
        raw = g.go_json(raw_value)
        document.update(signature=g._signature(raw_value['input']),
                        input_multiset_sha256=g._multiset_sha(g._signature(raw_value['input'])),
                        body_bytes=len(raw), input_count=3, part_count=1, part_bytes=len(raw))
        self.assertNotEqual(old_signature, document['signature'])
        guard = self.make(allowed=allowed)
        self.assertEqual(guard.request(raw, 'Bearer offline')[0], 200)
        changed = dict(raw_value)
        changed['input'] = ['same', 'other', 'other']
        self.assertEqual(guard.request(g.go_json(changed), 'Bearer offline')[0], 403)

    def test_malformed_changed_or_noncanonical_requests_never_count(self):
        valid = json.loads(self.bodies['g3-material-19'])
        reversed_keys = {
            'truncate_prompt_tokens': valid['truncate_prompt_tokens'],
            'encoding_format': valid['encoding_format'],
            'input': valid['input'],
            'model': valid['model'],
        }
        cases = [
            b'not-json',
            b'{"model":"x","model":"y","input":[]}',
            b' ' + self.bodies['g3-material-19'],
            self.bodies['g3-material-19'] + b'\n',
            g.go_json({**valid, 'model': 'wrong'}),
            g.go_json({**valid, 'encoding_format': 'base64'}),
            g.go_json({**valid, 'truncate_prompt_tokens': False}),
            g.go_json({**valid, 'extra': 1}),
            g.go_json({**valid, 'input': valid['input'][:-1]}),
            g.go_json({**valid, 'input': [*valid['input'], 'extra']}),
            g.go_json({**valid, 'input': [valid['input'][0], valid['input'][0]]}),
            g.go_json({**valid, 'input': [
                valid['input'][0], json.loads(self.bodies['g3-material-21'])['input'][0],
            ]}),
            json.dumps(valid, ensure_ascii=True, separators=(',', ':')).encode(),
            g.go_json(reversed_keys),
        ]
        guard = self.make()
        for raw in cases:
            with self.subTest(raw=raw[:40]):
                self.assertEqual(guard.request(raw, 'Bearer offline')[0], 403)
        self.assertEqual(guard.data['materials'], [])
        self.assertEqual(self.calls, [])

    def test_missing_or_control_bearer_never_reserves_material(self):
        guard = self.make()
        raw = self.request('g3-material-19')
        for authorization in ('', 'Bearer ', 'Bearer x\nleak', 'Bearer x\0leak'):
            with self.subTest(authorization=repr(authorization)):
                self.assertEqual(guard.request(raw, authorization)[0], 401)
        self.assertEqual(guard.data['materials'], [])
        self.assertEqual(guard.data['attempts'], [])
        self.assertEqual(self.calls, [])

    def test_ambiguous_multiset_rejected_before_ledger_reservation(self):
        allowed = copy.deepcopy(self.allowed)
        keys = list(allowed)
        allowed[keys[1]]['signature'] = allowed[keys[0]]['signature']
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS'):
            self.make(allowed=allowed)
        self.assertFalse(self.path.exists())

    def test_same_source_alternate_permutations_and_five_app_retries_send_once(self):
        guard = self.make()
        raw = self.request('g3-material-07')
        reverse = self.request('g3-material-07', list(reversed(range(34))))
        self.assertEqual(guard.request(raw, 'Bearer offline')[0], 200)
        for _ in range(5):
            self.assertEqual(guard.request(reverse, 'Bearer offline')[0], 409)
        self.assertEqual(len(self.calls), 2)

    def test_concurrent_permutations_of_same_source_only_send_one_material(self):
        entered = threading.Event()
        release = threading.Event()

        def slow(raw, auth, remaining):
            if not entered.is_set():
                entered.set()
                release.wait(2)
            return self.sender(raw, auth, remaining)

        guard = self.make(sender=slow)
        bodies = [self.request('g3-material-19'),
                  self.request('g3-material-19', [1, 0])]
        statuses = []
        first = threading.Thread(target=lambda: statuses.append(
            guard.request(bodies[0], 'Bearer offline')[0]))
        second = threading.Thread(target=lambda: statuses.append(
            guard.request(bodies[1], 'Bearer offline')[0]))
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()
        release.set()
        first.join(2)
        second.join(2)
        self.assertCountEqual(statuses, [200, 409])
        self.assertEqual(len(self.calls), 1)

    def test_second_or_third_part_failure_stops_without_later_calls(self):
        for material, fail_at, expected_calls in (
                ('g3-material-07', 2, 2), ('g3-material-12', 3, 3)):
            with self.subTest(material=material):
                with tempfile.TemporaryDirectory(prefix='g3-part-fail-') as directory:
                    self.path = Path(directory) / 'ledger.json'
                    self.calls = []

                    def fail(raw, auth, remaining):
                        self.calls.append(raw)
                        if len(self.calls) == fail_at:
                            return 503, b'failed'
                        return 200, embedding_response(json.loads(raw)['input'])

                    guard = self.make(sender=fail)
                    self.assertEqual(guard.request(self.request(material), 'Bearer offline')[0], 503)
                    for _ in range(5):
                        self.assertEqual(guard.request(self.request('g3-material-19'),
                                                       'Bearer offline')[0], 409)
                    self.assertEqual(len(self.calls), expected_calls)

    def test_transport_exception_stops_all_materials(self):
        def fail(_raw, _auth, _remaining):
            raise TimeoutError('offline')

        guard = self.make(sender=fail)
        self.assertEqual(guard.request(self.request('g3-material-19'), 'Bearer offline')[0], 502)
        self.assertEqual(guard.request(self.request('g3-material-21'), 'Bearer offline')[0], 409)
        ledger = json.loads(self.path.read_bytes())
        self.assertTrue(ledger['stopped'])
        self.assertEqual(ledger['attempts'][0]['status'], 'TRANSPORT_FAILED')

    def test_pre_send_and_post_send_accounting_failures_stop(self):
        guard = self.make()
        with patch.object(guard, 'save', side_effect=OSError('offline disk')):
            self.assertEqual(guard.request(self.request('g3-material-19'),
                                           'Bearer offline')[0], 503)
        self.assertEqual(self.calls, [])
        self.assertTrue(guard.data['stopped'])

        with tempfile.TemporaryDirectory(prefix='g3-post-send-') as directory:
            self.path = Path(directory) / 'ledger.json'
            self.calls = []
            guard = self.make()
            original = guard.save
            count = 0

            def fail_after_send():
                nonlocal count
                count += 1
                if count == 3:
                    raise OSError('offline disk')
                original()

            with patch.object(guard, 'save', side_effect=fail_after_send):
                self.assertEqual(guard.request(self.request('g3-material-19'),
                                               'Bearer offline')[0], 503)
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(guard.data['stopped'])

    def test_invalid_provider_responses_stop_before_returning_vectors(self):
        good_inputs = json.loads(self.bodies['g3-material-19'])['input']
        good_rows = json.loads(embedding_response(good_inputs, reverse=False))['data']
        cases = {
            'missing-index': g.go_json({'data': good_rows[:-1]}),
            'duplicate-index': g.go_json({'data': [good_rows[0], good_rows[0]]}),
            'bool-index': g.go_json({'data': [{**good_rows[0], 'index': False}, good_rows[1]]}),
            'bad-dimension': g.go_json({'data': [{**good_rows[0], 'embedding': [0]}, good_rows[1]]}),
            'bool-vector': g.go_json({'data': [{**good_rows[0], 'embedding': [False, *([0] * 1023)]}, good_rows[1]]}),
            'float32-overflow': g.go_json({'data': [{**good_rows[0], 'embedding': [1e39, *([0] * 1023)]}, good_rows[1]]}),
            'numeric-infinity': b'{"data":[{"embedding":[' + b'1e400,' + b'0,' * 1022 + b'0],"index":0}]}',
            'json-nan': b'{"data":[{"embedding":[NaN],"index":0}]}',
            'duplicate-key': b'{"data":[],"data":[]}',
        }
        for label, response in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory(prefix='g3-response-') as directory:
                    self.path = Path(directory) / 'ledger.json'
                    guard = self.make(sender=lambda _r, _a, _t, body=response: (200, body))
                    self.assertEqual(guard.request(self.request('g3-material-19'),
                                                   'Bearer offline')[0], 502)
                    self.assertTrue(guard.data['stopped'])

    def test_provider_rows_are_sorted_by_index_and_global_offsets(self):
        guard = self.make()
        raw = self.request('g3-material-07')
        status, response = guard.request(raw, 'Bearer offline')
        self.assertEqual(status, 200)
        self.assert_response_matches(response, json.loads(raw)['input'])

    def test_material_deadline_rejects_late_success(self):
        now = [0.0]

        def clock():
            return now[0]

        def late(raw, _auth, _remaining):
            now[0] = 51.0
            return 200, embedding_response(json.loads(raw)['input'])

        guard = self.make(sender=late, clock=clock)
        self.assertEqual(guard.request(self.request('g3-material-19'),
                                       'Bearer offline')[0], 502)
        self.assertTrue(guard.data['stopped'])
        self.assertEqual(len(guard.data['attempts']), 1)

    def test_deadline_expiring_during_attempt_started_save_prevents_send(self):
        now = [0.0]
        sends = []
        guard = self.make(
            sender=lambda *_args: sends.append(_args) or (200, b'{}'),
            clock=lambda: now[0],
        )
        original = guard.save

        def save_and_expire():
            original()
            if guard.data['attempts'] and guard.data['attempts'][-1]['status'] == 'STARTED':
                now[0] = 51.0

        with patch.object(guard, 'save', side_effect=save_and_expire):
            self.assertEqual(guard.request(self.request('g3-material-19'),
                                           'Bearer offline')[0], 502)
        self.assertEqual(sends, [])
        self.assertTrue(guard.data['stopped'])

    def test_deadline_expiring_during_final_success_save_rejects_late_success(self):
        now = [0.0]
        guard = self.make(clock=lambda: now[0])
        original = guard.save

        def save_and_expire():
            original()
            if guard.data['materials'] and guard.data['materials'][-1]['status'] == 'RESPONSE':
                now[0] = 51.0

        with patch.object(guard, 'save', side_effect=save_and_expire):
            self.assertEqual(guard.request(self.request('g3-material-19'),
                                           'Bearer offline')[0], 502)
        self.assertTrue(guard.data['stopped'])

    def test_existing_ledger_is_exclusive_and_secret_is_not_persisted(self):
        guard = self.make()
        secret = 'Bearer offline-secret-not-real'
        self.assertEqual(guard.request(self.request('g3-material-19'), secret)[0], 200)
        self.assertNotIn(secret, self.path.read_text())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        before = self.path.read_bytes()
        with patch.object(Path, 'exists', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'EXISTING_LEDGER'):
                self.make()
        self.assertEqual(self.path.read_bytes(), before)


class TransportTests(unittest.TestCase):
    def test_frame_protocol_roundtrip_and_rejects_short_extra_or_secret_controls(self):
        framed = g._frame('Bearer offline', b'{}')
        self.assertEqual(g._read_frame(io.BytesIO(framed)), ('Bearer offline', b'{}'))
        for raw in (framed[:-1], framed + b'x', struct.pack('!I', 9000)):
            with self.subTest(raw=raw[:8]):
                with self.assertRaises(ValueError):
                    g._read_frame(io.BytesIO(raw))
        for secret in ('', 'Bearer x\nleak', 'Bearer x\0leak'):
            with self.assertRaises(ValueError):
                g._frame(secret, b'{}')

    def test_forward_once_uses_fixed_endpoint_and_closed_bounded_envelope(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, limit):
                self.limit = limit
                return b'{"data":[]}'

        class Opener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                self.response = Response()
                return self.response

        opener = Opener()
        output = io.BytesIO()
        g.forward_once(io.BytesIO(g._frame('Bearer offline', b'{}')), output, opener)
        envelope = json.loads(output.getvalue())
        self.assertEqual(opener.request.full_url, g.UPSTREAM)
        self.assertEqual(opener.request.data, b'{}')
        self.assertEqual(opener.timeout, 50.0)
        self.assertEqual(opener.response.limit, g.MAX_RESPONSE_BYTES + 1)
        self.assertEqual(envelope, {'status': 200,
                                    'body_base64': base64.b64encode(b'{"data":[]}').decode()})
        self.assertEqual(output.getvalue(), g.go_json(envelope))

    def test_subprocess_timeout_kills_and_reaps_only_owned_child(self):
        class Child:
            returncode = None
            killed = False
            communicates = 0

            def communicate(self, **kwargs):
                self.communicates += 1
                if self.communicates == 1:
                    raise subprocess.TimeoutExpired('fixed-child', kwargs['timeout'])
                self.returncode = -9
                return b'', b''

            def kill(self):
                self.killed = True

        child = Child()
        captured = {}

        def popen(args, **kwargs):
            captured.update(args=args, kwargs=kwargs)
            return child

        sender = g.SubprocessSender(popen)
        with self.assertRaisesRegex(TimeoutError, 'FORWARD_CHILD_TIMEOUT'):
            sender(b'{}', 'Bearer offline', 1.25)
        self.assertTrue(child.killed)
        self.assertEqual(child.communicates, 2)
        self.assertEqual(captured['args'][-1], '--forward-once')
        self.assertNotIn('offline', repr(captured))
        self.assertEqual(set(captured['kwargs']['env']),
                         {'PATH', 'LANG', 'PYTHONDONTWRITEBYTECODE'})

    def test_subprocess_parent_sends_secret_only_in_exact_frame(self):
        payload = b'{"fixed":true}'
        response = b'{"data":[]}'

        class Child:
            returncode = 0

            def communicate(self, **kwargs):
                self.frame = kwargs['input']
                self.timeout = kwargs['timeout']
                envelope = {'status': 200,
                            'body_base64': base64.b64encode(response).decode('ascii')}
                return g.go_json(envelope), b''

        child = Child()
        captured = {}

        def popen(args, **kwargs):
            captured.update(args=args, kwargs=kwargs)
            return child

        sender = g.SubprocessSender(popen)
        self.assertEqual(sender(payload, 'Bearer offline-secret', 4.5), (200, response))
        self.assertEqual(g._read_frame(io.BytesIO(child.frame)),
                         ('Bearer offline-secret', payload))
        self.assertGreater(child.timeout, 0)
        self.assertLessEqual(child.timeout, 4.5)
        self.assertNotIn('offline-secret', repr(captured))

    def test_subprocess_spawn_time_is_deducted_and_owned_child_reaped(self):
        now = [0.0]

        class Child:
            returncode = 0
            killed = False
            communicates = 0

            def communicate(self, **_kwargs):
                self.communicates += 1
                return g.go_json({'status': 200, 'body_base64': 'e30='}), b''

            def kill(self):
                self.killed = True

        child = Child()

        def popen(*_args, **_kwargs):
            now[0] = 2.0
            return child

        sender = g.SubprocessSender(popen, clock=lambda: now[0])
        with self.assertRaises(TimeoutError):
            sender(b'{}', 'Bearer offline', 1.0)
        self.assertTrue(child.killed)
        self.assertEqual(child.communicates, 1)


if __name__ == '__main__':
    unittest.main()
