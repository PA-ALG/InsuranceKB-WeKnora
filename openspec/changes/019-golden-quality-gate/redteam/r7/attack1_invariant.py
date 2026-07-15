"""Attack 1 + 2: invariant falsification + evaluate<->build_profile drift.

Core invariant under test (codex 六轮 #1):
  Appending disputed-only golden records AND their predictions must NOT change
  ANY metric (field/global hallucination, P/R/F1, support, evidence, confusion,
  value_accuracy, tri_state_confusion, macro/micro F1) nor field_verdict eligibility.

We compute a FULL canonical metric dict from BOTH evaluate() and build_profile()
before and after appending disputed samples, and assert equality (except the
explicitly-reporting field golden_disputed_excluded).
"""
from datetime import UTC, datetime

from insurance_harness.goldenset.eval import evaluate, excluded_disputed_keys
from insurance_harness.goldenset.profile import build_profile
from insurance_harness.goldenset.baseline import RunFingerprint
from insurance_harness.goldenset.records import GoldenRecord, Evidence

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_ART = "a" * 64


def _fp(**ov):
    base = dict(git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
                template_profile="t1", source_profile="s1", golden_release_hash="a" * 64)
    base.update(ov)
    return RunFingerprint(**base)


def _rec(product, field_id, value, tri="present", *, with_evidence=True, disputed=False):
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if (value and with_evidence) else [],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT, disputed=disputed,
    )


def _golden(field_id, n=10):
    return [_rec(f"P{i}", field_id, f"值{i}") for i in range(n)]


def eval_metrics(golden, pred):
    """Canonical dict of ALL evaluate() outputs except golden_disputed_excluded."""
    r = evaluate(golden, pred)
    return {
        "micro": (r.micro.tp, r.micro.fp, r.micro.fn,
                  round(r.micro.precision, 12), round(r.micro.recall, 12), round(r.micro.f1, 12)),
        "per_field": {fid: (s.tp, s.fp, s.fn, round(s.precision, 12), round(s.recall, 12), round(s.f1, 12))
                      for fid, s in sorted(r.per_field.items())},
        "confusion": {f"{g}>{p}": c for (g, p), c in sorted(r.confusion.items())},
        "hallucination_rate": round(r.hallucination_rate, 12),
        "evidence_accuracy": r.evidence_accuracy,
        "macro_f1": round(r.macro_f1, 12),
        "pred_only_keys": r.pred_only_keys,
        "golden_only_keys": r.golden_only_keys,
        "evidence_mismatch_count": r.evidence_mismatch_count,
        "errors": sorted((e.product_id, e.field_id, e.kind, e.category, e.golden_value, e.pred_value)
                         for e in r.errors),
        "category_counts": dict(sorted(r.category_counts.items())),
    }


def profile_metrics(golden, pred):
    """Canonical dict of ALL build_profile() field + global metrics + verdicts."""
    prof = build_profile(golden, pred, _fp(), artifact_sha256=_ART)
    fields = {}
    for fid, m in sorted(prof.fields.items()):
        v = prof.field_verdict(fid)
        fields[fid] = {
            "support": m.support,
            "value_accuracy": round(m.value_accuracy, 12),
            "hallucination_rate": round(m.hallucination_rate, 12),
            "evidence_accuracy": m.evidence_accuracy,
            "precision": round(m.precision, 12),
            "recall": round(m.recall, 12),
            "f1": round(m.f1, 12),
            "tri_state_confusion": dict(sorted(m.tri_state_confusion.items())),
            "verdict_eligible": v.eligible,
            "verdict_failures": tuple(v.failures),
        }
    g = prof.global_metrics
    return {
        "fields": fields,
        "global": {
            "micro_f1": round(g.micro_f1, 12),
            "macro_f1": round(g.macro_f1, 12),
            "hallucination_rate": round(g.hallucination_rate, 12),
            "evidence_accuracy": g.evidence_accuracy,
            "unresolved_count": g.unresolved_count,
        },
    }


def all_metrics(golden, pred):
    return {"eval": eval_metrics(golden, pred), "profile": profile_metrics(golden, pred)}


