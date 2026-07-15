"""复现 codex 六轮 2×P1（对当前 head 8fdd696，修复前证据）。"""
from datetime import UTC, datetime

from insurance_harness.goldenset import (
    BaselineArtifact, BaselineProductArtifacts, Evidence, GlobalMetrics,
    GoldenRecord, QualityProfile, RunFingerprint, approve_baseline, build_profile,
)
from insurance_harness.goldenset.profile import FieldMetrics

AT = datetime(2026, 7, 14, tzinfo=UTC)
A64 = "a" * 64


def rec(product, field_id, value, tri="present", disputed=False):
    return GoldenRecord(
        product_id=product, product_name=f"P{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if value else [],
        annotator_model="m", schema_version="v1.1+x", created_at=AT, disputed=disputed,
    )


def fp(gh=A64):
    return RunFingerprint(
        git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
        template_profile="t1", source_profile="s1", golden_release_hash=gh,
    )


print("=== [P1 #1] disputed 金标的预测被误计为字段幻觉 ===")
golden = [rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
pred = [rec(f"P{i}", "f1", f"v{i}") for i in range(10)]
prof0 = build_profile(golden, pred, fp(), artifact_sha256=A64)
h0 = prof0.fields["f1"].hallucination_rate
print(f"10 正常 f1：field.hallucination={h0}  eligible(≤0.01)={h0 <= 0.01}")

# +1 条 disputed 金标（同 field f1，新 product P10）+ 模型也预测该 key
golden_d = golden + [rec("P10", "f1", "争议值", disputed=True)]
pred_d = pred + [rec("P10", "f1", "模型对争议键的预测")]
prof1 = build_profile(golden_d, pred_d, fp(), artifact_sha256=A64)
h1 = prof1.fields["f1"].hallucination_rate
print(f"+1 disputed 金标(模型也预测该键)：field.hallucination={h1}  eligible(≤0.01)={h1 <= 0.01}")
print(f"  >>> disputed 键的预测被误判为幻觉：{h1:.4f}（{'资格被误杀' if h1 > 0.01 else '未受影响'}）")

print("\n=== [P1 #2] reset 用未规范化 golden hash 比较：同 digest 大小写变体绕过 ===")


def raw_product(**ov):
    base = dict(
        product_id="P1", run_manifest_sha256=A64, pred_sha256=A64, pred_count=12,
        dead_letter_sha256=A64, dead_letter_count=0, judge_queue_sha256=A64,
        judge_queue_count=0, judgements_sha256=A64, resolved_judgement_count=0,
        keypoints_status="complete", keypoints_sha256=A64, keypoints_pending_count=0,
        eval_report_sha256=A64, unresolved_judge_count=0, unresolved_dead_letter_count=0,
    )
    base.update(ov)
    return BaselineProductArtifacts(**base)


def artifact(baseline_id, gh):
    return BaselineArtifact(baseline_id=baseline_id, fingerprint=fp(gh), products=(raw_product(),))


def cand(art, va):
    return QualityProfile(
        profile_version="1", artifact_sha256=art.sha256(), baseline_approval_sha256="",
        fingerprint=art.fingerprint,
        fields={"f1": FieldMetrics(field_id="f1", support=12, value_accuracy=va,
                hallucination_rate=0.0, evidence_accuracy=1.0, precision=1.0, recall=1.0,
                f1=1.0, tri_state_confusion={})},
        global_metrics=GlobalMetrics(micro_f1=va, macro_f1=va, hallucination_rate=0.0,
                evidence_accuracy=1.0),
    )


prod_art = artifact("prod-A", "a" * 64)          # 生产基线：golden 小写
prod = approve_baseline(prod_art, cand(prod_art, 1.0), approved_by="claude", approved_at=AT)
evil_art = artifact("gs-v2-rebrand", "A" * 64)   # 攻击：同一 digest 仅大写 + 新 id
print(f"  同一 digest？ 'a'*64.lower()=='A'*64.lower() -> {('a'*64).lower() == ('A'*64).lower()}")
try:
    r = approve_baseline(evil_art, cand(evil_art, 0.98), approved_by="attacker", prior=[prod],
                         allow_lineage_reset=True, lineage_reset_reason="rebrand", approved_at=AT)
    print(f"  reset -> APPROVED (BYPASS)  lineage_reset={r.lineage_reset}  "
          f">>> 大小写变体绕过'同评测基准必回归'")
except Exception as e:
    print(f"  reset -> REJECTED: {str(e)[:70]}")
