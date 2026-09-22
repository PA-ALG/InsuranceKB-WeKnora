import hashlib
import importlib.util
import inspect
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SRC = Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/source_upload_runner_v1.py')
spec = importlib.util.spec_from_file_location('runner_under_review', SRC)
r = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = r
assert spec.loader is not None
spec.loader.exec_module(r)

class Probe(unittest.TestCase):
    def test_authorization_passes_while_all_four_old_backfills_are_outside_material_scope(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'auth.json'
            value = {
                'contract': '830-g3-source-upload-authorization.v1',
                'decision': 'APPROVED', 'tenant_id': r.TENANT_ID, 'raw_kb_id': r.RAW_KB_ID,
                'manifest_sha256': r.MANIFEST_SHA256, 'runner_sha256': 'a' * 64,
                'provision_receipt_sha256': 'b' * 64,
                'authorized_material_ids': list(r.MATERIAL_IDS),
                'authorized_actions': ['upload', 'embedding-external-send', 'source-backfill'],
                'approved_at': True,
            }
            p.write_text(json.dumps(value))
            r.validate_authorization(p, 'a' * 64, 'b' * 64)
            self.assertTrue(set(r.OLD_KNOWLEDGE_IDS).isdisjoint(value['authorized_material_ids']))

    def test_guard_ledger_without_manifest_is_accepted(self):
        m = r.Material('g3-material-07', 'a.pdf', 1, 'm', 's', 1, 'q')
        ledger = {'attempts': [{'attempt': 1, 'material_id': m.material_id,
                               'source_sha256': m.sha256, 'request_sha256': m.request_sha256,
                               'status': 'RESPONSE', 'http_status': 200}], 'stopped': False}
        r.validate_guard_ledger(ledger, [m])

    def test_two_distinct_uploads_can_accept_same_knowledge_id(self):
        class State:
            def begin_post(self, *_): pass
            def record_http(self, *_): pass
            def finish_post(self, *_): pass
        class API:
            def request(self, method, path, **kwargs):
                material = m1 if not calls else m2
                calls.append(material.material_id)
                row = {'id': 'same-knowledge-id', 'tenant_id': r.TENANT_ID,
                       'knowledge_base_id': r.RAW_KB_ID, 'file_name': material.filename,
                       'file_size': material.size, 'file_hash': material.md5,
                       'file_sha256': material.sha256,
                       'metadata': {'process_overrides': r.expected_persisted_process_overrides()}}
                return 200, json.dumps({'data': row}).encode()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            p1, p2 = td/'one.pdf', td/'two.pdf'
            p1.write_bytes(b'one'); p2.write_bytes(b'two')
            m1 = r.Material('g3-material-07', p1.name, 3, r.file_md5(p1), r.file_sha256(p1), 1, 'q1', p1)
            m2 = r.Material('g3-material-08', p2.name, 3, r.file_md5(p2), r.file_sha256(p2), 1, 'q2', p2)
            calls = []
            frozen = r.FrozenInputs((m1,m2), {}, r.expected_process_config(), r.MANIFEST_SHA256, {})
            ex = r.UploadExecutor(API(), State(), td, frozen, lambda: {})
            self.assertEqual(ex.upload(m1)['id'], ex.upload(m2)['id'])

    def test_wrong_host_port_shared_mount_and_redis_password_mismatch_pass_runtime_gate(self):
        def ci(name, image, env):
            return {'Name': '/'+name, 'Image': image, 'State': {'Running': True},
                    'Config': {'Env': env},
                    'HostConfig': {'PortBindings': {'8080/tcp': [{'HostIp':'0.0.0.0','HostPort':'9999'}]}},
                    'Mounts': [{'Type':'volume','Name':'weknora-g2-shared','Destination':'/data/files','RW':True}],
                    'NetworkSettings': {'Networks': {r.INTERNAL_NETWORK: {}}}}
        appenv = ['BATCH_EMBED_SIZE=100','REDIS_DB=0','REDIS_ADDR=redis-g3:6379',
                  'REDIS_PASSWORD=app-secret','DB_HOST=postgres-g3','DB_PORT=5432',
                  'DB_NAME='+r.TARGET_DB,'DB_USER='+r.DB_USER]
        kb={'id':r.RAW_KB_ID,'tenant_id':r.TENANT_ID,'summary_model_id':None,'token_limit':0,
            'languages':[],'wiki_config':{},'indexing_strategy':{'graph_enabled':False,'wiki_enabled':False},
            'question_generation_config':{'enabled':False,'question_count':0}}
        model={'id':r.MODEL_ID,'tenant_id':r.TENANT_ID,'is_builtin':False,
               'parameters':{'base_url':r.GUARD_BASE_URL}}
        prov={'contract':'830-g3-source-runtime-provision-apply.v1','status':'PASS','script_sha256':r.PROVISION_SHA256}
        pg={'Name':'/'+r.PG_CONTAINER,'Image':r.PG_IMAGE,'State':{'Running':True},
            'NetworkSettings':{'Networks':{r.INTERNAL_NETWORK:{'Aliases':['postgres-g3']}}}}
        r.validate_runtime_precondition(prov, ci(r.APP,r.APP_IMAGE,appenv),
            ci(r.DOCREADER,r.DOCREADER_IMAGE,[]), ci(r.REDIS,r.REDIS_IMAGE,['REDIS_PASSWORD=redis-other']),
            kb, model, pg)

    def test_arbitrary_docker_command_is_accepted_and_forwarded(self):
        seen=[]
        def fake_run(command, **kwargs):
            seen.append(command)
            return subprocess.CompletedProcess(command,0,stdout=b'[]',stderr=b'')
        with mock.patch.object(r.subprocess,'run',fake_run):
            r.DockerRuntime(['arbitrary-runtime','--context','other']).call(['inspect','x'])
        self.assertEqual(seen[0][:3], ['arbitrary-runtime','--context','other'])

    def test_old_identity_validation_occurs_after_all_four_post_calls_in_main(self):
        src = inspect.getsource(r.main)
        loop = src.index('for mid in sorted(OLD_KNOWLEDGE_IDS)')
        post = src.index('receipt = executor.backfill', loop)
        validation = src.index('validate_old_source_ids(old_source_ids)', post)
        self.assertGreater(validation, src.index('state.checkpoint(f"old-source-seal-{mid}-pass"', post))

    def test_guard_lifetime_is_shorter_than_runner_serial_poll_budget(self):
        guard = (SRC.parent / 'embedding_guard.py').read_text()
        self.assertIn('threading.Timer(1800, server.shutdown)', guard)
        self.assertGreater(len(r.MATERIAL_IDS) * 180 * 2, 1800)

    def test_old_descriptor_files_have_no_frozen_digest_gate(self):
        src = inspect.getsource(r.load_frozen_inputs)
        self.assertIn('load_json(evidence / "inputs/existing-revisions"', src)
        self.assertNotIn('existing-revisions" / f"{mid}.json",', src)

if __name__ == '__main__':
    print('runner_sha256='+hashlib.sha256(SRC.read_bytes()).hexdigest())
    unittest.main(verbosity=2)
