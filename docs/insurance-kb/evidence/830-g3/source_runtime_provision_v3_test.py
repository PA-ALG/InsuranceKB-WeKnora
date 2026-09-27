import importlib.util
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("/private/tmp/g3-source-runtime-provision-draft.py")


def load_module():
    spec = importlib.util.spec_from_file_location("g3provision_review2", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthPath:
    def is_file(self):
        return True

    def is_symlink(self):
        return False

    def stat(self):
        class Result:
            st_mode = 0o600
        return Result()


def fixture(module):
    frozen_kb = {
        "id": module.RAW_KB_ID,
        "tenant_id": module.TENANT_ID,
        "embedding_model_id": module.EMBEDDING_MODEL_ID,
        "storage_backend_id": "storage",
        "vector_store_id": None,
        "chunking_config": {"strategy": "auto", "chunk_size": 512},
        "indexing_strategy": {
            "wiki_enabled": True,
            "graph_enabled": False,
            "keyword_enabled": True,
            "vector_enabled": True,
        },
    }
    kb = {
        **frozen_kb,
        "name": "raw",
        "description": "d",
        "type": "document",
        "summary_model_id": None,
        "question_generation_config": {"enabled": False, "question_count": 0},
        "image_processing_config": {},
        "faq_config": {},
        "wiki_config": {},
        "capabilities": {"vector": True, "keyword": True, "wiki": True,
                         "graph": False, "faq": False},
        "updated_at": "u0",
    }
    model = {
        "id": module.EMBEDDING_MODEL_ID,
        "tenant_id": module.TENANT_ID,
        "name": "qwen3.7-text-embedding",
        "display_name": "Qwen",
        "description": "d",
        "source": "remote",
        "type": "Embedding",
        "is_builtin": False,
        "parameters": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "interface_type": "",
            "embedding_parameters": {
                "dimension": 1024,
                "truncate_prompt_tokens": 0,
                "supports_dimension_override": False,
            },
            "parameter_size": 1,
            "provider": "aliyun",
            "supports_vision": False,
            "custom_headers": {},
        },
        "updated_at": "m0",
    }
    frozen = {
        "runtime-config-readonly.json": {
            "observations": [{
                "path": f"/api/v1/knowledge-bases/{module.RAW_KB_ID}",
                "selected": frozen_kb,
            }]
        },
        "existing-model-config-readonly.json": {
            "embedding_model": {"name": model["name"], "type": model["type"],
                                "source": model["source"]},
            "embedding_parameters": model["parameters"]["embedding_parameters"],
            "provider": "aliyun",
            "interface_type": "",
            "custom_header_names": [],
            "base_url_sanitized": {
                "scheme": "https", "host": "dashscope.aliyuncs.com",
                "port": None, "path": "/compatible-mode/v1",
            },
        },
    }
    return frozen_kb, kb, model, frozen


def install_common(module, api):
    _, _, _, frozen = fixture(module)
    module.api_request = api
    module.require_frozen_evidence = lambda: frozen
    module.load_json = lambda _: {"email": "admin@example.test", "password": "secret"}


def identity_responses(module):
    return {
        "login": {
            "token": "token",
            "user": {"id": "u", "email": "admin@example.test", "is_active": True},
            "active_tenant": {"id": module.TENANT_ID},
            "memberships": [{"tenant_id": module.TENANT_ID, "role": "admin"}],
        },
        "me": {"data": {
            "user": {"id": "u", "is_active": True},
            "tenant": {"id": module.TENANT_ID},
            "memberships": [{"tenant_id": module.TENANT_ID, "role": "admin"}],
        }},
    }


