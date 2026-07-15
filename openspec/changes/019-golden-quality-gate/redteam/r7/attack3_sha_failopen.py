"""Direction 2 + 3: For every `==`/`!=` SHA comparison on NON-golden fields, decide
fail-CLOSED (reject, safe) vs fail-OPEN (accept a wrong binding, bypass). Uppercase is the
canonical text variant since artifact.sha256()/content_hash()/approval.sha256() emit lowercase.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rt_helpers import A, AT, approve_baseline, artifact, candidate, fp, raw_product
from insurance_harness.goldenset.baseline import BaselineNotApprovableError, canonical_sha256
from insurance_harness.knowledge.quality_gate import QualityGate

print("=== Direction 3: canonical/hexdigest always lowercase ? ===")
a = artifact()
c = candidate(a, value_accuracy=1.0)
print("canonical_sha256 lowercase:", canonical_sha256({"x": 1}).islower())
print("artifact.sha256() lowercase:", a.sha256() == a.sha256().lower())
print("profile.content_hash() lowercase:", c.content_hash() == c.content_hash().lower())
rec0 = approve_baseline(a, c, approved_by="claude", approved_at=AT)
print("approval.sha256() lowercase:", rec0.sha256() == rec0.sha256().lower())
print("approval.artifact_sha256 lowercase:", rec0.artifact_sha256 == rec0.artifact_sha256.lower())

print("\n=== D2.1 approve_baseline: profile.artifact_sha256 UPPERCASE ===")
a = artifact()
c_up = candidate(a, artifact_sha256=a.sha256().upper())   # uppercase variant of correct hash
try:
    approve_baseline(a, c_up, approved_by="claude", approved_at=AT)
    print("*** FAIL-OPEN: uppercase artifact_sha256 accepted by approve_baseline")
except BaselineNotApprovableError as e:
    print("FAIL-CLOSED (reject):", str(e)[:60])

print("\n=== D2.2 gate: profile.artifact_sha256 == approval.artifact_sha256 (both raw str) ===")
# Legit good approval, then try to bind a DEGRADED profile by matching uppercase on BOTH sides.
a = artifact()
good = candidate(a, value_accuracy=1.0)
appr = approve_baseline(a, good, approved_by="claude", approved_at=AT)
good_approved = good.with_approval(appr)
# baseline: legit chain is gate-eligible
g0 = QualityGate(good_approved, approval=appr).decide("f1", "low", "add", a.fingerprint)
print("legit chain eligible:", g0.eligible)
# attack: forge degraded profile (va=0.5), copy approval回链 + uppercase both artifact_sha256
forged = candidate(a, value_accuracy=0.5).model_copy(update={
    "baseline_approval_sha256": appr.sha256(),
    "artifact_sha256": appr.artifact_sha256.upper(),
})
appr_up = appr.model_copy(update={"artifact_sha256": appr.artifact_sha256.upper()})
d = QualityGate(forged, approval=appr_up).decide("f1", "low", "add", a.fingerprint)
print("forged degraded (uppercase both sides) eligible:", d.eligible, "| reason:", d.reason)

print("\n=== D2.3 gate: content-hash binding pins profile content (uppercase can't unpin) ===")
# Try to keep approval valid but swap profile metrics while matching via uppercase artifact_sha256.
forged2 = good_approved.model_copy(update={
    "fields": {"f1": good_approved.fields["f1"].model_copy(update={"value_accuracy": 0.5})},
    "artifact_sha256": good_approved.artifact_sha256.upper(),
})
appr2 = appr.model_copy(update={"artifact_sha256": appr.artifact_sha256.upper()})
d2 = QualityGate(forged2, approval=appr2).decide("f1", "low", "add", a.fingerprint)
print("swapped-metric + uppercase eligible:", d2.eligible, "| reason:", d2.reason)

print("\n=== D2.4 product SHA UPPERCASE: approvable? distinct identity? ===")
a_low = artifact(products=(raw_product(pred_sha256=A),))
a_up = artifact(products=(raw_product(pred_sha256=A.upper()),))
print("uppercase product-SHA passes consistency/approval:",
      a_up.approval_blockers() == [])
print("same-content lower vs upper => DIFFERENT artifact identity:",
      a_low.sha256() != a_up.sha256())
# Does uppercase product SHA enable any reset/regression bypass? (identity differs, but reset only
# compares golden_release_hash, and regression compares metrics — product SHA never participates)
r_up = approve_baseline(a_up, candidate(a_up, value_accuracy=1.0), approved_by="c", approved_at=AT)
print("uppercase product-SHA approval succeeds:", r_up.version == 1)
