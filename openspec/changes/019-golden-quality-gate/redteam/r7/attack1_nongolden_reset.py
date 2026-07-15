"""Direction 1: Can changing a NON-golden fingerprint dim (model_id/schema_version) open a
lineage reset for the SAME golden set, to launder a regressed candidate?

Attack target: baseline.py:326-333 reset gate compares ONLY golden_release_hash.
Hypothesis to break: 'change model_id => reset opens => launder' (four-round #2 recurrence).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rt_helpers import AT, B, approve_baseline, artifact, candidate, fp, raw_product
from insurance_harness.goldenset.baseline import BaselineNotApprovableError

# Production baseline b1, golden set _A (lowercase), value_accuracy=1.0
b1 = artifact(baseline_id="b1", fingerprint=fp())
prod = approve_baseline(b1, candidate(b1, value_accuracy=1.0), approved_by="claude", approved_at=AT)
print("prod approved: golden=", prod.fingerprint.golden_release_hash[:8], "va=1.0")

# Candidate: SAME golden set (_A), new baseline_id, only change model_id (non-golden),
# regressed value 1.0 -> 0.99 (still above 0.98 gate threshold). Try to open reset.
for changed_dim in ("model_id", "schema_version", "prompt_version", "template_profile", "source_profile"):
    b2fp = fp(**{changed_dim: "CHANGED"})   # golden_release_hash still _A
    b2 = artifact(baseline_id="b2-" + changed_dim, fingerprint=b2fp,
                  products=(raw_product(pred_sha256=B),))
    cand = candidate(b2, value_accuracy=0.99)
    try:
        rec = approve_baseline(
            b2, cand, approved_by="attacker", prior=[prod],
            allow_lineage_reset=True, lineage_reset_reason="rebrand+change " + changed_dim,
            approved_at=AT,
        )
        print(f"*** BYPASS via {changed_dim}: reset approved regressed candidate! version=",
              rec.version, "lineage_reset=", rec.lineage_reset)
    except BaselineNotApprovableError as e:
        print(f"REJECTED (change {changed_dim}): {str(e)[:70]}")
