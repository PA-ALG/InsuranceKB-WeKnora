"""Direction 4 + 1: Reopen the six-round #2 case-variant reset bypass via model_copy(update=)
which SKIPS the Sha256Hex AfterValidator, then the parent BaselineArtifact does NOT re-validate
(no revalidate_instances). => an un-normalized (UPPERCASE) golden_release_hash reaches the reset
comparison at baseline.py:326, so `_A.upper() in {_A}` is False and reset OPENS.

Also drive the laundered approval through QualityGate.decide to prove gate-eligibility harm.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rt_helpers import A, AT, B, approve_baseline, artifact, candidate, fp, raw_product
from insurance_harness.goldenset.baseline import BaselineNotApprovableError
from insurance_harness.knowledge.quality_gate import QualityGate

# Production baseline b1, golden set _A (lowercase), value_accuracy=1.0
b1 = artifact(baseline_id="b1", fingerprint=fp(golden_release_hash=A))
prod = approve_baseline(b1, candidate(b1, value_accuracy=1.0), approved_by="claude", approved_at=AT)
print("prod: golden(lower)=", prod.fingerprint.golden_release_hash[:12], "va=1.0")

# 1) Sanity: same golden set via NORMAL construction with UPPERCASE is normalized -> reset REJECTED
b2fp_norm = fp(golden_release_hash=A.upper())
print("normal-construction upper normalized ->", b2fp_norm.golden_release_hash == A)
b2_norm = artifact(baseline_id="gs-v2", fingerprint=b2fp_norm, products=(raw_product(pred_sha256=B),))
try:
    approve_baseline(b2_norm, candidate(b2_norm, value_accuracy=0.99), approved_by="atk",
                     prior=[prod], allow_lineage_reset=True, lineage_reset_reason="x", approved_at=AT)
    print("normal-construction reset: *** unexpectedly approved ***")
except BaselineNotApprovableError as e:
    print("normal-construction reset REJECTED (fix works):", str(e)[:60])

# 2) ATTACK: build an un-normalized UPPERCASE golden hash via model_copy (skips validator)
evil_fp = fp(golden_release_hash=A).model_copy(update={"golden_release_hash": A.upper()})
print("model_copy fp golden =", evil_fp.golden_release_hash[:12], "(un-normalized)")
b2_evil = artifact(baseline_id="gs-v2-evil", fingerprint=evil_fp, products=(raw_product(pred_sha256=B),))
cand = candidate(b2_evil, value_accuracy=0.99)   # regressed vs 1.0 but >=0.98 gate threshold
try:
    reset = approve_baseline(b2_evil, cand, approved_by="attacker", prior=[prod],
                             allow_lineage_reset=True, lineage_reset_reason="rebrand",
                             approved_at=AT)
    print("*** RESET BYPASS: regressed candidate approved. lineage_reset=", reset.lineage_reset,
          "version=", reset.version)
    # Drive through the gate to prove auto-publish eligibility
    approved_profile = cand.with_approval(reset)
    gate = QualityGate(approved_profile, approval=reset)
    dec = gate.decide("f1", "low", "add", evil_fp)   # current run == same evil fp
    print("    gate decision eligible=", dec.eligible, "reason=", dec.reason)
except BaselineNotApprovableError as e:
    print("model_copy reset REJECTED:", str(e)[:80])
