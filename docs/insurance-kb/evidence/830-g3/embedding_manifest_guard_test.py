"""Manifest-sized batches preserve the existing one-attempt embedding boundary."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('guard', Path(__file__).with_name('embedding_manifest_guard.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class ManifestBatchTests(unittest.TestCase):
    def prepare(self, root, counts=(21, 2, 1, 3, 2, 1)):
        rows = []
        for i, count in enumerate(counts):
            body = g.go_json(dict(model='qwen3.7-text-embedding', input=[f'doc{i}:{j}' for j in range(count)], encoding_format='float', truncate_prompt_tokens=511))
            path = f'{i}.json'
            (root / path).write_bytes(body)
            rows.append(dict(material_id=f'm{i}', source_sha256=g.sha(f'source{i}'.encode()), persisted_path=path, request_sha256=g.sha(body), body_bytes=len(body), input_count=count))
        manifest = dict(contract='830-g3-prepared-embedding-transport.v2', upstream=g.UPSTREAM, provider_calls=0, batch_embed_size=100, requests=rows,
                        max_materials=len(rows), max_attempts=sum((n + 19)//20 for n in counts))
        p = root / 'manifest.json'
        p.write_bytes(g.go_json(manifest))
        return p, rows

    def test_six_materials_are_manifest_bound_and_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p, rows = self.prepare(root)
            allowed = g.load_allowed(root, p, g.sha(p.read_bytes()))
            calls = []
            def send(raw, authorization, remaining):
                values = json.loads(raw)['input']
                calls.append(values)
                return 200, g.go_json({'data': [dict(index=i, embedding=[0]*1024) for i in range(len(values))]})
            guard = g.Guard(root/'ledger.json', allowed, g.sha(p.read_bytes()), send=send)
            for row in rows:
                raw = (root/row['persisted_path']).read_bytes()
                self.assertEqual(guard.request(raw, 'Bearer fixture')[0], 200)
                self.assertEqual(guard.request(raw, 'Bearer fixture')[0], 409)
            self.assertEqual(len(calls), 7)
            self.assertEqual((guard.data['max_materials'], guard.data['max_attempts']), (6, 7))

    def test_declared_budget_cannot_understate_or_expand_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p, _ = self.prepare(root)
            for field in ('max_materials', 'max_attempts'):
                for delta in (-1, 1):
                    payload = json.loads(p.read_bytes())
                    payload[field] += delta
                    p.write_bytes(g.go_json(payload))
                    with self.assertRaisesRegex(ValueError, 'BUDGET'):
                        g.load_allowed(root, p, g.sha(p.read_bytes()))
                    p, _ = self.prepare(root)

    def test_failure_stops_remaining_sources_and_keeps_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p, rows = self.prepare(root, (1, 1))
            allowed = g.load_allowed(root, p, g.sha(p.read_bytes()))
            calls = []
            def send(*args):
                calls.append(1)
                return 503, b'{}'
            guard = g.Guard(root/'ledger.json', allowed, g.sha(p.read_bytes()), send=send)
            self.assertEqual(guard.request((root/rows[0]['persisted_path']).read_bytes(), 'Bearer fixture')[0], 503)
            self.assertEqual(guard.request((root/rows[1]['persisted_path']).read_bytes(), 'Bearer fixture')[0], 409)
            self.assertEqual(len(calls), 1)
            ledger = json.loads((root/'ledger.json').read_bytes())
            self.assertTrue(ledger['stopped'])
            self.assertEqual(len(ledger['attempts']), 1)
            self.assertEqual(ledger['attempts'][0]['status'], 'RESPONSE')
            self.assertEqual(ledger['attempts'][0]['http_status'], 503)
            self.assertEqual(ledger['attempts'][0]['response_sha256'], g.sha(b'{}'))


if __name__ == '__main__':
    unittest.main()
