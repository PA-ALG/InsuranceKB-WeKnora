"""End-to-end (attack 5) + evidence-None fail-closed (attack 4).

Full chain: build_profile -> approve_baseline(first) -> with_approval -> QualityGate.decide.
Uses a monkeypatched extract_pages so f1 evidence verifies to 1.0 (field genuinely eligible).
"""
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import insurance_harness.goldenset.pdf as pdfmod
from insurance_harness.goldenset import (
    Evidence, GoldenRecord, RunFingerprint, build_profile,
)
from insurance_harness.goldenset.baseline import (
    BaselineArtifact, approve_baseline, build_product_artifacts,
)
from insurance_harness.goldenset.profile import AutomationThresholds
from insurance_harness.knowledge.quality_gate import QualityGate

_AT = datetime(2026, 7, 14, tzinfo=UTC)


def _fp(**ov):
    base = dict(git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
                template_profile="t1", source_profile="s1", golden_release_hash="rh1")
    base.update(ov)
    return RunFingerprint(**base)


def _rec(product, field_id, value, tri="present", *, with_evidence=True):
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if (value and with_evidence) else [],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT,
    )


def hr(label):
    print("\n" + "=" * 70 + f"\n{label}\n" + "=" * 70)


class _Pg:
    def __init__(self, n, t):
        self.page_no = n
        self.text = t


def build_full_chain(golden, pred, dataset_root, thresholds=None):
    """Return (gate, run_fp) after full approval chain for a FIRST baseline (prior=())."""
    fp = _fp()
    shas = {k: ("a" * 64) for k in
            ("run_manifest", "pred", "dead_letter", "judge_queue", "judgements",
             "eval_report", "keypoints")}
    products = tuple(
        build_product_artifacts(pid, shas=shas, pred_count=5)
        for pid in sorted({g.product_id for g in golden})
    )
    artifact = BaselineArtifact(baseline_id="B1", fingerprint=fp, products=products)
    art_sha = artifact.sha256()
    profile = build_profile(golden, pred, fp, artifact_sha256=art_sha, dataset_root=dataset_root)
    approval = approve_baseline(artifact, profile, approved_by="tester", prior=())  # FIRST: no regression
    approved = profile.with_approval(approval)
    gate = QualityGate(approved, approval=approval, thresholds=thresholds)
    return gate, fp, profile


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # golden values 值0..值11; make one page whose text contains every quote
    all_quotes = "".join(f"值{i}" for i in range(12)) + "伪造"
    pdfmod.extract_pages = lambda _p: [_Pg(1, all_quotes)]  # patch module attr (both call sites use it)

    # create PDFs for P0..P11 (fabrication products Z* deliberately have NO pdf)
    for i in range(12):
        d = root / f"产品P{i}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "d.pdf").write_text("x", encoding="utf-8")

    hr("ATTACK 5a: CLEAN f1 (12 correct, evidence 1.0) + 200 UNKNOWN-field fabrications")
    golden = [_rec(f"P{i}", "f1", f"值{i}") for i in range(12)]
    pred = ([_rec(f"P{i}", "f1", f"值{i}") for i in range(12)]
            + [_rec(f"Z{i}", f"f_fake{i}", "伪造") for i in range(200)])
    gate, run_fp, prof = build_full_chain(golden, pred, root)
    m = prof.field("f1")
    print("f1: support=%s value_acc=%s halluc=%s evidence=%s f1=%s" % (
        m.support, m.value_accuracy, m.hallucination_rate, m.evidence_accuracy, m.f1))
    print("GLOBAL hallucination_rate  :", round(prof.global_metrics.hallucination_rate, 4),
          " micro_f1:", round(prof.global_metrics.micro_f1, 4))
    dec = gate.decide("f1", "low", "add", run_fp)
    print("gate.decide('f1','low','add') ->", dec.eligible, "|", dec.reason)
    dec_fake = gate.decide("f_fake0", "low", "add", run_fp)
    print("gate.decide('f_fake0',...)    ->", dec_fake.eligible, "|", dec_fake.reason)
    print(">> f1 clean field publishable despite dirty global; fabricated fields DENIED (no profile).")
    print(">> Gate consults NO global metric — confirm by inspecting decide() path.")

    hr("ATTACK 5b: DIRTY f1 (12 correct + 12 SAME-field fabrications) — must be DENIED")
    golden = [_rec(f"P{i}", "f1", f"值{i}") for i in range(12)]
    pred = ([_rec(f"P{i}", "f1", f"值{i}") for i in range(12)]
            + [_rec(f"Z{i}", "f1", "伪造") for i in range(12)])  # SAME field f1
    gate, run_fp, prof = build_full_chain(golden, pred, root)
    m = prof.field("f1")
    print("f1: support=%s value_acc=%s halluc=%s evidence=%s f1=%s" % (
        m.support, m.value_accuracy, m.hallucination_rate, m.evidence_accuracy, round(m.f1, 4)))
    dec = gate.decide("f1", "low", "add", run_fp)
    print("gate.decide('f1','low','add') ->", dec.eligible, "|", dec.reason)
    assert not dec.eligible, "BYPASS! dirty same-field candidate got eligible"
    assert "hallucination_rate" in dec.reason, "hallucination not the cited reason"
    print(">> Correctly DENIED on hallucination_rate. Invariant holds end-to-end.")

# ===================================================================
# ATTACK 4: evidence=None + high hallucination -> fail-closed, both failures
# ===================================================================
hr("ATTACK 4: evidence=None must NOT mask other failures (fail-closed)")
# No dataset_root => evidence None; same-field fabrication => halluc 0.5
golden = [_rec(f"P{i}", "f1", f"v{i}") for i in range(12)]
pred = ([_rec(f"P{i}", "f1", f"v{i}") for i in range(12)]
        + [_rec(f"Z{i}", "f1", "fab") for i in range(12)])
prof = build_profile(golden, pred, _fp(), artifact_sha256="a" * 64, dataset_root=None)
m = prof.field("f1")
verdict = prof.field_verdict("f1")
print("f1: evidence=%s halluc=%s" % (m.evidence_accuracy, m.hallucination_rate))
print("verdict.eligible:", verdict.eligible)
print("failures:", verdict.failures)
has_halluc = any("hallucination_rate" in f for f in verdict.failures)
has_evid = any("evidence" in f for f in verdict.failures)
print("cites hallucination:", has_halluc, "| cites evidence:", has_evid)
assert not verdict.eligible and has_halluc and has_evid, "evidence=None masked hallucination!"
print(">> Both failures listed independently; evidence=None does not skip hallucination check.")

print("\nE2E DONE")
