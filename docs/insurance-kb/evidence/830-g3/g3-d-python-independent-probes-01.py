import copy
from pathlib import Path

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as module

ROOT = Path("/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation")
FIXTURE = ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json"

bundle = module.validate_batch_candidate(FIXTURE.read_bytes())
assert len(bundle.request.base_request.existing_fields) == 134
assert len(module.aligned_existing_fields(bundle.request)) == 134
assert len(bundle.model_compile_result.output.fields) == 208
assert len(bundle.compile_result.output.fields) == 342
print("PASS baseline actual342 request/candidate")


def request_with_hash(value):
    value["request_sha256"] = module._batch_sha256(
        value["contract"],
        {key: item for key, item in value.items() if key != "request_sha256"},
    )
    return module.BatchConceptCompileRequest830G3V1.model_validate(value)


# The wire validator must bind the displayed/logical product identity back to
# the selected C child anchors. Rehashing the D wrapper must not authorize drift.
changed = bundle.request.model_dump(mode="json")
binding = changed["entity_bindings"][0]
old_code = binding["product_code"]
binding["product_code"] = old_code + "-TAMPER"
binding["binding_sha256"] = module._batch_sha256(
    binding["contract"],
    {key: item for key, item in binding.items() if key != "binding_sha256"},
)
accepted = request_with_hash(changed)
assert accepted.entity_bindings[0].product_code.endswith("-TAMPER")
print("INVALID_ACCEPTED binding-product-code-not-bound-to-C-anchor")

# The claimed receipt_file_sha256 is constant, but the embedded confirmation
# must also be locked to those exact saved bytes/semantics.
changed = bundle.request.model_dump(mode="json")
confirmation = changed["profile_confirmation"]
confirmation["receipt"]["actor"] = "fabricated-confirmation-actor"
confirmation["receipt_semantic_sha256"] = module._batch_sha256(
    confirmation["receipt"]["contract"], confirmation["receipt"]
)
accepted = request_with_hash(changed)
assert accepted.profile_confirmation.receipt.actor == "fabricated-confirmation-actor"
print("INVALID_ACCEPTED profile-confirmation-content-not-bound-to-file-sha")

# The same source identity may not carry different SourceBlock bytes in the
# outer base request and in the replayed C corpus. Appending outside all quoted
# spans preserves Evidence yet demonstrates the missing equality check.
changed = bundle.request.model_dump(mode="json")
changed["base_request"]["sources"][0]["text"] += "\nTAMPER_OUTSIDE_EVIDENCE"
accepted = request_with_hash(changed)
assert accepted.base_request.sources[0].text.endswith("TAMPER_OUTSIDE_EVIDENCE")
print("INVALID_ACCEPTED same-source-identity-different-bytes")

# Existing strict extra-key behavior remains fail closed.
changed = bundle.request.model_dump(mode="json")
changed["entity_bindings"][0]["unexpected"] = "x"
try:
    request_with_hash(changed)
except Exception:
    print("PASS nested-extra-key-rejected")
else:
    raise AssertionError("nested extra key accepted")

print("EFFECTS provider=0 model=0 database=0 build=0 repo_write=0")
