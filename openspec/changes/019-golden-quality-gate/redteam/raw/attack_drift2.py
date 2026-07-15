"""Deeper drift probes: disputed golden, evidence via dataset_root, per-field==global
single-field halluc equality, macro_f1 blindness to unknown fabrications."""
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import insurance_harness.goldenset.pdf as pdfmod
from insurance_harness.goldenset import (
    Evidence, GoldenRecord, RunFingerprint, build_profile, compare_baselines,
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


def _rec(product, field_id, value, tri="present", *, with_evidence=True, disputed=False):
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if (value and with_evidence) else [],
        disputed=disputed, disputed_reason="meta_mismatch" if disputed else None,
        annotator_model="m", schema_version="v1.1+x", created_at=_AT,
    )


def hr(label):
    print("\n" + "=" * 70 + f"\n{label}\n" + "=" * 70)


class _Pg:
    def __init__(self, n, t):
        self.page_no = n
        self.text = t


def drift_of(prof, ev):
    d = []
    g = prof.global_metrics
    if g.micro_f1 != ev.micro.f1: d.append(f"micro_f1 {g.micro_f1}!={ev.micro.f1}")
    if g.macro_f1 != ev.macro_f1: d.append(f"macro_f1 {g.macro_f1}!={ev.macro_f1}")
    if g.hallucination_rate != ev.hallucination_rate: d.append(f"halluc {g.hallucination_rate}!={ev.hallucination_rate}")
    if g.evidence_accuracy != ev.evidence_accuracy: d.append(f"evidence {g.evidence_accuracy}!={ev.evidence_accuracy}")
    if set(prof.fields) != set(ev.per_field): d.append(f"fieldset {set(prof.fields)}!={set(ev.per_field)}")
    for f in set(prof.fields) & set(ev.per_field):
        pm, es = prof.field(f), ev.per_field[f]
        if (pm.precision, pm.recall, pm.f1) != (es.precision, es.recall, es.f1):
            d.append(f"{f} PRF prof={(pm.precision,pm.recall,pm.f1)} ev={(es.precision,es.recall,es.f1)}")
    return d


# ---- disputed golden interactions ----
hr("DRIFT: disputed golden — field vanishing, support, pred-only reclassification")
cases = {
  "field only disputed golden + pred-only present (=> unknown field, global-only)":
    ([_rec("P0", "f1", "A", disputed=True)],
     [_rec("P0", "f1", "A"), _rec("Q0", "f1", "fab")]),
  "field mixed disputed/live + pred-only present on same field":
    ([_rec("P0", "f1", "A", disputed=True), _rec("P1", "f1", "B"), _rec("P2", "f1", "C")],
     [_rec("P1", "f1", "B"), _rec("P2", "f1", "C"), _rec("Q0", "f1", "fab")]),
  "disputed on one field, live on another, cross fabrications":
    ([_rec("P0", "f1", "A", disputed=True), _rec("P1", "f2", "B")],
     [_rec("P1", "f2", "B"), _rec("Q0", "f1", "fab"), _rec("Q1", "f2", "fab")]),
}
for name, (g, p) in cases.items():
    prof, ev = _bp(g, p), evaluate(g, p)
    d = drift_of(prof, ev)
    print(f"[{'DRIFT!' if d else 'consistent'}] {name}")
    for x in d: print("     ", x)
    print("      profile.fields=%s support=%s" % (
        sorted(prof.fields), {k: prof.field(k).support for k in prof.fields}))

# ---- single-field: per-field hallucination_rate MUST equal global ----
hr("DRIFT: single known field => per-field halluc == global halluc (strong check)")
for name, (g, p) in {
  "1 correct + N fab": ([_rec("P0", "f1", "A")],
                        [_rec("P0", "f1", "A")] + [_rec(f"Z{i}", "f1", "fab") for i in range(7)]),
  "all golden absent, all pred present": ([_rec(f"P{i}", "f1", None, "absent_explicitly") for i in range(5)],
                                          [_rec(f"P{i}", "f1", "fab") for i in range(5)]),
  "mix present/absent golden + fab": ([_rec("P0", "f1", "A"), _rec("P1", "f1", None, "absent_explicitly")],
                                       [_rec("P0", "f1", "A"), _rec("P1", "f1", "boom"), _rec("Z0", "f1", "fab")]),
}.items():
    prof = _bp(g, p)
    pf = prof.field("f1").hallucination_rate
    gl = prof.global_metrics.hallucination_rate
    print(f"[{'MISMATCH!' if abs(pf-gl)>1e-12 else 'equal'}] {name}: per-field={pf:.4f} global={gl:.4f}")

# ---- macro_f1 blindness to unknown fabrications, but micro+halluc catch ----
hr("REGRESSION: unknown-field fabrications — does macro_f1 miss them? do micro/halluc catch?")
gold = [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
clean = _bp(gold, [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)])
dirty = _bp(gold, [_rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
                  + [_rec(f"Z{i}", f"fUNK{i}", "fab") for i in range(50)])
print("clean : macro=%.4f micro=%.4f halluc=%.4f" % (
    clean.global_metrics.macro_f1, clean.global_metrics.micro_f1, clean.global_metrics.hallucination_rate))
print("dirty : macro=%.4f micro=%.4f halluc=%.4f" % (
    dirty.global_metrics.macro_f1, dirty.global_metrics.micro_f1, dirty.global_metrics.hallucination_rate))
res = compare_baselines(clean, dirty)
print("macro_f1 blind to unknown fab? ", clean.global_metrics.macro_f1 == dirty.global_metrics.macro_f1)
print("compare_baselines eligible?    ", res.eligible)
print("failure metrics                :", [f.metric for f in res.failures])
assert not res.eligible, "REGRESSION BYPASS: unknown fabrications not caught!"
print(">> Even though macro_f1 is blind, micro_f1 + global hallucination catch it.")

# ---- evidence via dataset_root: field-set / PRF stay consistent ----
hr("DRIFT: evidence via dataset_root does not perturb field-set or PRF")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    pdfmod.extract_pages = lambda _p: [_Pg(1, "AAABBBCCC")]
    for pid in ("P0", "P1"):
        (root / f"产品{pid}").mkdir(parents=True, exist_ok=True)
        (root / f"产品{pid}" / "d.pdf").write_text("x", encoding="utf-8")
    g = [_rec("P0", "f1", "AAA"), _rec("P1", "f1", "BBB")]
    p = [_rec("P0", "f1", "AAA"), _rec("P1", "f1", "ZZZ"), _rec("Q0", "f1", "fab")]
    prof, ev = _bp(g, p, dataset_root=root), evaluate(g, p, dataset_root=root)
    d = drift_of(prof, ev)
    print(f"[{'DRIFT!' if d else 'consistent'}] with dataset_root")
    for x in d: print("     ", x)
    print("      f1 evidence_accuracy=", prof.field("f1").evidence_accuracy,
          " global evidence=", prof.global_metrics.evidence_accuracy)

print("\nDRIFT2 DONE")