class ProvisionReview2Tests(unittest.TestCase):
    def test_put_success_is_checkpointed_before_failed_readback(self):
        module = load_module()
        _, kb, _, _ = fixture(module)
        ids = identity_responses(module)
        checkpoints = []
        put_seen = False

        def api(method, path, token=None, body=None):
            nonlocal put_seen
            if path.endswith("/auth/login"):
                return ids["login"]
            if path.endswith("/auth/me"):
                return ids["me"]
            if path.endswith(module.RAW_KB_ID):
                if method == "PUT":
                    put_seen = True
                    return {"success": True, "data": {}}
                if put_seen:
                    raise RuntimeError("fake readback failed")
                return {"data": kb}
            raise AssertionError((method, path))

        install_common(module, api)
        with self.assertRaisesRegex(RuntimeError, "fake readback failed"):
            module.configure_api(AuthPath(), lambda step, evidence=None: checkpoints.append(step))
        self.assertIn("kb-api-put-succeeded", checkpoints)

    def test_model_put_success_is_checkpointed_before_failed_readback(self):
        module = load_module()
        _, kb, model, _ = fixture(module)
        ids = identity_responses(module)
        checkpoints = []
        kb_after_put = False
        model_put_seen = False

        def api(method, path, token=None, body=None):
            nonlocal kb_after_put, model_put_seen
            if path.endswith("/auth/login"):
                return ids["login"]
            if path.endswith("/auth/me"):
                return ids["me"]
            if path.endswith(module.RAW_KB_ID):
                if method == "PUT":
                    kb_after_put = True
                    return {"success": True, "data": {}}
                out = json.loads(json.dumps(kb))
                if kb_after_put:
                    out["indexing_strategy"]["wiki_enabled"] = False
                    out["capabilities"]["wiki"] = False
                    out["updated_at"] = "u1"
                return {"data": out}
            if path.endswith(module.EMBEDDING_MODEL_ID):
                if method == "PUT":
                    model_put_seen = True
                    return {"success": True, "data": {}}
                if model_put_seen:
                    raise RuntimeError("fake model readback failed")
                return {"data": model}
            raise AssertionError((method, path))

        install_common(module, api)
        with self.assertRaisesRegex(RuntimeError, "fake model readback failed"):
            module.configure_api(AuthPath(), lambda step, evidence=None: checkpoints.append(step))
        self.assertIn("model-api-put-succeeded", checkpoints)

    def test_kb_expected_after_recomputes_capabilities(self):
        module = load_module()
        _, kb, model, _ = fixture(module)
        ids = identity_responses(module)
        after_put = False

        def api(method, path, token=None, body=None):
            nonlocal after_put
            if path.endswith("/auth/login"):
                return ids["login"]
            if path.endswith("/auth/me"):
                return ids["me"]
            if path.endswith(module.RAW_KB_ID):
                if method == "PUT":
                    after_put = True
                    return {"success": True, "data": {}}
                out = json.loads(json.dumps(kb))
                if after_put:
                    out["indexing_strategy"]["wiki_enabled"] = False
                    out["capabilities"]["wiki"] = False
                    out["updated_at"] = "u1"
                return {"data": out}
            if path.endswith(module.EMBEDDING_MODEL_ID):
                if method == "PUT":
                    model["parameters"] = json.loads(json.dumps(body["parameters"]))
                    model["updated_at"] = "m1"
                    return {"success": True, "data": {}}
                return {"data": model}
            raise AssertionError((method, path))

        install_common(module, api)
        checkpoints = []
        result = module.configure_api(
            AuthPath(), lambda step, evidence=None: checkpoints.append(step))
        self.assertFalse(result["wiki_enabled"])
        self.assertEqual(checkpoints, [
            "validated-human-admin-session",
            "kb-api-prewrite-validated",
            "kb-api-put-succeeded",
            "kb-api-postwrite-readback",
            "model-api-prewrite-validated",
            "model-api-put-succeeded",
            "model-api-postwrite-readback",
        ])

    def test_apply_source_env_requires_db_name_and_user(self):
        module = load_module()
        receipt = {"source_db": module.SOURCE_DB, "db_user": module.DB_USER,
                   "postgres_binding": {"host": "pg", "port": "5432"}}
        with self.assertRaisesRegex(RuntimeError, "database identity"):
            module.validate_apply_source_environment(
                {"DB_HOST": "pg", "DB_PORT": "5432", "DB_NAME": "wrong",
                 "DB_USER": module.DB_USER}, receipt)

    def test_apply_parser_env_requires_exact_forced_empty_values(self):
        module = load_module()
        parser_env = {"DOCREADER_GRPC_PORT": "50051",
                      "DOCREADER_EXTERNAL_HTTP_PROXY": "",
                      "DOCREADER_EXTERNAL_HTTPS_PROXY": "",
                      "DOCREADER_ODL_HYBRID": "off"}
        with self.assertRaisesRegex(RuntimeError, "parser environment"):
            module.validate_apply_parser_environment(parser_env)
        parser_env["DOCREADER_ODL_HYBRID_URL"] = ""
        module.validate_apply_parser_environment(parser_env)

    def test_source_pg_binding_includes_database_and_user(self):
        module = load_module()
        source = {"NetworkSettings": {"Networks": {"g2": {}}}}
        pg = {"Image": "sha256:pg", "NetworkSettings": {"Networks": {
            "g2": {"Aliases": ["postgres-g2", module.PG_CONTAINER]}}}}
        binding = module.source_pg_binding(source, pg, {
            "DB_HOST": "postgres-g2", "DB_PORT": "5432",
            "DB_NAME": module.SOURCE_DB, "DB_USER": module.DB_USER,
        })
        self.assertEqual(binding["database"], module.SOURCE_DB)
        self.assertEqual(binding["user"], module.DB_USER)
        module.validate_apply_source_environment({
            "DB_NAME": module.SOURCE_DB, "DB_USER": module.DB_USER,
        }, {"source_db": module.SOURCE_DB, "db_user": module.DB_USER,
            "postgres_binding": binding})

    def test_live_observed_missing_network_is_the_only_allowed_failure(self):
        module = load_module()
        runner = object.__new__(module.Runner)
        runner._docker_process = lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 1, b"[]\n",
            b"Error response from daemon: network weknora-g3-830-internal not found\n"
            b'time="x" level=fatal msg="exit status 1"\n')
        self.assertIsNone(runner.inspect("network", module.NETWORK, allow_missing=True))
        runner._docker_process = lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 1, b"[]\n", b"Cannot connect to Docker daemon\n")
        with self.assertRaisesRegex(RuntimeError, "docker inspect failed"):
            runner.inspect("network", module.NETWORK, allow_missing=True)

    def test_archive_rejects_links_and_cleanup_exception_stays_fail_closed(self):
        module = load_module()
        blob = io.BytesIO()
        with tarfile.open(fileobj=blob, mode="w") as archive:
            member = tarfile.TarInfo("source.pdf")
            member.type = tarfile.SYMTYPE
            member.linkname = "other.pdf"
            archive.addfile(member)
        with self.assertRaisesRegex(RuntimeError, "link or non-regular"):
            module.tar_manifest(blob.getvalue())

        runner = object.__new__(module.Runner)
        runner.prefix = ["colima"]
        original = module.subprocess.run
        module.subprocess.run = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fake"))
        try:
            cleanup = module.cleanup_remote_secret_files(runner)
        finally:
            module.subprocess.run = original
        self.assertEqual(cleanup, {"attempted": True, "clean": False,
                                   "execution": "failed"})

    def test_failure_stop_visits_and_reinspects_every_target(self):
        module = load_module()

        class Runner:
            def __init__(self):
                self.counts = {}
                self.stops = []

            def inspect(self, kind, name, allow_missing=False):
                self.counts[name] = self.counts.get(name, 0) + 1
                return {"State": {"Running": self.counts[name] == 1}}

            def _docker_process(self, *args, **kwargs):
                self.stops.append(args[-1])
                return subprocess.CompletedProcess(args, 0, b"", b"")

        runner = Runner()
        evidence = module.stop_and_inspect_targets(runner)
        self.assertEqual(evidence["failures"], [])
        self.assertEqual(runner.stops,
                         [module.SEED, module.APP, module.DOCREADER, module.REDIS])
        self.assertTrue(all(value == 2 for value in runner.counts.values()))

    def test_apply_validates_mutable_source_inputs_before_first_mutation(self):
        source = SCRIPT.read_text()
        apply_source = source[source.index("def apply("):]
        first_mutation = apply_source.index('r.docker("exec", PG_CONTAINER, "createdb"')
        self.assertLess(apply_source.index("validate_apply_source_environment"), first_mutation)
        self.assertLess(apply_source.index("validate_apply_parser_environment"), first_mutation)
        self.assertLess(apply_source.index("build_parser_environment"), first_mutation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
