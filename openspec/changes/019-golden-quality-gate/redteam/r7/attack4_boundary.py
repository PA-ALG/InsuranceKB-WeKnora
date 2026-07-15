"""Characterize the reset bypass boundary precisely:
(a) model_construct also skips Sha256Hex (task's explicit question);
(b) does a FABRICATED distinct fake 64-hex golden hash via NORMAL (validated) construction also
    open reset? (i.e. is the model_copy path even necessary, or is laundering already possible
    within the documented 020 authorization boundary?);
(c) harm bound: a fully-degraded candidate (va=0.5) approved via reset is still gate-DENIED.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rt_helpers import A, AT, B, approve_baseline, artifact, candidate, fp, raw_product
from insurance_harness.goldenset.baseline import (
    BaselineNotApprovableError, RunFingerprint,
)
from insurance_harness.knowledge.quality_gate import QualityGate

b1 = artifact(baseline_id="b1", fingerprint=fp(golden_release_hash=A))
prod = approve_baseline(b1, candidate(b1, value_accuracy=1.0), approved_by="claude", approved_at=AT)

print("=== (a) model_construct skips Sha256Hex normalization? ===")
mc = RunFingerprint.model_construct(
    git_sha="g", schema_version="v", model_id="m", prompt_version="p",
    template_profile="t", source_profile="s", golden_release_hash=A.upper(),
)
print("model_construct golden stays UPPER:", mc.golden_release_hash == A.upper())
b2mc = artifact(baseline_id="mc", fingerprint=mc, products=(raw_product(pred_sha256=B),))
try:
    r = approve_baseline(b2mc, candidate(b2mc, value_accuracy=0.99), approved_by="atk",
                         prior=[prod], allow_lineage_reset=True, lineage_reset_reason="x", approved_at=AT)
    print("  *** reset OPENED via model_construct upper (bypass), lineage_reset=", r.lineage_reset)
except BaselineNotApprovableError as e:
    print("  reset rejected:", str(e)[:50])

print("\n=== (b) FABRICATED distinct fake hash via NORMAL validated constructor opens reset? ===")
fake = "f" * 64   # a perfectly valid, normalized, DISTINCT 64-hex that names no real golden set
b2fake = artifact(baseline_id="fake", fingerprint=fp(golden_release_hash=fake),
                  products=(raw_product(pred_sha256=B),))
cand = candidate(b2fake, value_accuracy=0.99)
r2 = approve_baseline(b2fake, cand, approved_by="attacker", prior=[prod],
                      allow_lineage_reset=True, lineage_reset_reason="new gs (fabricated)",
                      approved_at=AT)
print("  reset OPENED with fabricated distinct hash (NORMAL construction):",
      r2.lineage_reset, "version=", r2.version)
gate_dec = QualityGate(cand.with_approval(r2), approval=r2).decide(
    "f1", "low", "add", fp(golden_release_hash=fake))
print("  => gate eligible for the laundered va=0.99 regression:", gate_dec.eligible)
print("  (This path needs NO model_copy; it is the documented 020 golden-authenticity boundary.)")

print("\n=== (c) harm bound: fully-degraded va=0.5 approved via reset is still gate-DENIED ===")
b2bad = artifact(baseline_id="bad", fingerprint=fp(golden_release_hash=fake),
                 products=(raw_product(pred_sha256=B),))
bad = candidate(b2bad, value_accuracy=0.5)
r3 = approve_baseline(b2bad, bad, approved_by="attacker", prior=[prod],
                      allow_lineage_reset=True, lineage_reset_reason="x", approved_at=AT)
d3 = QualityGate(bad.with_approval(r3), approval=r3).decide("f1", "low", "add", fp(golden_release_hash=fake))
print("  va=0.5 reset-approved:", r3.version == 1, "| gate eligible:", d3.eligible, "|", d3.reason[:40])
