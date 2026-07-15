"""Red-team shared builders, mirroring tests/test_goldenset_baseline_019.py + test_quality_gate_019.py."""
from datetime import UTC, datetime

from insurance_harness.goldenset.baseline import (
    ApprovalRecord,
    BaselineArtifact,
    BaselineProductArtifacts,
    RunFingerprint,
    approve_baseline,
)
from insurance_harness.goldenset.profile import (
    FieldMetrics,
    GlobalMetrics,
    QualityProfile,
)
from insurance_harness.knowledge.quality_gate import QualityGate

AT = datetime(2026, 7, 14, tzinfo=UTC)
A = "a" * 64
B = "b" * 64
C = "c" * 64


def fp(**ov):
    base = dict(
        git_sha="abc123", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
        template_profile="tpl1", source_profile="src1", golden_release_hash=A,
    )
    base.update(ov)
    return RunFingerprint(**base)


def raw_product(**ov):
    base = dict(
        product_id="P1", run_manifest_sha256=A, pred_sha256=A, pred_count=12,
        dead_letter_sha256=A, dead_letter_count=0, judge_queue_sha256=A,
        judge_queue_count=0, judgements_sha256=A, resolved_judgement_count=0,
        keypoints_status="complete", keypoints_sha256=A, keypoints_pending_count=0,
        eval_report_sha256=A, unresolved_judge_count=0, unresolved_dead_letter_count=0,
    )
    base.update(ov)
    return BaselineProductArtifacts(**base)


def artifact(*, baseline_id="b1", fingerprint=None, products=None):
    return BaselineArtifact(
        baseline_id=baseline_id,
        fingerprint=fingerprint if fingerprint is not None else fp(),
        products=products if products is not None else (raw_product(),),
    )


def field(**ov):
    base = dict(
        field_id="f1", support=12, value_accuracy=1.0, hallucination_rate=0.0,
        evidence_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0, tri_state_confusion={},
    )
    base.update(ov)
    return FieldMetrics(**base)


def candidate(art, *, value_accuracy=1.0, artifact_sha256=None, fingerprint=None):
    return QualityProfile(
        profile_version="1",
        artifact_sha256=artifact_sha256 if artifact_sha256 is not None else art.sha256(),
        baseline_approval_sha256="",
        fingerprint=fingerprint if fingerprint is not None else art.fingerprint,
        fields={"f1": field(value_accuracy=value_accuracy)},
        global_metrics=GlobalMetrics(
            micro_f1=value_accuracy, macro_f1=value_accuracy,
            hallucination_rate=0.0, evidence_accuracy=1.0,
        ),
    )
