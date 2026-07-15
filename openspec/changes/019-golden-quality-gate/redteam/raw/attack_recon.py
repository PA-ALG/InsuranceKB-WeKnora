"""Adversarial recon: try to break build_profile per-field aggregation (019)."""
from datetime import UTC, datetime
from pathlib import Path

from insurance_harness.goldenset import (
    Evidence, GoldenRecord, RunFingerprint, build_profile,
)
from insurance_harness.goldenset.eval import evaluate

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_ART = "a" * 64


def _fp(**ov):
    base = dict(git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
                template_profile="t1", source_profile="s1", golden_release_hash="rh1")
    base.update(ov)
    return RunFingerprint(**base)


def _bp(golden, pred, fp=None, *, dataset_root=None):
    return build_profile(golden, pred, fp or _fp(), artifact_sha256=_ART, dataset_root=dataset_root)


def _rec(product, field_id, value, tri="present", *, with_evidence=True):
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if (value and with_evidence) else [],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT,
    )


def hr(label):
    print("\n" + "=" * 70 + f"\n{label}\n" + "=" * 70)


# ===================================================================
# ATTACK 1: unknown field_id pred-only — invisible at field level?
# ===================================================================
hr("ATTACK 1a: unknown-field present fabrications — do they hit GLOBAL?")
golden = [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
# 10 correct f1 + 100 fabricated on UNKNOWN field ids f_fakeN (never in golden)
pred = ([_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
        + [_rec(f"Z{i}", f"f_fake{i}", "伪造") for i in range(100)])
prof = _bp(golden, pred)
ev = evaluate(golden, pred)
print("profile.fields keys        :", sorted(prof.fields))
print("f1 metrics                 : support=%s value_acc=%s halluc=%s f1=%s" % (
    prof.field("f1").support, prof.field("f1").value_accuracy,
    prof.field("f1").hallucination_rate, prof.field("f1").f1))
print("f_fake* in profile.fields? :", any(k.startswith("f_fake") for k in prof.fields))
print("GLOBAL hallucination_rate  :", prof.global_metrics.hallucination_rate,
      "(evaluate:", ev.hallucination_rate, ")")
print("GLOBAL micro_f1            :", prof.global_metrics.micro_f1,
      "(evaluate:", ev.micro.f1, ")")
print("f1 field_verdict eligible  :", prof.field_verdict("f1").eligible)
print("f_fake0 field_verdict       :", prof.field_verdict("f_fake0").eligible,
      prof.field_verdict("f_fake0").failures)

hr("ATTACK 1b: unknown-field ABSENT/UNKNOWN pred-only — fully invisible?")
golden = [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
pred = ([_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
        + [_rec(f"Z{i}", f"f_fake{i}", None, "absent_explicitly") for i in range(50)]
        + [_rec(f"Y{i}", f"f_ghost{i}", None, "unknown") for i in range(50)])
prof = _bp(golden, pred)
ev = evaluate(golden, pred)
print("GLOBAL hallucination_rate  :", prof.global_metrics.hallucination_rate)
print("GLOBAL micro_f1            :", prof.global_metrics.micro_f1)
print("pred_only_keys (evaluate)  :", ev.pred_only_keys)
print("=> absent/unknown pred-only are not fabrications; expected invisible")

# ===================================================================
# ATTACK 2: support vs denominator dilution
# ===================================================================
hr("ATTACK 2: 1 golden correct + N fabrications same KNOWN field")
for N in (1, 5, 10, 100, 1000):
    golden = [_rec("P0", "f1", "A")]
    pred = [_rec("P0", "f1", "A")] + [_rec(f"Z{i}", "f1", "伪造") for i in range(N)]
    m = _bp(golden, pred).field("f1")
    print(f"N={N:<5} support={m.support} value_acc={m.value_accuracy} "
          f"halluc={m.hallucination_rate:.4f} (expect {N}/{N+1}={N/(N+1):.4f}) f1={m.f1:.4f}")

hr("ATTACK 2b: try to DILUTE halluc below fabrication ratio")
# 10 golden present all correct + 10 fabrications: can adding correct preds dilute below 0.5?
golden = [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
pred = ([_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
        + [_rec(f"Z{i}", "f1", "伪造") for i in range(10)])
m = _bp(golden, pred).field("f1")
print("10 correct + 10 fab same field: halluc=%s (target 0.5) f1=%s (target 0.667)" % (
    m.hallucination_rate, round(m.f1, 4)))

# ===================================================================
# ATTACK 3: build_profile <-> evaluate drift, many scenarios
# ===================================================================
hr("ATTACK 3: profile.field(f).{P,R,F1} vs evaluate.per_field[f]; global too")

def compare(name, golden, pred, dataset_root=None):
    prof = _bp(golden, pred, dataset_root=dataset_root)
    ev = evaluate(golden, pred, dataset_root=dataset_root)
    drift = []
    # global
    if prof.global_metrics.micro_f1 != ev.micro.f1:
        drift.append(f"global.micro_f1 {prof.global_metrics.micro_f1} != {ev.micro.f1}")
    if prof.global_metrics.macro_f1 != ev.macro_f1:
        drift.append(f"global.macro_f1 {prof.global_metrics.macro_f1} != {ev.macro_f1}")
    if prof.global_metrics.hallucination_rate != ev.hallucination_rate:
        drift.append(f"global.halluc {prof.global_metrics.hallucination_rate} != {ev.hallucination_rate}")
    if prof.global_metrics.evidence_accuracy != ev.evidence_accuracy:
        drift.append(f"global.evidence {prof.global_metrics.evidence_accuracy} != {ev.evidence_accuracy}")
    # field-set equality
    if set(prof.fields) != set(ev.per_field):
        drift.append(f"FIELD SET {set(prof.fields)} != {set(ev.per_field)}")
    # per-field P/R/F1
    for f in set(prof.fields) | set(ev.per_field):
        pm = prof.field(f)
        es = ev.per_field.get(f)
        if pm is None or es is None:
            drift.append(f"{f}: one side missing (prof={pm is not None} ev={es is not None})")
            continue
        if pm.precision != es.precision or pm.recall != es.recall or pm.f1 != es.f1:
            drift.append(f"{f}: P/R/F1 prof=({pm.precision:.3f},{pm.recall:.3f},{pm.f1:.3f}) "
                         f"ev=({es.precision:.3f},{es.recall:.3f},{es.f1:.3f})")
    status = "DRIFT!" if drift else "consistent"
    print(f"[{status}] {name}")
    for d in drift:
        print("     ", d)
    return drift


g1 = [_rec("P0", "f1", "A"), _rec("P1", "f1", "B")]
compare("pred-only known field", g1, g1 + [_rec("Q0", "f1", "fab")])
compare("pred-only unknown field", g1, g1 + [_rec("Q0", "fX", "fab")])
compare("absent-only (empty numerator)",
        [_rec("P0", "f1", None, "absent_explicitly")],
        [_rec("P0", "f1", None, "absent_explicitly")])
compare("golden present, pred absent (missed)",
        [_rec("P0", "f1", "A")], [_rec("P0", "f1", None, "absent_explicitly")])
compare("golden absent, pred present (hallu on known key)",
        [_rec("P0", "f1", None, "absent_explicitly")], [_rec("P0", "f1", "fab")])
compare("empty pred", g1, [])
compare("empty golden", [], [_rec("P0", "f1", "fab")])
compare("mixed everything",
        [_rec("P0", "f1", "A"), _rec("P1", "f1", "B"),
         _rec("P2", "f2", None, "absent_explicitly"), _rec("P3", "f2", "C")],
        [_rec("P0", "f1", "A"), _rec("P1", "f1", "错"), _rec("P2", "f2", "编造"),
         _rec("P3", "f2", "C"), _rec("P9", "f9", "多余"), _rec("Q0", "f1", "fab")])
compare("value mismatch + pred-only same field",
        [_rec("P0", "f1", "A"), _rec("P1", "f1", "B")],
        [_rec("P0", "f1", "WRONG"), _rec("P1", "f1", "B"), _rec("Q0", "f1", "fab")])

hr("ATTACK 3b: internal consistency — can field.f1==1.0 while halluc>0?")
# a field that evaluate says perfect (f1=1.0) but build_profile halluc says dirty, or vice versa
scenarios = [
    ("10 correct only", [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)],
     [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]),
    ("10 correct +10 fab", [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)],
     [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)] + [_rec(f"Z{i}", "f1", "fab") for i in range(10)]),
]
for name, g, p in scenarios:
    m = _bp(g, p).field("f1")
    bad = (m.f1 >= 0.999 and m.hallucination_rate > 0.01) or (m.f1 < 0.999 and m.hallucination_rate == 0.0 and m.value_accuracy >= 0.999)
    print(f"[{'INCONSISTENT!' if bad else 'ok'}] {name}: f1={m.f1:.4f} halluc={m.hallucination_rate:.4f} value_acc={m.value_accuracy:.4f}")

print("\nRECON DONE")
