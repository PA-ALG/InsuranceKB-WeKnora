"""Attack: randomized invariant fuzzer (2000 iters).

For each random base (golden, pred):
  Mode A: append DISPUTED-ONLY golden (key absent from base) + random pred for that key.
  Mode B: append DISPUTED golden whose key is ALREADY usable in base (same-key case);
          no extra pred (pred key already exists) -> usable must win, metrics unchanged.
Assert the FULL metric dict (eval + profile + verdicts) is identical before/after,
except golden_disputed_excluded (a reporting counter, excluded from the dict).
"""
import random
from datetime import UTC, datetime

from insurance_harness.goldenset.eval import evaluate
from insurance_harness.goldenset.profile import build_profile
from insurance_harness.goldenset.baseline import RunFingerprint
from insurance_harness.goldenset.records import GoldenRecord, Evidence

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_ART = "a" * 64
TRIS = ["present", "absent_explicitly", "unknown"]
VALS = ["A", "B", "C", None]


def _fp():
    return RunFingerprint(git_sha="abc", schema_version="v1.1+x", model_id="m1",
                          prompt_version="p1", template_profile="t1", source_profile="s1",
                          golden_release_hash="a" * 64)


def _rec(product, field_id, value, tri="present", *, ev=True, disputed=False):
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if (value and ev) else [],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT, disputed=disputed,
    )


def full(golden, pred):
    r = evaluate(golden, pred)
    prof = build_profile(golden, pred, _fp(), artifact_sha256=_ART)
    d = {
        "micro": (r.micro.tp, r.micro.fp, r.micro.fn),
        "pf": {k: (s.tp, s.fp, s.fn) for k, s in sorted(r.per_field.items())},
        "conf": {f"{g}>{p}": c for (g, p), c in sorted(r.confusion.items())},
        "hall": round(r.hallucination_rate, 12),
        "macro": round(r.macro_f1, 12),
        "pred_only": r.pred_only_keys, "golden_only": r.golden_only_keys,
        "evmis": r.evidence_mismatch_count,
        "errs": sorted((e.product_id, e.field_id, e.kind, e.category) for e in r.errors),
        "g_micro_f1": round(prof.global_metrics.micro_f1, 12),
        "g_macro_f1": round(prof.global_metrics.macro_f1, 12),
        "g_hall": round(prof.global_metrics.hallucination_rate, 12),
        "prof_fields": {},
    }
    for fid, m in sorted(prof.fields.items()):
        v = prof.field_verdict(fid)
        d["prof_fields"][fid] = (m.support, round(m.value_accuracy, 12),
                                 round(m.hallucination_rate, 12),
                                 round(m.precision, 12), round(m.recall, 12), round(m.f1, 12),
                                 tuple(sorted(m.tri_state_confusion.items())),
                                 v.eligible, tuple(v.failures))
    return d


def rand_rec(prod, fid, disputed=False):
    tri = random.choice(TRIS)
    val = random.choice(VALS) if tri != "unknown" else None
    if tri == "present" and val is None:
        val = "A"
    return _rec(prod, fid, val, tri, ev=random.random() < 0.7, disputed=disputed)


def run(iters=2000):
    random.seed(12345)
    violations = []
    for it in range(iters):
        prods = [f"P{i}" for i in range(random.randint(1, 4))]
        fields = [f"f{i}" for i in range(random.randint(1, 3))]
        golden, pred = [], []
        used_keys = set()
        for prod in prods:
            for fid in fields:
                if random.random() < 0.6:
                    golden.append(rand_rec(prod, fid, disputed=False))
                    used_keys.add((prod, fid))
                if random.random() < 0.6:
                    pred.append(rand_rec(prod, fid))
        # pred-only fabrications (unknown or extra products)
        for _ in range(random.randint(0, 2)):
            pred.append(rand_rec(f"X{random.randint(0,9)}", random.choice(fields + ["fNEW"])))
        if not golden:
            golden.append(rand_rec("P0", "f0"))
            used_keys.add(("P0", "f0"))

        before = full(golden, pred)

        # Mode A: disputed-only append (fresh keys)
        dg, dp = [], []
        for _ in range(random.randint(1, 4)):
            k = (f"D{random.randint(0,50)}", random.choice(fields + ["fDONLY"]))
            if k in used_keys:
                continue
            used_keys.add(k)
            dg.append(rand_rec(k[0], k[1], disputed=True))
            if random.random() < 0.8:
                dp.append(rand_rec(k[0], k[1]))  # pred for the disputed key
        gA, pA = golden + dg, pred + dp
        afterA = full(gA, pA)
        if before != afterA:
            violations.append(("A", it, golden, pred, dg, dp,
                               _diff(before, afterA)))

        # Mode B: same-key disputed append (key already usable) -- no extra pred
        usable_keys = [(g.product_id, g.field_id) for g in golden if not g.disputed]
        if usable_keys:
            k = random.choice(usable_keys)
            dgB = [rand_rec(k[0], k[1], disputed=True)]
            afterB = full(golden + dgB, pred)  # usable must win, no change
            if before != afterB:
                violations.append(("B", it, golden, pred, dgB, [],
                                   _diff(before, afterB)))
    print(f"ran {iters} iters (Mode A + Mode B each).")
    if not violations:
        print("RANDOM INVARIANT HELD across all iterations.")
    else:
        print(f"!!! {len(violations)} VIOLATIONS. First 3:")
        for mode, it, g, p, dg, dp, diff in violations[:3]:
            print(f"\n mode={mode} iter={it}")
            print(f"  golden={[(r.product_id,r.field_id,r.tri_state,r.value,r.disputed) for r in g]}")
            print(f"  pred={[(r.product_id,r.field_id,r.tri_state,r.value) for r in p]}")
            print(f"  disp_golden={[(r.product_id,r.field_id,r.tri_state,r.value) for r in dg]}")
            print(f"  disp_pred={[(r.product_id,r.field_id,r.tri_state,r.value) for r in dp]}")
            for x in diff:
                print(f"     {x}")
    return violations


def _diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += _diff(a.get(k, "<MISS>"), b.get(k, "<MISS>"), f"{path}.{k}")
    elif a != b:
        out.append(f"{path}: BEFORE={a!r} AFTER={b!r}")
    return out


if __name__ == "__main__":
    run()
