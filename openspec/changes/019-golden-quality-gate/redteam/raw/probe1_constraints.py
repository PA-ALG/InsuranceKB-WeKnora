"""Probe 1: does the constructor really reject illegal domain values?

Attack directions 1-4: try to construct FieldMetrics / GlobalMetrics / Thresholds /
BaselineProductArtifacts with NaN / +-inf / out-of-range rate / negative count / bool,
and report for each whether pydantic BLOCKED it (fix works) or ACCEPTED it (bypass).
"""
import math
from pydantic import ValidationError

from insurance_harness.goldenset.profile import (
    FieldMetrics, GlobalMetrics, AutomationThresholds, RegressionThresholds,
    RegressionFailure,
)
from insurance_harness.goldenset.baseline import BaselineProductArtifacts

NAN = float("nan")
INF = float("inf")
NINF = float("-inf")

def base_fieldmetrics(**over):
    kw = dict(field_id="f", support=10, value_accuracy=1.0, hallucination_rate=0.0,
              evidence_accuracy=1.0, tri_state_confusion={})
    kw.update(over)
    return kw

def try_construct(label, ctor, kw):
    try:
        obj = ctor(**kw)
        print(f"  [ACCEPTED / potential BYPASS] {label} -> {ctor.__name__} built; "
              f"offending field value = {kw}")
        return obj
    except ValidationError as e:
        # compress
        msgs = "; ".join(sorted({err['type'] for err in e.errors()}))
        print(f"  [BLOCKED] {label}: {msgs}")
        return None

print("=== FieldMetrics.value_accuracy (Rate) ===")
for label, v in [("NaN", NAN), ("+inf", INF), ("-inf", NINF), ("2.0", 2.0),
                 ("-0.5", -0.5), ("1.0 ok", 1.0), ("0.0 ok", 0.0),
                 ("bool True", True), ('str "2.0"', "2.0"), ('str "nan"', "nan"),
                 ('str "inf"', "inf")]:
    try_construct(f"value_accuracy={label}", FieldMetrics, base_fieldmetrics(value_accuracy=v))

print("=== FieldMetrics.evidence_accuracy (Rate | None) -- the linchpin ===")
for label, v in [("NaN", NAN), ("+inf", INF), ("-inf", NINF), ("2.0", 2.0),
                 ("-0.5", -0.5), ("None ok", None), ("1.0 ok", 1.0),
                 ('str "nan"', "nan"), ("bool True", True)]:
    try_construct(f"evidence_accuracy={label}", FieldMetrics, base_fieldmetrics(evidence_accuracy=v))

print("=== FieldMetrics.support (NonNegativeInt) ===")
for label, v in [("-1", -1), ("0 ok", 0), ("bool True", True), ("bool False", False),
                 ("1.5 float", 1.5), ('str "-1"', "-1")]:
    try_construct(f"support={label}", FieldMetrics, base_fieldmetrics(support=v))

print("=== GlobalMetrics.evidence_accuracy (Rate | None) ===")
for label, v in [("NaN", NAN), ("2.0", 2.0), ("-inf", NINF)]:
    try_construct(f"g.evidence_accuracy={label}", GlobalMetrics, dict(evidence_accuracy=v))
print("=== GlobalMetrics.micro_f1 / unresolved_count ===")
try_construct("micro_f1=NaN", GlobalMetrics, dict(micro_f1=NAN))
try_construct("micro_f1=2.0", GlobalMetrics, dict(micro_f1=2.0))
try_construct("unresolved_count=-1", GlobalMetrics, dict(unresolved_count=-1))
try_construct("unresolved_count=True", GlobalMetrics, dict(unresolved_count=True))

print("=== AutomationThresholds (can we set a permissive threshold?) ===")
try_construct("hallucination_rate_max=2.0", AutomationThresholds, dict(hallucination_rate_max=2.0))
try_construct("hallucination_rate_max=inf", AutomationThresholds, dict(hallucination_rate_max=INF))
try_construct("value_accuracy_min=-1", AutomationThresholds, dict(value_accuracy_min=-1.0))
try_construct("support_min=-5", AutomationThresholds, dict(support_min=-5))

print("=== RegressionThresholds (can we set a huge tolerance to hide regressions?) ===")
try_construct("max_micro_f1_drop=2.0", RegressionThresholds, dict(max_micro_f1_drop=2.0))
try_construct("max_micro_f1_drop=inf", RegressionThresholds, dict(max_micro_f1_drop=INF))
try_construct("max_field_hallucination_increase=NaN", RegressionThresholds,
              dict(max_field_hallucination_increase=NAN))

print("=== RegressionFailure (FiniteFloat: expect NaN/inf blocked, out-of-range ALLOWED) ===")
try_construct("baseline=NaN", RegressionFailure, dict(metric="m", baseline=NAN, candidate=0.0, allowed=1.0))
try_construct("baseline=inf", RegressionFailure, dict(metric="m", baseline=INF, candidate=0.0, allowed=1.0))
try_construct("baseline=2.0 (out of [0,1])", RegressionFailure, dict(metric="m", baseline=2.0, candidate=0.0, allowed=1.0))
try_construct("candidate=-9.0", RegressionFailure, dict(metric="m", baseline=1.0, candidate=-9.0, allowed=1.0))

print("=== BaselineProductArtifacts counts (NonNegativeInt) ===")
def base_bpa(**over):
    kw = dict(product_id="p", run_manifest_sha256="a"*64, pred_sha256="b"*64, pred_count=1,
              dead_letter_sha256="c"*64, dead_letter_count=0, judge_queue_sha256="d"*64,
              judge_queue_count=0, judgements_sha256="e"*64, resolved_judgement_count=0,
              keypoints_status="complete", keypoints_sha256="f"*64, keypoints_pending_count=0,
              eval_report_sha256="0"*64, unresolved_judge_count=0, unresolved_dead_letter_count=0)
    kw.update(over)
    return kw
try_construct("unresolved_judge_count=-1", BaselineProductArtifacts, base_bpa(unresolved_judge_count=-1))
try_construct("unresolved_dead_letter_count=-3", BaselineProductArtifacts, base_bpa(unresolved_dead_letter_count=-3))
try_construct("pred_count=True", BaselineProductArtifacts, base_bpa(pred_count=True))
try_construct("unresolved_judge_count=True", BaselineProductArtifacts, base_bpa(unresolved_judge_count=True))
