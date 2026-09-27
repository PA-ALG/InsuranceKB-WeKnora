"""Rebuild from harness/: PYTHONPATH=src:. python ../internal/application/service/testdata/generate_restart_fixture.py.
Synthetic protocol data only; no provider or live release effects.
"""

import gzip
import hashlib
from pathlib import Path
from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as c
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    CompileOutput,
    ExecutionRecord,
    ReviewOutput,
    ReviewResult,
)
from tests.test_provenance_quality_bundle import quality_bundle
from tests.test_provenance_quality_policy import score

original = quality_bundle()
request = original.request
data = original.model_compile_result.output.model_dump(mode="json")
for d in data["definitions"]:
    d["body"] = "Synthetic generated concept explanation."
    d["evidence"] = []
    d["content_provenance"] = {
        "contract": "knowledge-content-provenance.830.v1",
        "segments": [
            {"text": d["body"], "origin": "MODEL_GENERATED", "evidence_indexes": []}
        ],
    }
for p in data["pages"]:
    p["body"] = "Synthetic generated reading advice."
    p["conditions"] = []
    p["exceptions"] = []
    p["evidence"] = []
    p["content_provenance"] = {
        "contract": "knowledge-content-provenance.830.v1",
        "segments": [
            {"text": p["body"], "origin": "MODEL_GENERATED", "evidence_indexes": []}
        ],
    }
output = CompileOutput.model_validate(data)
delta = c.record_model_compile(
    request,
    output,
    run_id="synthetic-restart",
    implementation="fixture-only",
    raw=c._canonical_json(output),
)
final = c.compose_batch_output(request, delta)
composed = c.record_composed_output(
    request, delta, final, run_id="synthetic-restart-composition"
)
reviewed = ReviewOutput(
    request_hash=c.compile_request_hash_g3(request.base_request),
    output_hash=c.compile_output_hash_g3(final),
    decision="PASS",
    page_scores={
        key: score(71, 0) for key in c.changed_knowledge_member_ids(request, final)
    },
    reasons=("SYNTHETIC_PROTOCOL_FIXTURE_NOT_MODEL_REVIEW",),
)
raw = c._canonical_json(reviewed)
review = ReviewResult(
    output=reviewed,
    execution=ExecutionRecord(
        run_id="synthetic-restart-review",
        implementation="fixture-only",
        context_hash=c._batch_sha256(
            "batch-concept-review-context.830.g3.v1",
            c.review_context_g3(request, final),
        ),
        raw_output=raw,
        raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
    ),
)
bundle = c.assemble_candidate_bundle(
    request, delta, composed, review, c.knowledge_admission_g3(request, final, reviewed)
)
raw = c._canonical_json(bundle).encode()
assert c.validate_batch_candidate(raw) == bundle
Path(__file__).with_name("generated-restart-candidate.json.gz").write_bytes(
    gzip.compress(raw, mtime=0)
)
print("Validated synthetic fixture created; no provider calls")
