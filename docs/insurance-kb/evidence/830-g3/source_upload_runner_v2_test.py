import hashlib
import importlib.util
import json
import tempfile
import unittest
import sys
import subprocess
from pathlib import Path


SCRIPT = Path("/private/tmp/g3-source-upload-runner-review2.py")


def load_runner():
    spec = importlib.util.spec_from_file_location("g3_source_upload_runner", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class UploadRunnerTests(unittest.TestCase):
    def test_scope_preflight_rejects_new_md5_before_any_write(self):
        module = load_runner()
        materials = [module.Material("g3-material-07", "a.pdf", 3, "md5-a", "sha-a", 1)]
        existing = [{"id": "existing", "tenant_id": module.TENANT_ID,
                     "knowledge_base_id": module.RAW_KB_ID, "file_name": "other.pdf",
                     "file_size": 9, "file_hash": "md5-a", "file_sha256": "different"}]
        with self.assertRaisesRegex(RuntimeError, "pre-upload conflict"):
            module.validate_initial_scope(existing, materials, {})

    def test_started_persist_failure_prevents_post(self):
        module = load_runner()
        sent = []

        class State:
            def begin_post(self, *_):
                raise OSError("fake fsync failure")

        with self.assertRaises(OSError):
            module.single_post(State(), lambda: sent.append(True), "upload:g3-material-07")
        self.assertEqual(sent, [])

    def test_timeout_is_result_unknown_and_sequence_does_not_advance(self):
        module = load_runner()
        calls = []

        class State:
            def __init__(self):
                self.rows = []

            def begin_material(self, material):
                self.rows.append([material.material_id, "STARTED"])

            def fail_material(self, material, status, error_type):
                self.rows[-1][1] = status

            def complete_material(self, material, result):
                self.rows[-1][1] = "PASS"

        def worker(material):
            calls.append(material.material_id)
            raise TimeoutError("ambiguous upload")

        materials = [module.Material("g3-material-07", "a", 1, "m1", "s1", 1),
                     module.Material("g3-material-08", "b", 1, "m2", "s2", 1)]
        state = State()
        with self.assertRaises(TimeoutError):
            module.execute_material_sequence(materials, state, worker)
        self.assertEqual(calls, ["g3-material-07"])
        self.assertEqual(state.rows, [["g3-material-07", "RESULT_UNKNOWN"]])

    def test_provider_non200_ledger_stops_before_next_material(self):
        module = load_runner()
        material = module.Material("g3-material-07", "a", 1, "m", "source-sha", 1,
                                   request_sha256="request-sha")
        ledger = {"stopped": True, "attempts": [{
            "material_id": material.material_id,
            "source_sha256": material.sha256,
            "request_sha256": material.request_sha256,
            "status": "RESPONSE", "http_status": 503,
        }]}
        with self.assertRaisesRegex(RuntimeError, "provider attempt failed"):
            module.validate_guard_ledger(ledger, [material])

    def test_descriptor_double_read_manifest_and_parser_must_match(self):
        module = load_runner()
        process = module.expected_process_config()
        chunks = [{"id": "c1", "chunk_index": 0, "content": "hello"},
                  {"id": "c2", "chunk_index": 1, "content": "world"}]
        digest = module.compute_manifest_digest("knowledge-1", 1, chunks)
        descriptor = {
            "knowledge_id": "knowledge-1", "parse_attempt": 1,
            "file_digest": {"algorithm": "sha256", "value": "a" * 64},
            "chunk_manifest": {"algorithm": "weknora.chunk_manifest.v1",
                               "digest": digest, "chunk_count": 2},
            "parser_identity": module.expected_parser_identity_projection(),
        }
        module.validate_revision_capture(descriptor, json.loads(json.dumps(descriptor)),
                                         chunks, process, "a" * 64)
        drifted = json.loads(json.dumps(descriptor))
        drifted["chunk_manifest"]["digest"] = "b" * 64
        with self.assertRaisesRegex(RuntimeError, "descriptor drift"):
            module.validate_revision_capture(descriptor, drifted, chunks, process, "a" * 64)

    def test_source_receipt_and_old_ids_are_exact(self):
        module = load_runner()
        material = module.Material("g3-material-07", "a.pdf", 9, "m", "a" * 64, 3)
        descriptor = {"knowledge_id": "knowledge-1", "parse_attempt": 2,
                      "chunk_manifest": {"algorithm": "weknora.chunk_manifest.v1",
                                         "digest": "b" * 64, "chunk_count": 4}}
        receipt = {"contract": "knowledge-revision-source.v1", "knowledge_id": "knowledge-1",
                   "parse_attempt": 2, "revision_source_id": "c" * 64,
                   "file_sha256": material.sha256, "object_sha256": material.sha256,
                   "size": 9, "mime_type": "application/pdf", "page_count": 3,
                   "manifest_algorithm": "weknora.chunk_manifest.v1",
                   "manifest_digest": "b" * 64, "chunk_count": 4,
                   "binding_digest": "d" * 64, "retention_state": "pinned"}
        module.validate_source_receipt(receipt, material, descriptor, "knowledge-1")
        old = dict(module.OLD_SOURCE_IDS)
        module.validate_old_source_ids(old)
        old["g3-material-01"] = "e" * 64
        with self.assertRaisesRegex(RuntimeError, "old source identity drift"):
            module.validate_old_source_ids(old)

    def test_teardown_failure_reports_stop_incomplete(self):
        module = load_runner()

        class Runtime:
            def stop_guard(self):
                return True

            def disconnect_egress(self):
                return False

            def stop_failed_runtime(self):
                return {module.APP: False, module.DOCREADER: True}

        evidence = module.teardown(Runtime(), failed=True)
        self.assertEqual(evidence["status"], "STOP_INCOMPLETE")

    def test_frozen_local_inputs_are_exact_eleven_unique_sources(self):
        module = load_runner()
        inputs = module.load_frozen_inputs(module.WORKTREE)
        self.assertEqual(len(inputs.materials), 11)
        self.assertEqual(len({m.sha256 for m in inputs.materials}), 11)
        self.assertEqual(inputs.process_config, module.expected_process_config())
        self.assertEqual(inputs.manifest_sha256, module.MANIFEST_SHA256)
        persisted = module.expected_persisted_process_overrides()
        self.assertNotIn("enable_parent_child", persisted["chunking_config"])
        self.assertFalse(inputs.process_config["chunking_config"]["enable_parent_child"])

    def test_existing_descriptor_uses_frozen_legacy_identity(self):
        module = load_runner()
        frozen = {"knowledge_id": "k", "parse_attempt": 1,
                  "file_digest": {"algorithm": "sha256", "value": "a" * 64},
                  "chunk_manifest": {"algorithm": "weknora.chunk_manifest.v1",
                                     "digest": "", "chunk_count": 1},
                  "parser_identity": {"chunk_size": 512}}
        chunks = [{"id": "c", "chunk_index": 0, "content": "legacy"}]
        frozen["chunk_manifest"]["digest"] = module.compute_manifest_digest("k", 1, chunks)
        module.validate_existing_revision_capture(frozen, json.loads(json.dumps(frozen)), chunks, frozen)
        drifted = json.loads(json.dumps(frozen))
        drifted["parser_identity"]["chunk_size"] = 2048
        with self.assertRaisesRegex(RuntimeError, "existing descriptor drift"):
            module.validate_existing_revision_capture(drifted, drifted, chunks, frozen)

    def test_post_response_status_is_durable_and_never_retried(self):
        module = load_runner()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = module.RunState(root / "receipt.json", {
                "materials": {}, "steps": [], "status": "STARTED"})

            class API:
                def request(self, *args, **kwargs):
                    calls.append((args, kwargs))
                    return 409, b'{"error":"duplicate"}'

            frozen = module.FrozenInputs((), {}, module.expected_process_config(),
                                         module.MANIFEST_SHA256, {})
            executor = module.UploadExecutor(API(), state, root / "artifacts", frozen, lambda: {})
            executor.artifacts.mkdir()
            with self.assertRaisesRegex(RuntimeError, "HTTP 409"):
                executor.request_json("POST", "/api/v1/test", "one-shot", post=True)
            self.assertEqual(len(calls), 1)
            saved = json.loads((root / "receipt.json").read_text())
            self.assertEqual(saved["current_post"]["status"], "RESPONSE")

    def test_upload_sends_exact_process_config_and_accepts_go_readback_shape(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            source.write_bytes(b"pdf")
            material = module.Material("g3-material-07", source.name, 3,
                                       module.file_md5(source), module.file_sha256(source), 1,
                                       "r" * 64, source)
            calls = []

            class API:
                def request(self, method, path, **kwargs):
                    calls.append((method, path, kwargs))
                    row = {"id": "knowledge-new", "tenant_id": module.TENANT_ID,
                           "knowledge_base_id": module.RAW_KB_ID, "file_name": source.name,
                           "file_size": 3, "file_hash": material.md5,
                           "file_sha256": material.sha256,
                           "metadata": {"process_overrides": module.expected_persisted_process_overrides()}}
                    return 200, json.dumps({"data": row}).encode()

            state = module.RunState(root / "receipt.json", {"materials": {}, "steps": []})
            artifacts = root / "artifacts"
            artifacts.mkdir()
            frozen = module.FrozenInputs((material,), {}, module.expected_process_config(),
                                         module.MANIFEST_SHA256, {})
            executor = module.UploadExecutor(API(), state, artifacts, frozen, lambda: {})
            self.assertEqual(executor.upload(material)["id"], "knowledge-new")
            self.assertEqual(len(calls), 1)
            self.assertIn(module.canonical(module.expected_process_config()), calls[0][2]["body"])

    def test_wrong_external_send_authorization_is_rejected(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            path.write_text(json.dumps({"contract": "wrong"}))
            with self.assertRaisesRegex(RuntimeError, "authorization"):
                module.validate_authorization(path, "a" * 64, "b" * 64)

    def test_login_requires_active_tenant_admin_and_me_readback(self):
        module = load_runner()

        class State:
            def __init__(self):
                self.events = []
            def begin_post(self, label):
                self.events.append((label, "STARTED"))
            def finish_post(self, label, status, details):
                self.events.append((label, status, details))

        class API:
            token = None
            def __init__(self):
                self.calls = []
            def request(self, method, path, **kwargs):
                self.calls.append((method, path, kwargs))
                user = {"id": "human-1", "tenant_id": module.TENANT_ID}
                membership = [{"tenant_id": module.TENANT_ID, "role": "admin"}]
                if path.endswith("/login"):
                    return 200, json.dumps({"success": True, "token": "secret-token",
                                            "user": user, "active_tenant": {"id": module.TENANT_ID},
                                            "memberships": membership}).encode()
                return 200, json.dumps({"data": {"user": user,
                    "tenant": {"id": module.TENANT_ID}, "memberships": membership}}).encode()

        api, state = API(), State()
        self.assertEqual(module.authenticate(api, state, "admin@example.test", "secret")["id"], "human-1")
        self.assertEqual(api.token, "secret-token")
        self.assertEqual([row[:2] for row in api.calls],
                         [("POST", "/api/v1/auth/login"), ("GET", "/api/v1/auth/me")])
        self.assertNotIn(b"secret-token", api.calls[0][2]["body"])

    def test_secret_file_must_be_private_single_line(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("value\n")
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "permissions"):
                module.secret_line(path, trim_outer_space=False)
            path.chmod(0o600)
            self.assertEqual(module.secret_line(path, trim_outer_space=False), "value")

    def test_runtime_teardown_noops_before_guard_or_network_exist(self):
        module = load_runner()
        runtime = module.DockerRuntime(
            ["colima", "ssh", "--profile", "default", "--", "sudo", "docker"])
        self.assertTrue(runtime.stop_guard())
        self.assertTrue(runtime.disconnect_egress())

    def test_exact_cloned_four_pass_readonly_scope(self):
        module = load_runner()
        frozen = module.load_frozen_inputs(module.WORKTREE)
        existing = []
        for mid, knowledge_id in module.OLD_KNOWLEDGE_IDS.items():
            material = frozen.old_materials[mid]
            existing.append({"id": knowledge_id, "tenant_id": module.TENANT_ID,
                             "knowledge_base_id": module.RAW_KB_ID,
                             "file_name": material.filename, "file_size": material.size,
                             "file_hash": material.md5, "file_sha256": material.sha256})
        module.validate_initial_scope(existing, frozen.materials, frozen.old_materials)

    def test_guard_staging_copies_exact_thirteen_regular_files(self):
        module = load_runner()
        frozen = module.load_frozen_inputs(module.WORKTREE)

        class FakeDocker(module.DockerRuntime):
            def __init__(self):
                super().__init__(["colima", "ssh", "--profile", "default", "--", "sudo", "docker"])
                self.calls = []

            def call(self, args, **kwargs):
                self.calls.append((args, kwargs))
                output = b""
                if len(args) > 4 and args[:3] == ["exec", module.APP, "python3"] \
                        and "expected=json.loads" in args[4]:
                    output = args[-1].encode()
                return subprocess.CompletedProcess(args, 0, stdout=output, stderr=b"")

        runtime = FakeDocker()
        self.assertEqual(runtime.prepare_stage(frozen), "/run/g3-830-upload")
        copied = [call for call in runtime.calls if call[0][:4] == ["exec", "-i", module.APP, "python3"]]
        self.assertEqual(len(copied), 13)
        self.assertTrue(all(call[1].get("input_bytes") for call in copied))

    def test_failed_runtime_stops_both_before_inspecting_either(self):
        module = load_runner()

        class FakeDocker(module.DockerRuntime):
            def __init__(self):
                super().__init__(["colima", "ssh", "--profile", "default", "--", "sudo", "docker"])
                self.events = []

            def call(self, args, **kwargs):
                self.events.append(tuple(args))
                return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

            def inspect(self, name):
                self.events.append(("inspect", name))
                return {"State": {"Running": False}}

        runtime = FakeDocker()
        self.assertEqual(runtime.stop_failed_runtime(), {module.APP: True, module.DOCREADER: True})
        self.assertEqual(runtime.events[:2], [("stop", "--time", "30", module.APP),
                                             ("stop", "--time", "30", module.DOCREADER)])

    def test_target_runtime_preflight_rejects_egress_already_attached(self):
        module = load_runner()

        def inspect(name, image, env):
            return {"Name": "/" + name, "Image": image, "State": {"Running": True},
                    "Config": {"Env": env}, "NetworkSettings": {"Networks": {
                        module.INTERNAL_NETWORK: {}, module.EGRESS_NETWORK: {}}}}

        app_env = ["BATCH_EMBED_SIZE=100", "REDIS_DB=0", "REDIS_ADDR=redis-g3:6379",
                   "DB_HOST=postgres-g3", "DB_PORT=5432",
                   "DB_NAME=" + module.TARGET_DB, "DB_USER=" + module.DB_USER]
        kb = {"id": module.RAW_KB_ID, "tenant_id": module.TENANT_ID,
              "indexing_strategy": {"graph_enabled": False, "wiki_enabled": False}}
        model = {"id": module.MODEL_ID, "tenant_id": module.TENANT_ID,
                 "is_builtin": False, "parameters": {"base_url": module.GUARD_BASE_URL}}
        provision = {"contract": "830-g3-source-runtime-provision-apply.v1", "status": "PASS",
                     "script_sha256": module.PROVISION_SHA256}
        with self.assertRaisesRegex(RuntimeError, "runtime network drift"):
            module.validate_runtime_precondition(
                provision, inspect(module.APP, module.APP_IMAGE, app_env),
                inspect(module.DOCREADER, module.DOCREADER_IMAGE, []),
                inspect(module.REDIS, module.REDIS_IMAGE, ["REDIS_PASSWORD=x"]), kb, model)

    def test_target_runtime_preflight_accepts_exact_provisioned_binding(self):
        module = load_runner()
        module.validate_runtime_precondition(*RepairOneBehaviorTests()._runtime(module))

    def test_existing_dedicated_egress_is_rejected_before_creation(self):
        module = load_runner()

        class FakeDocker(module.DockerRuntime):
            def call(self, args, **kwargs):
                return subprocess.CompletedProcess(args, 0,
                    stdout=(module.EGRESS_NETWORK + "\n").encode(), stderr=b"")

        with self.assertRaisesRegex(RuntimeError, "already exists"):
            FakeDocker(["colima", "ssh", "--profile", "default", "--", "sudo", "docker"]).assert_egress_absent()


class RepairOneBehaviorTests(unittest.TestCase):
    def _authorization(self, module):
        all_ids = list(module.MATERIAL_IDS) + list(module.OLD_KNOWLEDGE_IDS)
        return {
            "contract": "830-g3-source-upload-authorization.v1",
            "decision": "APPROVED",
            "tenant_id": module.TENANT_ID,
            "raw_kb_id": module.RAW_KB_ID,
            "manifest_sha256": module.MANIFEST_SHA256,
            "runner_sha256": "a" * 64,
            "provision_receipt_sha256": "b" * 64,
            "action_scopes": {
                "upload": {"material_ids": list(module.MATERIAL_IDS), "max_actions": 11},
                "embedding-external-send": {
                    "material_ids": list(module.MATERIAL_IDS),
                    "manifest_sha256": module.MANIFEST_SHA256,
                    "max_actions": 11,
                },
                "source-backfill": {
                    "material_ids": all_ids,
                    "execution_order": all_ids,
                    "max_actions": 15,
                },
            },
            "approved_at": "2026-09-07T20:00:00+08:00",
        }

    def test_authorization_binds_three_exact_action_scopes_and_timestamp(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            path.write_text(json.dumps(self._authorization(module)))
            value = module.validate_authorization(path, "a" * 64, "b" * 64)
            self.assertEqual(value["action_scopes"]["source-backfill"]["max_actions"], 15)
            invalid = self._authorization(module)
            invalid["approved_at"] = True
            path.write_text(json.dumps(invalid))
            with self.assertRaisesRegex(RuntimeError, "approved_at"):
                module.validate_authorization(path, "a" * 64, "b" * 64)
            extra = self._authorization(module)
            extra["authorized_material_ids"] = list(module.MATERIAL_IDS)
            path.write_text(json.dumps(extra))
            with self.assertRaisesRegex(RuntimeError, "authorization shape"):
                module.validate_authorization(path, "a" * 64, "b" * 64)

    def test_docker_runtime_only_accepts_exact_colima_transport(self):
        module = load_runner()
        with self.assertRaisesRegex(RuntimeError, "docker command"):
            module.DockerRuntime(["docker"])
        module.DockerRuntime(["colima", "ssh", "--profile", "default", "--", "sudo", "docker"])

    def _runtime(self, module):
        def inspect(name, image, env, mounts=(), ports=None):
            return {"Name": "/" + name, "Image": image, "State": {"Running": True},
                    "Config": {"Env": env}, "HostConfig": {"PortBindings": ports or {}},
                    "Mounts": list(mounts),
                    "NetworkSettings": {"Networks": {module.INTERNAL_NETWORK: {}}}}
        app_env = [
            "BATCH_EMBED_SIZE=100", "REDIS_DB=0", "REDIS_ADDR=redis-g3:6379",
            "REDIS_USERNAME=", "REDIS_PASSWORD=shared-secret", "DB_HOST=postgres-g3",
            "DB_PORT=5432", "DB_NAME=" + module.TARGET_DB, "DB_USER=" + module.DB_USER,
            "STORAGE_TYPE=local", "LOCAL_STORAGE_BASE_DIR=/data/files",
            "DOCREADER_ADDR=docreader-g3:50051", "DOCREADER_TRANSPORT=grpc",
        ]
        doc_env = ["PATH=/usr/local/bin:/usr/bin", "DOCREADER_GRPC_PORT=50051", "DOCREADER_ODL_HYBRID=off",
                   "DOCREADER_EXTERNAL_HTTP_PROXY=", "DOCREADER_EXTERNAL_HTTPS_PROXY=",
                   "DOCREADER_ODL_HYBRID_URL="]
        app_mounts = [
            {"Type": "volume", "Name": module.FILES_VOLUME, "Destination": "/data/files", "RW": True},
            {"Type": "volume", "Name": module.DOCREADER_TMP_VOLUME,
             "Destination": "/tmp/docreader", "RW": False},
        ]
        doc_mounts = [{"Type": "volume", "Name": module.DOCREADER_TMP_VOLUME,
                       "Destination": "/tmp/docreader", "RW": True}]
        app = inspect(module.APP, module.APP_IMAGE, app_env, app_mounts,
                      {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18294"}]})
        doc = inspect(module.DOCREADER, module.DOCREADER_IMAGE, doc_env, doc_mounts)
        redis = inspect(module.REDIS, module.REDIS_IMAGE, ["REDIS_PASSWORD=shared-secret"])
        kb = {"id": module.RAW_KB_ID, "tenant_id": module.TENANT_ID,
              "indexing_strategy": {"graph_enabled": False, "wiki_enabled": False},
              "question_generation_config": {"enabled": False, "question_count": 0}}
        model = {"id": module.MODEL_ID, "tenant_id": module.TENANT_ID,
                 "is_builtin": False, "parameters": {"base_url": module.GUARD_BASE_URL}}
        provision = {"contract": "830-g3-source-runtime-provision-apply.v1", "status": "PASS",
                     "script_sha256": module.PROVISION_SHA256}
        pg = {"Name": "/" + module.PG_CONTAINER, "Image": module.PG_IMAGE,
              "State": {"Running": True}, "NetworkSettings": {"Networks": {
                  module.INTERNAL_NETWORK: {"Aliases": ["postgres-g3"]}}}}
        return provision, app, doc, redis, kb, model, pg

    def test_runtime_gate_binds_port_volumes_env_and_redis_password(self):
        module = load_runner()
        values = self._runtime(module)
        module.validate_runtime_precondition(*values)
        drift = json.loads(json.dumps(values[1]))
        drift["Mounts"].append({"Type": "volume", "Name": "weknora-g2-594-files",
                                "Destination": "/data/files", "RW": True})
        with self.assertRaisesRegex(RuntimeError, "mount"):
            module.validate_runtime_precondition(values[0], drift, *values[2:])
        mismatch = json.loads(json.dumps(values[3]))
        mismatch["Config"]["Env"] = ["REDIS_PASSWORD=other"]
        with self.assertRaisesRegex(RuntimeError, "redis password"):
            module.validate_runtime_precondition(values[0], values[1], values[2], mismatch,
                                                 values[4], values[5], values[6])

    def test_old_source_id_is_checked_before_pass_checkpoint(self):
        module = load_runner()
        import inspect
        source = inspect.getsource(module.main)
        loop = source.index("for mid in OLD_MATERIAL_IDS")
        validate = source.index("validate_old_source_id(mid, receipt)", loop)
        checkpoint = source.index('state.checkpoint(f"old-source-seal-{mid}-pass"', loop)
        self.assertLess(validate, checkpoint)
        with self.assertRaisesRegex(RuntimeError, "old source identity drift"):
            module.validate_old_source_id("g3-material-01", {"revision_source_id": "0" * 64})

    def test_upload_rejects_old_or_repeated_returned_knowledge_id_immediately(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            source.write_bytes(b"pdf")
            material = module.Material("g3-material-07", source.name, 3, module.file_md5(source),
                                       module.file_sha256(source), 1, "r" * 64, source)
            class State:
                def begin_post(self, *_): pass
                def record_http(self, *_): pass
                def finish_post(self, *_): pass
            class API:
                def request(self, *_args, **_kwargs):
                    row = {"id": module.OLD_KNOWLEDGE_IDS["g3-material-01"],
                           "tenant_id": module.TENANT_ID, "knowledge_base_id": module.RAW_KB_ID,
                           "file_name": source.name, "file_size": 3, "file_hash": material.md5,
                           "file_sha256": material.sha256,
                           "metadata": {"process_overrides": module.expected_persisted_process_overrides()}}
                    return 200, json.dumps({"data": row}).encode()
            frozen = module.FrozenInputs((material,), {}, module.expected_process_config(),
                                         module.MANIFEST_SHA256, {})
            executor = module.UploadExecutor(API(), State(), root, frozen, lambda *_: {})
            with self.assertRaisesRegex(RuntimeError, "knowledge id"):
                executor.upload(material)

    def test_wait_and_revision_capture_bind_requested_knowledge(self):
        module = load_runner()
        material = module.Material("g3-material-07", "a.pdf", 3, "m", "a" * 64, 1)
        class State:
            def record_http(self, *_): pass
        class API:
            def request(self, *_args, **_kwargs):
                return 200, json.dumps({"data": {"id": "other", "tenant_id": module.TENANT_ID,
                    "knowledge_base_id": module.RAW_KB_ID, "file_name": material.filename,
                    "file_size": material.size, "file_hash": material.md5,
                    "file_sha256": material.sha256, "parse_status": "completed"}}).encode()
        frozen = module.FrozenInputs((material,), {}, module.expected_process_config(),
                                     module.MANIFEST_SHA256, {})
        executor = module.UploadExecutor(API(), State(), Path("/tmp"), frozen, lambda *_: {})
        executor._save_response = lambda *_: "x" * 64
        with self.assertRaisesRegex(RuntimeError, "knowledge readback binding"):
            executor.wait_completed("expected", material)

    def test_chunk_pages_bind_requested_scope_and_attempt(self):
        module = load_runner()
        class State:
            def record_http(self, *_): pass
        class API:
            def request(self, *_args, **_kwargs):
                row = {"id": "chunk-1", "chunk_index": 0, "content": "x",
                       "tenant_id": module.TENANT_ID, "knowledge_base_id": module.RAW_KB_ID,
                       "knowledge_id": "other", "parse_attempt": 1}
                return 200, json.dumps({"data": [row], "total": 1}).encode()
        frozen = module.FrozenInputs((), {}, module.expected_process_config(),
                                     module.MANIFEST_SHA256, {})
        executor = module.UploadExecutor(API(), State(), Path("/tmp"), frozen, lambda *_: {})
        executor._save_response = lambda *_: "x" * 64
        with self.assertRaisesRegex(RuntimeError, "chunk scope"):
            executor.chunks("expected", 1, "chunks")

    def test_guard_ledger_requires_exact_header_even_when_attempts_match(self):
        module = load_runner()
        ledger = {"contract": "830-g3-embedding-attempts.v1",
                  "upstream": module.GUARD_UPSTREAM, "manifest_sha256": module.MANIFEST_SHA256,
                  "max_attempts": 11, "stopped": False, "attempts": []}
        module.validate_guard_ledger(ledger, [])
        del ledger["upstream"]
        with self.assertRaisesRegex(RuntimeError, "header"):
            module.validate_guard_ledger(ledger, [])

    def test_empty_guard_header_is_validated_before_egress_creation(self):
        module = load_runner()
        import inspect
        source = inspect.getsource(module.main)
        launch = source.index("runtime.start_guard(staged)")
        validate = source.index("validate_guard_ledger(", launch)
        egress = source.index("runtime.create_egress()", launch)
        self.assertLess(validate, egress)
        self.assertIn("runtime.read_guard_ledger", source[validate:egress])

    def test_old_descriptor_manifest_and_exact_capture_files_are_frozen(self):
        module = load_runner()
        self.assertEqual(module.EXISTING_CHUNK_CAPTURE_SHA256,
                         "3b14ef391cad1a215a8012acbfb385b0093425aef60c116eebbd0a0a81b54924")
        values = module.load_frozen_inputs(module.WORKTREE)
        self.assertEqual(set(values.old_descriptors), set(module.OLD_KNOWLEDGE_IDS))

    def test_external_deadline_is_1440_seconds_and_clamps_http_and_sleep(self):
        module = load_runner()
        now = [100.0]
        deadline = module.ExternalDeadline(clock=lambda: now[0])
        self.assertEqual(deadline.expires_at, 1540.0)
        self.assertEqual(deadline.timeout(180), 180)
        now[0] = 1539.5
        self.assertEqual(deadline.timeout(180), 0.5)
        now[0] = 1540.0
        with self.assertRaisesRegex(TimeoutError, "external window deadline"):
            deadline.timeout(1)

    def test_guard_launch_time_anchors_external_deadline_before_probe_delay(self):
        module = load_runner()
        import inspect
        source = inspect.getsource(module.main)
        start = source.index("guard_launch_started = time.monotonic()")
        launch = source.index("runtime.start_guard(staged)")
        deadline = source.index("ExternalDeadline(started_at=guard_launch_started)")
        self.assertLess(start, launch)
        self.assertLess(launch, deadline)


if __name__ == "__main__":
    unittest.main(verbosity=2)
