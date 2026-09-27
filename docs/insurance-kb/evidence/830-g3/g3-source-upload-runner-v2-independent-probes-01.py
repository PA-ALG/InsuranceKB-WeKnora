import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path("/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation")
E = ROOT / "docs/insurance-kb/evidence/830-g3"
RUNNER = E / "source_upload_runner_v2.py"

spec = importlib.util.spec_from_file_location("g3_upload_v2_independent", RUNNER)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

# The frozen loader must close over exactly 11 new inputs and four existing descriptors.
frozen = module.load_frozen_inputs(ROOT)
assert len(frozen.materials) == 11
assert set(frozen.old_descriptors) == set(module.OLD_KNOWLEDGE_IDS)
print("PASS frozen-loader 11-new 4-old exact")

# Recompute each of the four real saved W1 manifests from all persisted HTTP chunk rows.
for material_id in module.OLD_MATERIAL_IDS:
    path = E / "inputs/existing-revisions" / f"{material_id}.json"
    capture = json.loads(path.read_text())
    chunks = []
    for page in capture["chunk_pages"]:
        assert page["revision"]["knowledge_id"] == module.OLD_KNOWLEDGE_IDS[material_id]
        assert page["revision"]["parse_attempt"] == capture["descriptor"]["parse_attempt"]
        for row in page["data"]:
            assert row["tenant_id"] == module.TENANT_ID
            assert row["knowledge_base_id"] == module.RAW_KB_ID
            assert row["knowledge_id"] == module.OLD_KNOWLEDGE_IDS[material_id]
            assert row["parse_attempt"] == capture["descriptor"]["parse_attempt"]
        chunks.extend(page["data"])
    module.validate_existing_revision_capture(
        capture["descriptor"], capture["descriptor"], chunks, capture["descriptor"]
    )
    print(f"PASS actual-W1 {material_id} chunks={len(chunks)}")

# The runner's exact Docreader gate matches the actual provision-v3 preflight projection.
preflight = json.loads((E / "source-runtime-v3-actual-preflight-03.json").read_text())
assert preflight["source"]["parser_env"] == {
    "DOCREADER_EXTERNAL_HTTPS_PROXY": "",
    "DOCREADER_EXTERNAL_HTTP_PROXY": "",
    "DOCREADER_GRPC_PORT": "50051",
    "DOCREADER_ODL_HYBRID": "off",
    "DOCREADER_ODL_HYBRID_URL": "",
}
print("PASS actual-provision-v3 docreader-env exact")

# An expired external deadline must fail before durable POST start and before transport.
now = [100.0]
deadline = module.ExternalDeadline(clock=lambda: now[0])
now[0] = deadline.expires_at
calls = {"begin": 0, "api": 0}
class State:
    def begin_post(self, *_):
        calls["begin"] += 1
class API:
    def request(self, *_args, **_kwargs):
        calls["api"] += 1
        return 200, b"{}"
executor = module.UploadExecutor(
    API(), State(), Path("/private/tmp"), frozen, lambda *_: {}, deadline=deadline
)
try:
    executor.request_json("POST", "/api/v1/knowledge/x", "expired", post=True)
except TimeoutError:
    pass
else:
    raise AssertionError("expired deadline accepted")
assert calls == {"begin": 0, "api": 0}
print("PASS expired-deadline-before-POST")

# Timestamp validity is structural and timezone-bearing, without generating authorization.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "authorization.json"
    all_ids = list(module.MATERIAL_IDS) + list(module.OLD_MATERIAL_IDS)
    value = {
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
        "approved_at": "2026-09-07",
    }
    path.write_text(json.dumps(value))
    try:
        module.validate_authorization(path, "a" * 64, "b" * 64)
    except RuntimeError as error:
        assert "timezone" in str(error)
    else:
        raise AssertionError("timezone-less authorization accepted")
print("PASS timezone-less-authorization-rejected")

# The old-source exact ID check is before the source PASS checkpoint in the executable loop.
source = RUNNER.read_text()
loop = source.index("for mid in OLD_MATERIAL_IDS")
check = source.index("validate_old_source_id(mid, receipt)", loop)
checkpoint = source.index('state.checkpoint(f"old-source-seal-{mid}-pass"', loop)
assert check < checkpoint
print("PASS old-source-check-before-pass-checkpoint")

print("EFFECTS http=0 docker=0 database=0 provider=0 upload=0")
