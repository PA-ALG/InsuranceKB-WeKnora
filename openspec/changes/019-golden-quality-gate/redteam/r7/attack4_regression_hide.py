"""Attack directions 3a + 3b:
 3a: does validate._check_disputed_rate actually cap >5% per product?
 3b: can a WORSE candidate hide degradation from compare_baselines by marking the
     keys it fails on as disputed (staying within the per-product 5% cap)?
"""
from datetime import UTC, datetime

from insurance_harness.goldenset.validate import _check_disputed_rate
from insurance_harness.goldenset.eval import evaluate
from insurance_harness.goldenset.profile import build_profile, compare_baselines
from insurance_harness.goldenset.baseline import RunFingerprint
from insurance_harness.goldenset.records import GoldenRecord, Evidence

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_ART = "a" * 64


def _fp(**ov):
    base = dict(git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
                template_profile="t1", source_profile="s1", golden_release_hash="a" * 64)
    base.update(ov)
    return RunFingerprint(**base)


def _rec(product, field_id, value, tri="present", *, disputed=False):
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if value else [],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT, disputed=disputed,
    )


def _bp(g, p, fp=None):
    return build_profile(g, p, fp or _fp(), artifact_sha256=_ART)


print("=" * 70)
print("3a: validator disputed-rate cap (max=0.05, strict >)")
print("=" * 70)
for n, d in [(20, 1), (20, 2), (1, 1), (19, 1), (40, 2), (40, 3)]:
    recs = [_rec("P0", f"f{i}", "v", disputed=(i < d)) for i in range(n)]
    chk = _check_disputed_rate({"P0": recs}, 0.05)
    rate = d / n
    print(f"  {d}/{n} disputed = {rate:.4f}: passed={chk.passed}  detail={chk.detail}")

print()
print("=" * 70)
print("3b: WORSE candidate hides degradation by disputing the keys it fails")
print("=" * 70)
# 20 products x 20 fields = 400 keys. M1 correct on all.
prods = [f"P{i}" for i in range(20)]
fields = [f"f{j}" for j in range(20)]
golden_M1 = [_rec(pr, fj, f"{pr}-{fj}") for pr in prods for fj in fields]
pred_M1 = [_rec(pr, fj, f"{pr}-{fj}") for pr in prods for fj in fields]  # all correct
approved = _bp(golden_M1, pred_M1)

# M2 is WORSE: it gets (P0,f0) WRONG.
pred_M2_wrong = [
    _rec(pr, fj, ("XX_WRONG" if (pr, fj) == ("P0", "f0") else f"{pr}-{fj}"))
    for pr in prods for fj in fields
]
# Honest candidate: same golden as M1, no disputed hiding.
honest = _bp(golden_M1, pred_M2_wrong, _fp(model_id="m2"))
res_honest = compare_baselines(approved, honest)
print(f"\n  Honest M2 (no hiding): compare eligible={res_honest.eligible}")
print(f"    failures: {[(f.metric, f.baseline, f.candidate) for f in res_honest.failures]}")

# Cheating candidate: mark (P0,f0) disputed in ITS golden set (P0 has 20 recs -> 5%, passes cap).
golden_M2_cheat = [
    _rec(pr, fj, f"{pr}-{fj}", disputed=((pr, fj) == ("P0", "f0")))
    for pr in prods for fj in fields
]
# verify cap passes for P0
p0_recs = [r for r in golden_M2_cheat if r.product_id == "P0"]
cap = _check_disputed_rate({"P0": p0_recs}, 0.05)
print(f"\n  Cheat golden: P0 disputed rate check passed={cap.passed} ({cap.detail or 'ok'})")
cheat = _bp(golden_M2_cheat, pred_M2_wrong, _fp(model_id="m2"))
res_cheat = compare_baselines(approved, cheat)
print(f"  Cheat M2 (dispute the failing key): compare eligible={res_cheat.eligible}")
print(f"    failures: {[(f.metric, f.baseline, f.candidate) for f in res_cheat.failures]}")

# Also show the raw eval: honest M2 has a real error; cheat hides it.
ev_h = evaluate(golden_M1, pred_M2_wrong)
ev_c = evaluate(golden_M2_cheat, pred_M2_wrong)
print(f"\n  eval honest: micro_f1={ev_h.micro.f1:.5f} f0 field stats tp/fp/fn="
      f"{(lambda s:(s.tp,s.fp,s.fn))(ev_h.per_field['f0'])}")
print(f"  eval cheat : micro_f1={ev_c.micro.f1:.5f} f0 field stats tp/fp/fn="
      f"{(lambda s:(s.tp,s.fp,s.fn))(ev_c.per_field['f0'])}")
print(f"\n  >>> Degradation hidden? honest_flags_regression={not res_honest.eligible} "
      f"cheat_flags_regression={not res_cheat.eligible}")
