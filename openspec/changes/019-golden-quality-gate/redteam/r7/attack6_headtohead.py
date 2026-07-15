"""Attack direction 2 (crisp head-to-head): evaluate vs build_profile on the exact
cases the fix targets. Proves both paths treat disputed keys identically (no path
counts a disputed-key present prediction as hallucination while the other doesn't).
"""
from datetime import UTC, datetime

from insurance_harness.goldenset.eval import evaluate, excluded_disputed_keys
from insurance_harness.goldenset.profile import build_profile
from insurance_harness.goldenset.baseline import RunFingerprint
from insurance_harness.goldenset.records import GoldenRecord, Evidence

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_ART = "a" * 64


def _fp():
    return RunFingerprint(git_sha="abc", schema_version="v1.1+x", model_id="m1",
                          prompt_version="p1", template_profile="t1", source_profile="s1",
                          golden_release_hash="a" * 64)


def _rec(product, field_id, value, tri="present", *, disputed=False):
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if value else [],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT, disputed=disputed,
    )


def _bp(g, p):
    return build_profile(g, p, _fp(), artifact_sha256=_ART)


print("CASE A: field 'fSolo' whose ONLY golden is disputed; model predicts it present")
golden = [_rec("D0", "fSolo", "争议", disputed=True)]
pred = [_rec("D0", "fSolo", "模型预测present")]
ev = evaluate(golden, pred)
prof = _bp(golden, pred)
print(f"  excluded_disputed_keys = {excluded_disputed_keys(golden)}")
print(f"  evaluate: hallucination_rate={ev.hallucination_rate} pred_only_keys={ev.pred_only_keys} "
      f"micro(tp,fp,fn)=({ev.micro.tp},{ev.micro.fp},{ev.micro.fn}) "
      f"'fSolo' in per_field={('fSolo' in ev.per_field)}")
print(f"  build_profile: global_hall={prof.global_metrics.hallucination_rate} "
      f"'fSolo' in fields={('fSolo' in prof.fields)}")
a_ok = (ev.hallucination_rate == 0.0 and ev.micro.fp == 0 and "fSolo" not in ev.per_field
        and prof.global_metrics.hallucination_rate == 0.0 and "fSolo" not in prof.fields)
print(f"  -> both paths agree NOT hallucination, no phantom field: {a_ok}")

print("\nCASE A': SAME shape but golden NOT disputed (usable absent) -> MUST be hallucination")
golden_u = [_rec("D0", "fSolo", None, "absent_explicitly")]
pred_u = [_rec("D0", "fSolo", "模型预测present")]
ev_u = evaluate(golden_u, pred_u)
prof_u = _bp(golden_u, pred_u)
print(f"  evaluate: hallucination_rate={ev_u.hallucination_rate} micro.fp={ev_u.micro.fp}")
print(f"  build_profile: global_hall={prof_u.global_metrics.hallucination_rate} "
      f"fSolo.hall={prof_u.fields['fSolo'].hallucination_rate}")
aprime_ok = ev_u.hallucination_rate == 1.0 and prof_u.global_metrics.hallucination_rate == 1.0
print(f"  -> disputed exclusion is doing REAL work (non-disputed IS flagged): {aprime_ok}")

print("\nCASE B: disputed-only key shares field_id 'f1' with a real usable key; "
      "disputed pred must NOT leak into f1")
golden = [_rec("P0", "f1", "对", "present"),                       # usable
          _rec("D0", "f1", "争议", "present", disputed=True)]       # disputed-only, same field
pred = [_rec("P0", "f1", "对"),                                    # correct
        _rec("D0", "f1", "对争议键的present预测")]                  # excluded
ev = evaluate(golden, pred)
prof = _bp(golden, pred)
f1e = ev.per_field["f1"]
f1p = prof.fields["f1"]
print(f"  excluded_disputed_keys = {excluded_disputed_keys(golden)}")
print(f"  evaluate f1 (tp,fp,fn)=({f1e.tp},{f1e.fp},{f1e.fn}) hall={ev.hallucination_rate}")
print(f"  build_profile f1 support={f1p.support} value_acc={f1p.value_accuracy} "
      f"hall={f1p.hallucination_rate} confusion={f1p.tri_state_confusion}")
b_ok = (f1e.tp == 1 and f1e.fp == 0 and f1e.fn == 0 and ev.hallucination_rate == 0.0
        and f1p.support == 1 and f1p.hallucination_rate == 0.0
        and f1p.tri_state_confusion == {"present>present": 1})
print(f"  -> disputed pred did NOT leak into real field f1: {b_ok}")

print("\nCASE C: same key both disputed AND usable; pred WRONG -> judged against usable "
      "(value mismatch), key NOT excluded")
golden = [_rec("P0", "f1", "正确金标", "present"),
          _rec("P0", "f1", "争议金标", "present", disputed=True)]  # same key, disputed twin
pred = [_rec("P0", "f1", "错误预测")]
ev = evaluate(golden, pred)
prof = _bp(golden, pred)
f1e = ev.per_field["f1"]
f1p = prof.fields["f1"]
print(f"  excluded_disputed_keys = {excluded_disputed_keys(golden)} (should be empty)")
print(f"  evaluate f1 (tp,fp,fn)=({f1e.tp},{f1e.fp},{f1e.fn})")
print(f"  build_profile f1 support={f1p.support} value_acc={f1p.value_accuracy}")
c_ok = (excluded_disputed_keys(golden) == set() and f1e.tp == 0 and f1e.fp == 1
        and f1e.fn == 1 and f1p.value_accuracy == 0.0 and f1p.support == 1)
print(f"  -> usable golden wins; wrong pred correctly penalized: {c_ok}")

print("\n" + ("ALL HEAD-TO-HEAD CASES PASSED (two paths consistent)"
              if all([a_ok, aprime_ok, b_ok, c_ok]) else "SOME CASE FAILED"))
