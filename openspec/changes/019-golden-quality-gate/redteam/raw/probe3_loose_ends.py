"""Probe 3: two loose ends.
(1) RegressionFailure out-of-range FiniteFloat -> can it flip RegressionResult.eligible? (dir 2)
(2) ApprovalRecord.version is plain int (not NonNegativeInt) -> negative allowed? is it a false-pass?
"""
from datetime import UTC, datetime
from pydantic import ValidationError
from insurance_harness.goldenset.profile import RegressionFailure, RegressionResult
from insurance_harness.goldenset.baseline import ApprovalRecord, RunFingerprint

FP = RunFingerprint(git_sha="g", schema_version="s", model_id="m", prompt_version="p",
                    template_profile="t", source_profile="src", golden_release_hash="h")

print("=== (1) RegressionFailure with out-of-range values: does eligible flip to True? ===")
rr = RegressionResult(failures=(
    RegressionFailure(metric="global.micro_f1", baseline=2.0, candidate=-9.0, allowed=999.0),
))
print(f"  RegressionResult.eligible with 1 out-of-range failure = {rr.eligible}  (expect False)")
print(f"  summary: {rr.summary()}")
print("  -> out-of-range values only corrupt the DISPLAY; a present failure still blocks. Not a bypass.")
empty = RegressionResult(failures=())
print(f"  RegressionResult.eligible with no failures = {empty.eligible} (this is the only eligible=True path)")

print()
print("=== (2) ApprovalRecord.version: plain int, no NonNegativeInt ===")
try:
    ar = ApprovalRecord(baseline_id="b", version=-5, approved_by="x",
                        approved_at=datetime.now(UTC), fingerprint=FP,
                        artifact_sha256="a"*64, profile_content_sha256="c"*64)
    print(f"  [ACCEPTED] version=-5 constructed. It is a sequence tiebreaker in")
    print(f"    max(prior, key=(approved_at, version, baseline_id)); NOT a rate/count threshold.")
    print(f"    Exploiting it requires injecting forged records into the TRUSTED prior store,")
    print(f"    a different threat model (approval-log integrity), and yields no NaN/range false-pass.")
except ValidationError as e:
    print(f"  [BLOCKED] {sorted({x['type'] for x in e.errors()})}")
