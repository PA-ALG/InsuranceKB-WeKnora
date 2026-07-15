"""Shared fixtures copied from tests/test_goldenset_baseline_019.py (合法输入构造)."""
from datetime import UTC, datetime

from insurance_harness.goldenset import (
    BaselineArtifact,
    BaselineProductArtifacts,
    GlobalMetrics,
    QualityProfile,
    RunFingerprint,
)
from insurance_harness.goldenset.profile import FieldMetrics

AT = datetime(2026, 7, 14, tzinfo=UTC)
A = "a" * 64
B = "b" * 64


def fp(**overrides: str) -> RunFingerprint:
    base = dict(
        git_sha="abc123", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
        template_profile="tpl1", source_profile="src1", golden_release_hash="rh1",
    )
    base.update(overrides)
    return RunFingerprint(**base)


def raw_product(**ov: object) -> BaselineProductArtifacts:
    base: dict[str, object] = dict(
        product_id="P1", run_manifest_sha256=A, pred_sha256=A, pred_count=12,
        dead_letter_sha256=A, dead_letter_count=0, judge_queue_sha256=A,
        judge_queue_count=0, judgements_sha256=A, resolved_judgement_count=0,
        keypoints_status="complete", keypoints_sha256=A, keypoints_pending_count=0,
        eval_report_sha256=A, unresolved_judge_count=0, unresolved_dead_letter_count=0,
    )
    base.update(ov)
    return BaselineProductArtifacts(**base)  # type: ignore[arg-type]


def artifact(*, baseline_id: str = "b1", fingerprint=None, products=None) -> BaselineArtifact:
    return BaselineArtifact(
        baseline_id=baseline_id, fingerprint=fingerprint or fp(),
        products=products if products is not None else (raw_product(),),
    )


def field(**ov: object) -> FieldMetrics:
    base: dict[str, object] = dict(
        field_id="f1", support=12, value_accuracy=1.0, hallucination_rate=0.0,
        evidence_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0, tri_state_confusion={},
    )
    base.update(ov)
    return FieldMetrics(**base)  # type: ignore[arg-type]


def candidate(art, *, value_accuracy=1.0, hallucination_rate=0.0,
              evidence_accuracy=1.0) -> QualityProfile:
    return QualityProfile(
        profile_version="1", artifact_sha256=art.sha256(), baseline_approval_sha256="",
        fingerprint=art.fingerprint,
        fields={"f1": field(value_accuracy=value_accuracy,
                            hallucination_rate=hallucination_rate,
                            evidence_accuracy=evidence_accuracy)},
        global_metrics=GlobalMetrics(
            micro_f1=value_accuracy, macro_f1=value_accuracy,
            hallucination_rate=hallucination_rate, evidence_accuracy=evidence_accuracy,
        ),
    )
