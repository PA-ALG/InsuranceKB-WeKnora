"""Probe 2: end-to-end. Does the NaN/out-of-range attack reach a false PASS?

Part A: the INTENDED attack via the normal constructor -- inject NaN into a candidate
        profile's metric to dodge field_verdict / compare_baselines. Expect: BLOCKED.
Part B: prove the domain type is the SOLE load-bearing guard -- IF validation is bypassed
        (model_construct), field_verdict says eligible and compare_baselines says
        no-regression on a NaN metric. This is the hazard the Rate type exists to stop.
"""
import math
from pydantic import ValidationError

from insurance_harness.goldenset.profile import (
    FieldMetrics, GlobalMetrics, QualityProfile, AutomationThresholds,
    RegressionThresholds, compare_baselines,
)
from insurance_harness.goldenset.baseline import RunFingerprint

NAN = float("nan")
FP = RunFingerprint(git_sha="g", schema_version="s", model_id="m", prompt_version="p",
                    template_profile="t", source_profile="src", golden_release_hash="h")

def make_field(**over):
    kw = dict(field_id="premium", support=10, value_accuracy=1.0, hallucination_rate=0.0,
              evidence_accuracy=1.0, tri_state_confusion={})
    kw.update(over)
    return FieldMetrics(**kw)

print("############ PART A: intended attack through the normal constructor ############")
print("Attack A1: candidate field with value_accuracy=NaN so `NaN < 0.98` is False -> dodge verdict")
try:
    bad = make_field(value_accuracy=NAN)
    print("  [BYPASS] built FieldMetrics with NaN value_accuracy")
except ValidationError as e:
    print(f"  [BLOCKED] {sorted({x['type'] for x in e.errors()})}")

print("Attack A2: candidate GlobalMetrics micro_f1=NaN so `base-NaN > max_drop` is False -> dodge regression")
try:
    bad = GlobalMetrics(micro_f1=NAN)
    print("  [BYPASS] built GlobalMetrics with NaN micro_f1")
except ValidationError as e:
    print(f"  [BLOCKED] {sorted({x['type'] for x in e.errors()})}")

print("Attack A3: candidate field hallucination_rate=-5.0 (below range) to look clean")
try:
    bad = make_field(hallucination_rate=-5.0)
    print("  [BYPASS] built FieldMetrics with hallucination_rate=-5.0")
except ValidationError as e:
    print(f"  [BLOCKED] {sorted({x['type'] for x in e.errors()})}")

print("Attack A4: full regression-dodge scenario -- try to build a candidate profile whose")
print("           micro_f1 is NaN, approved baseline micro_f1=0.9, tolerance 0.0 (any drop fails).")
good_global = GlobalMetrics(micro_f1=0.9, macro_f1=0.9, hallucination_rate=0.0)
current = QualityProfile(profile_version="1", artifact_sha256="x", baseline_approval_sha256="",
                         fingerprint=FP, fields={"premium": make_field()},
                         global_metrics=good_global)
try:
    cand_global = GlobalMetrics(micro_f1=NAN, macro_f1=0.9, hallucination_rate=0.0)
    candidate = QualityProfile(profile_version="1", artifact_sha256="x",
                               baseline_approval_sha256="", fingerprint=FP,
                               fields={"premium": make_field()}, global_metrics=cand_global)
    res = compare_baselines(current, candidate, RegressionThresholds())
    print(f"  [BYPASS] candidate built; regression eligible(no-regression)={res.eligible}")
except ValidationError as e:
    print(f"  [BLOCKED at construction] {sorted({x['type'] for x in e.errors()})}")

print()
print("############ PART B: is the Rate type load-bearing? (bypass validation on purpose) ############")
print("Using model_construct (skips ALL validation) to place NaN where the constructor forbids it,")
print("to observe what the downstream comparison would do if such a value ever slipped in.")

# B1: field_verdict on a NaN value_accuracy
nan_field = FieldMetrics.model_construct(field_id="premium", support=10, value_accuracy=NAN,
                                         hallucination_rate=NAN, evidence_accuracy=NAN,
                                         precision=0.0, recall=0.0, f1=0.0, tri_state_confusion={})
prof = QualityProfile.model_construct(profile_version="1", artifact_sha256="x",
                                      baseline_approval_sha256="", fingerprint=FP,
                                      fields={"premium": nan_field}, global_metrics=GlobalMetrics())
verdict = prof.field_verdict("premium", AutomationThresholds())
print(f"  field_verdict on all-NaN metrics: eligible={verdict.eligible} failures={verdict.failures}")
print(f"    -> demonstrates: NaN < 0.98 == {NAN < 0.98}, NaN > 0.01 == {NAN > 0.01} "
      f"(both False -> no failure recorded)")

# B2: compare_baselines with a NaN candidate micro_f1
cur = QualityProfile.model_construct(profile_version="1", artifact_sha256="x",
    baseline_approval_sha256="", fingerprint=FP, fields={},
    global_metrics=GlobalMetrics.model_construct(micro_f1=0.9, macro_f1=0.9,
        hallucination_rate=0.0, evidence_accuracy=None, unresolved_count=0))
cand = QualityProfile.model_construct(profile_version="1", artifact_sha256="x",
    baseline_approval_sha256="", fingerprint=FP, fields={},
    global_metrics=GlobalMetrics.model_construct(micro_f1=NAN, macro_f1=NAN,
        hallucination_rate=0.0, evidence_accuracy=None, unresolved_count=0))
res = compare_baselines(cur, cand, RegressionThresholds())
print(f"  compare_baselines(base micro_f1=0.9 -> candidate micro_f1=NaN, tol=0): "
      f"no-regression={res.eligible}  (true F1 collapsed to NaN but gate says clean)")
print(f"    -> demonstrates: 0.9 - NaN > 0.0 == {0.9 - NAN > 0.0} (False -> no regression recorded)")
print()
print("CONCLUSION: the NaN false-pass hazard is real, and the ONLY thing stopping it is the")
print("Rate/allow_inf_nan constructor validation (Part A: all blocked). No normal-API path")
print("reaches the Part B state; model_construct is an explicit validation-skip, not a data path.")