# ---------------- base scenarios (golden, pred) ----------------
def base_scenarios():
    scen = {}
    # perfect replay
    g = _golden("f1", 10)
    scen["perfect"] = (g, list(g))
    # partial value errors
    g = _golden("f1", 8)
    p = [_rec(f"P{i}", "f1", "错" if i < 3 else f"值{i}") for i in range(8)]
    scen["value_errors"] = (g, p)
    # hallucination (absent golden, present pred) + missing + pred-only fabrication
    g = [_rec("PX", "f1", None, "absent_explicitly"), *_golden("f1", 4)]
    p = [_rec("PX", "f1", "编造"), *[_rec(f"P{i}", "f1", f"值{i}") for i in range(3)],
         _rec("QQ", "f1", "出界伪造")]
    scen["mixed_halluc"] = (g, p)
    # multi-field
    g = [_rec("P0", "f1", "A"), _rec("P1", "f1", "B"),
         _rec("P2", "f2", None, "absent_explicitly"), _rec("P3", "f2", "C")]
    p = [_rec("P0", "f1", "A"), _rec("P1", "f1", "错"), _rec("P2", "f2", "编造"),
         _rec("P3", "f2", "C"), _rec("P9", "f9", "多余")]
    scen["multifield"] = (g, p)
    # all absent
    g = [_rec("P0", "f1", None, "absent_explicitly")]
    scen["all_absent"] = (g, [_rec("P0", "f1", None, "absent_explicitly")])
    # empty pred
    scen["empty_pred"] = (_golden("f1", 5), [])
    return scen


# --------------- disputed-append variants ---------------
# each returns extra (golden_records, pred_records) appended to a base
def disputed_variants():
    variants = {}
    # disputed-only present, with pred present (value match), known field f1
    variants["disp_present_pred_present_known"] = (
        [_rec("D0", "f1", "争议", disputed=True)],
        [_rec("D0", "f1", "争议")],
    )
    # disputed-only present, pred present value MISMATCH
    variants["disp_pred_mismatch"] = (
        [_rec("D1", "f1", "金标争议", disputed=True)],
        [_rec("D1", "f1", "完全不同的预测")],
    )
    # disputed-only, pred ABSENT
    variants["disp_pred_absent"] = (
        [_rec("D2", "f1", "争议", disputed=True)],
        [_rec("D2", "f1", None, "absent_explicitly")],
    )
    # disputed-only, NO pred
    variants["disp_no_pred"] = (
        [_rec("D3", "f1", "争议", disputed=True)], [],
    )
    # disputed-only absent_explicitly golden + pred present
    variants["disp_absent_golden_pred_present"] = (
        [_rec("D4", "f1", None, "absent_explicitly", disputed=True)],
        [_rec("D4", "f1", "编造")],
    )
    # disputed-only unknown field id (fnew not in base golden), pred present
    variants["disp_unknown_field"] = (
        [_rec("D5", "fZZZ", "争议", disputed=True)],
        [_rec("D5", "fZZZ", "预测")],
    )
    # disputed-only, pred WITHOUT evidence
    variants["disp_pred_no_evidence"] = (
        [_rec("D6", "f1", "争议", disputed=True)],
        [_rec("D6", "f1", "预测", with_evidence=False)],
    )
    # many disputed-only (超 5% dilution attempt) present preds
    variants["many_disputed_present"] = (
        [_rec(f"M{i}", "f1", "争议", disputed=True) for i in range(20)],
        [_rec(f"M{i}", "f1", "编造") for i in range(20)],
    )
    # disputed-only unknown field + its OWN pred only (isolated: must be inert)
    variants["disp_unknown_field_isolated"] = (
        [_rec("D7", "fYYY", "争议", disputed=True)],
        [_rec("D7", "fYYY", "预测")],
    )
    # multiple disputed records SAME key (D9,f1) + one pred
    variants["dup_disputed_same_key"] = (
        [_rec("D9", "f1", "争议1", disputed=True), _rec("D9", "f1", "争议2", disputed=True)],
        [_rec("D9", "f1", "预测")],
    )
    return variants


def run():
    bases = base_scenarios()
    variants = disputed_variants()
    failures = []
    checked = 0
    for bname, (g, p) in bases.items():
        before = all_metrics(g, p)
        for vname, (dg, dp) in variants.items():
            g2 = list(g) + list(dg)
            p2 = list(p) + list(dp)
            after = all_metrics(g2, p2)
            checked += 1
            if before != after:
                # find diffs
                diffs = _deep_diff(before, after)
                failures.append((bname, vname, diffs))
    print(f"checked {checked} (base x variant) combinations")
    if not failures:
        print("INVARIANT HELD: no metric changed on any base x variant.")
    else:
        print(f"!!! INVARIANT VIOLATED in {len(failures)} combos:")
        for bname, vname, diffs in failures:
            print(f"\n  base={bname} variant={vname}")
            for d in diffs:
                print(f"     {d}")
    return failures


def _deep_diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += _deep_diff(a.get(k, "<MISSING>"), b.get(k, "<MISSING>"), f"{path}.{k}")
    else:
        if a != b:
            out.append(f"{path}: BEFORE={a!r}  AFTER={b!r}")
    return out


if __name__ == "__main__":
    run()
