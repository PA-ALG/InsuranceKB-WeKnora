"""Attack direction 5: end-to-end build_profile -> approve_baseline -> gate.decide.

Q: does adding a disputed golden sample + its prediction abnormally change gate
eligibility for a field? We build a GATE-ELIGIBLE field (support>=10, va>=0.98,
hall<=0.01, evidence=1.0), run the full chain, then append disputed samples and
re-run the full chain; eligibility & reasons must be identical.
"""
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import insurance_harness.goldenset.pdf as pdfmod
from insurance_harness.goldenset.profile import build_profile
from insurance_harness.goldenset.baseline import (
    RunFingerprint, BaselineArtifact, build_product_artifacts, approve_baseline,
)
from insurance_harness.goldenset.records import GoldenRecord, Evidence
from insurance_harness.knowledge.quality_gate import QualityGate

_AT = datetime(2026, 7, 14, tzinfo=UTC)


class _Pg:
    def __init__(self, n, t):
        self.page_no, self.text = n, t


def _fp(**ov):
    base = dict(git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
                template_profile="t1", source_profile="s1", golden_release_hash="a" * 64)
    base.update(ov)
    return RunFingerprint(**base)


def _rec(product, field_id, value, tri="present", *, quote=None, disputed=False):
    ev = [Evidence(page=1, quote=quote if quote is not None else value)] if value else []
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=ev, annotator_model="m", schema_version="v1.1+x",
        created_at=_AT, disputed=disputed,
    )


def make_artifact(fp):
    shas = {k: (f"{i:064x}") for i, k in enumerate(
        ["run_manifest", "pred", "dead_letter", "judge_queue", "judgements",
         "keypoints", "eval_report"], start=1)}
    prod = build_product_artifacts("P0", shas=shas, pred_count=12)
    return BaselineArtifact(baseline_id="bl-1", fingerprint=fp, products=(prod,))


def gate_decision(golden, pred, root, fp):
    art = make_artifact(fp)
    profile = build_profile(golden, pred, fp, artifact_sha256=art.sha256(), dataset_root=root)
    approval = approve_baseline(art, profile, approved_by="qa")
    approved_profile = profile.with_approval(approval)
    gate = QualityGate(approved_profile, approval=approval)
    dec = gate.decide("f1", "low", "add", fp)
    m = approved_profile.field("f1")
    return dec, (m.support, m.value_accuracy, m.hallucination_rate, m.evidence_accuracy)


def run():
    pdfmod.extract_pages = lambda _p: [_Pg(1, "GOODQUOTE 命中内容")]
    root = Path(tempfile.mkdtemp())
    for prod in [f"P{i}" for i in range(12)] + ["D0", "D1"]:
        d = root / f"产品{prod}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "d.pdf").write_text("x", encoding="utf-8")
    fp = _fp()

    # gate-eligible field: 12 keys, all correct, verifiable evidence
    golden = [_rec(f"P{i}", "f1", "GOODQUOTE", quote="GOODQUOTE") for i in range(12)]
    pred = [_rec(f"P{i}", "f1", "GOODQUOTE", quote="GOODQUOTE") for i in range(12)]

    dec0, m0 = gate_decision(golden, pred, root, fp)
    print("BASE (no disputed):")
    print(f"  gate eligible={dec0.eligible} reason={dec0.reason!r}")
    print(f"  field metrics (support, va, hall, ev)={m0}")

    # append disputed-only sample + a present prediction with a BAD (unverifiable) quote
    golden2 = golden + [_rec("D0", "f1", "GOODQUOTE", quote="GOODQUOTE", disputed=True)]
    pred2 = pred + [_rec("D0", "f1", "编造", quote="BADQUOTE_NOT_ON_PAGE")]
    dec1, m1 = gate_decision(golden2, pred2, root, fp)
    print("\nAFTER (disputed-only + present pred w/ bad evidence):")
    print(f"  gate eligible={dec1.eligible} reason={dec1.reason!r}")
    print(f"  field metrics (support, va, hall, ev)={m1}")

    # append a SECOND disputed with value mismatch pred
    golden3 = golden2 + [_rec("D1", "f1", "另一争议", quote="GOODQUOTE", disputed=True)]
    pred3 = pred2 + [_rec("D1", "f1", "错误预测", quote="GOODQUOTE")]
    dec2, m2 = gate_decision(golden3, pred3, root, fp)
    print("\nAFTER2 (two disputed samples):")
    print(f"  gate eligible={dec2.eligible} reason={dec2.reason!r}")
    print(f"  field metrics (support, va, hall, ev)={m2}")

    ok = (dec0.eligible == dec1.eligible == dec2.eligible
          and dec0.reason == dec1.reason == dec2.reason
          and m0 == m1 == m2)
    print("\n" + ("GATE E2E INVARIANT HELD: disputed samples do not affect eligibility"
                  if ok else "!!! GATE E2E CHANGED by disputed samples"))
    return ok


if __name__ == "__main__":
    run()
