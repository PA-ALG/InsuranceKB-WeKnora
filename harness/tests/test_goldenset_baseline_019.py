"""019 Q2 + 实施计划 Task3 + codex 三轮复审：内容寻址 artifact / 强绑定批准 / 全指标回归。

对抗性负例为主：artifact 产物齐全性与一致性、artifact 内容身份、批准绑定 artifact、
回归基线不可伪造/不可省略——都必须"非法状态无法构造"。
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from insurance_harness.goldenset import (
    ApprovalRecord,
    BaselineArtifact,
    BaselineNotApprovableError,
    BaselineProductArtifacts,
    Evidence,
    GlobalMetrics,
    GoldenRecord,
    QualityProfile,
    RunFingerprint,
    approve_baseline,
    release_hash,
)
from insurance_harness.goldenset.profile import FieldMetrics

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_A = "a" * 64
_B = "b" * 64


def _fp(**overrides: str) -> RunFingerprint:
    base = dict(
        git_sha="abc123", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
        template_profile="tpl1", source_profile="src1", golden_release_hash="rh1",
    )
    base.update(overrides)
    return RunFingerprint(**base)


def _raw_product(**ov: object) -> BaselineProductArtifacts:
    """默认一份内部一致、可批准的产品现场；用 overrides 注入违规做负例。"""
    base: dict[str, object] = dict(
        product_id="P1", run_manifest_sha256=_A, pred_sha256=_A, pred_count=12,
        dead_letter_sha256=_A, dead_letter_count=0, judge_queue_sha256=_A,
        judge_queue_count=0, judgements_sha256=_A, resolved_judgement_count=0,
        keypoints_status="complete", keypoints_sha256=_A, keypoints_pending_count=0,
        eval_report_sha256=_A, unresolved_judge_count=0, unresolved_dead_letter_count=0,
    )
    base.update(ov)
    return BaselineProductArtifacts(**base)  # type: ignore[arg-type]


def _artifact(
    *, fingerprint: RunFingerprint | None = None,
    products: tuple[BaselineProductArtifacts, ...] | None = None,
) -> BaselineArtifact:
    return BaselineArtifact(
        baseline_id="b1", fingerprint=fingerprint or _fp(),
        products=products if products is not None else (_raw_product(),),
    )


def _field(**ov: object) -> FieldMetrics:
    base: dict[str, object] = dict(
        field_id="f1", support=12, value_accuracy=1.0, hallucination_rate=0.0,
        evidence_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0, tri_state_confusion={},
    )
    base.update(ov)
    return FieldMetrics(**base)  # type: ignore[arg-type]


def _candidate(
    artifact: BaselineArtifact, *, value_accuracy: float = 1.0,
) -> QualityProfile:
    """派生自该 artifact 的候选画像（artifact_sha256 绑定，baseline_approval_sha256=""）。"""
    return QualityProfile(
        profile_version="1", artifact_sha256=artifact.sha256(), baseline_approval_sha256="",
        fingerprint=artifact.fingerprint, fields={"f1": _field(value_accuracy=value_accuracy)},
        global_metrics=GlobalMetrics(
            micro_f1=value_accuracy, macro_f1=value_accuracy,
            hallucination_rate=0.0, evidence_accuracy=1.0,
        ),
    )


# --------------------------------------- Q2.1 未解决计数（实施计划 unresolved 现场）

def test_q2_1_unresolved_is_dead_letter_plus_pending_judge() -> None:
    p = _raw_product(
        dead_letter_count=2, unresolved_dead_letter_count=2,
        judge_queue_count=5, resolved_judgement_count=3, unresolved_judge_count=2,
    )
    assert p.unresolved == 4
    assert _artifact(products=(p,)).unresolved_total() == 4


def test_q2_1_unresolved_total_sums_products() -> None:
    a = _artifact(products=(
        _raw_product(product_id="P1", dead_letter_count=2, unresolved_dead_letter_count=2),
        _raw_product(product_id="P2", judge_queue_count=3, unresolved_judge_count=3),
    ))
    assert a.unresolved_total() == 5


# ------------------------------- Q2.1 产物齐全 + 一致性（实施计划 L199 拒绝清单）

@pytest.mark.parametrize("sha_field", [
    "run_manifest_sha256", "pred_sha256", "dead_letter_sha256",
    "judge_queue_sha256", "judgements_sha256", "eval_report_sha256",
])
def test_q2_1_missing_each_required_sha_blocks_approval(sha_field: str) -> None:
    a = _artifact(products=(_raw_product(**{sha_field: ""}),))
    assert any(sha_field in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match=sha_field):
        approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)


def test_q2_1_zero_pred_blocks_approval() -> None:
    a = _artifact(products=(_raw_product(pred_count=0),))
    with pytest.raises(BaselineNotApprovableError, match="无预测产物"):
        approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)


def test_q2_1_inconsistent_unresolved_judge_count_blocks() -> None:
    # judge_queue=3, resolved=3 → 应 0 未解决；却声明 unresolved_judge_count=0 一致，
    # 反例：声明 2 不一致。
    a = _artifact(products=(_raw_product(
        judge_queue_count=3, resolved_judgement_count=3, unresolved_judge_count=2),))
    assert any("unresolved_judge_count" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError):
        approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)


def test_q2_1_resolved_exceeds_queue_blocks() -> None:
    a = _artifact(products=(_raw_product(
        judge_queue_count=2, resolved_judgement_count=5, unresolved_judge_count=0),))
    assert any("超出" in b for b in a.approval_blockers())


def test_q2_1_dead_letter_count_mismatch_blocks() -> None:
    a = _artifact(products=(_raw_product(
        dead_letter_count=3, unresolved_dead_letter_count=1),))  # 应相等
    assert any("unresolved_dead_letter_count" in b for b in a.approval_blockers())


def test_q2_1_pending_keypoints_without_positive_count_blocks() -> None:
    a = _artifact(products=(_raw_product(
        keypoints_status="pending", keypoints_sha256=None, keypoints_pending_count=0),))
    assert any("pending 但 pending_count" in b for b in a.approval_blockers())


def test_q2_1_pending_keypoints_blocks_even_if_internally_consistent() -> None:
    # pending 且 pending_count>0 → 内部一致，但仍不可批准（关键点未完成）。
    p = _raw_product(keypoints_status="pending", keypoints_sha256=None, keypoints_pending_count=2)
    assert p.consistency_errors() == []
    a = _artifact(products=(p,))
    assert any("关键点未完成" in b for b in a.approval_blockers())


def test_q2_1_unresolved_items_block_approval() -> None:
    a = _artifact(products=(_raw_product(
        dead_letter_count=1, unresolved_dead_letter_count=1),))
    with pytest.raises(BaselineNotApprovableError, match="未解决"):
        approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)


@pytest.mark.parametrize("count_field", [
    "pred_count", "dead_letter_count", "judge_queue_count", "resolved_judgement_count",
    "keypoints_pending_count", "unresolved_judge_count", "unresolved_dead_letter_count",
])
def test_q2_1_negative_counts_rejected_at_construction(count_field: str) -> None:
    """codex 五轮 #2：计数不得为负——构造期即拒（NonNegativeInt）。"""
    with pytest.raises(ValidationError):
        _raw_product(**{count_field: -1})


def test_q2_2_negative_count_cannot_mask_unresolved() -> None:
    """codex 五轮 #2：负 dead-letter 不能与真实待裁决正负相消掩盖未解决（Q2.2 fail-closed）。

    旧实现 `unresolved`=judge+dead-letter 合计的 truthiness 会被 -1 抵消 +1；现负数不可构造，
    且 approval_blockers 逐项检查——双保险。
    """
    with pytest.raises(ValidationError):
        _raw_product(dead_letter_count=-1, unresolved_dead_letter_count=-1,
                     judge_queue_count=1, unresolved_judge_count=1)


def test_q2_2_unresolved_judge_alone_blocks_approval() -> None:
    """逐项检查：只有待裁决未解决（dead-letter=0）也必须阻断批准。"""
    a = _artifact(products=(_raw_product(
        judge_queue_count=1, resolved_judgement_count=0, unresolved_judge_count=1),))
    assert any("待裁决未解决" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="待裁决未解决"):
        approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)


# ------------------------------------------------- Q2.2 指纹 / 空产品

def test_q2_2_missing_fingerprint_field_blocks_approval() -> None:
    fp = _fp(git_sha=" ")
    a = _artifact(fingerprint=fp)
    with pytest.raises(BaselineNotApprovableError, match="git_sha"):
        approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)


def test_q2_2_empty_products_block_approval() -> None:
    a = BaselineArtifact(baseline_id="b1", fingerprint=_fp(), products=())
    assert any("无任何产品" in b for b in a.approval_blockers())


# ------------------- codex #2：批准绑定 artifact 内容身份（不只是运行配置）

def test_q2_artifact_sha256_reflects_output_content() -> None:
    """同配置（指纹相同）但产物输出不同（pred_sha256 不同）→ 不同 artifact 身份。"""
    a1 = _artifact(products=(_raw_product(pred_sha256=_A),))
    a2 = _artifact(products=(_raw_product(pred_sha256=_B),))
    assert a1.fingerprint == a2.fingerprint
    assert a1.sha256() != a2.sha256()


def test_q2_3_approval_binds_artifact_sha256() -> None:
    a = _artifact()
    rec = approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)
    assert rec.artifact_sha256 == a.sha256()


def test_q2_3_different_artifact_yields_different_approval() -> None:
    """复审 #2：只改 pred_sha256、保持指纹/画像结构，两份 artifact 的批准记录不相等。"""
    a1 = _artifact(products=(_raw_product(pred_sha256=_A),))
    a2 = _artifact(products=(_raw_product(pred_sha256=_B),))
    r1 = approve_baseline(a1, _candidate(a1), approved_by="claude", approved_at=_AT)
    r2 = approve_baseline(a2, _candidate(a2), approved_by="claude", approved_at=_AT)
    assert r1.artifact_sha256 != r2.artifact_sha256 and r1.sha256() != r2.sha256()


def test_q4_3_profile_must_derive_from_artifact() -> None:
    a = _artifact(products=(_raw_product(pred_sha256=_A),))
    other = _artifact(products=(_raw_product(pred_sha256=_B),))
    wrong_profile = _candidate(other)  # 画像 artifact_sha256 指向 other
    with pytest.raises(BaselineNotApprovableError, match="artifact_sha256 不符"):
        approve_baseline(a, wrong_profile, approved_by="claude", approved_at=_AT)


# ------------------------------------------------- Q2.3 版本化 / 不可变

def test_q2_3_approval_is_versioned_and_immutable() -> None:
    a = _artifact()
    p1 = _candidate(a)
    first = approve_baseline(a, p1, approved_by="claude", approved_at=_AT)
    assert first.version == 1
    approved_p1 = p1.with_approval(first)
    second = approve_baseline(
        a, _candidate(a), approved_by="claude", prior=[first],
        prior_profile=approved_p1, approved_at=_AT,
    )
    assert second.version == 2
    with pytest.raises(Exception):  # noqa: B017,PT011  frozen
        first.version = 9


# --------------------------- codex #1 复审：回归不可省略、不可伪造

def test_q4_6_prior_approval_requires_prior_profile() -> None:
    a = _artifact()
    first = approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)
    with pytest.raises(BaselineNotApprovableError, match="必须提供 prior_profile"):
        approve_baseline(a, _candidate(a), approved_by="claude", prior=[first], approved_at=_AT)


def test_q4_6_forged_prior_profile_rejected() -> None:
    """复审 #1：prior_profile 必须是最近批准所绑定的画像，不能塞一份低标准伪基线（裸对象）。"""
    a = _artifact()
    first = approve_baseline(a, _candidate(a, value_accuracy=1.0), approved_by="claude",
                             approved_at=_AT)
    forged_baseline = _candidate(a, value_accuracy=0.1)  # 未被批准的"假基线"
    candidate = _candidate(a, value_accuracy=0.99)
    with pytest.raises(BaselineNotApprovableError, match="不是当前生产基线|不是最近批准"):
        approve_baseline(a, candidate, approved_by="claude", prior=[first],
                         prior_profile=forged_baseline, approved_at=_AT)


def test_q4_6_forged_prior_copying_public_approval_hash_rejected() -> None:
    """四轮 #1（更强）：伪 prior 复制公开的 approval.sha256() 也不行——批准提交的是画像**内容**哈希，
    低标准伪基线的 content_hash 与被批准画像不符，无法冒充当前生产基线。"""
    a = _artifact()
    first = approve_baseline(a, _candidate(a, value_accuracy=1.0), approved_by="claude",
                             approved_at=_AT)
    # 攻击者复制公开 approval 哈希，试图让伪 prior 通过"绑定"检查
    forged = _candidate(a, value_accuracy=0.1).model_copy(
        update={"baseline_approval_sha256": first.sha256()})
    candidate = _candidate(a, value_accuracy=0.99)
    with pytest.raises(BaselineNotApprovableError, match="不是当前生产基线"):
        approve_baseline(a, candidate, approved_by="claude", prior=[first],
                         prior_profile=forged, approved_at=_AT)


def test_q4_6_regression_failure_blocks_second_approval() -> None:
    a = _artifact()
    p1 = _candidate(a, value_accuracy=1.0)
    first = approve_baseline(a, p1, approved_by="claude", approved_at=_AT)
    approved_p1 = p1.with_approval(first)
    worse = _candidate(a, value_accuracy=0.5)
    with pytest.raises(BaselineNotApprovableError, match="回归失败"):
        approve_baseline(a, worse, approved_by="claude", prior=[first],
                         prior_profile=approved_p1, approved_at=_AT)


def test_q4_6_rotated_baseline_id_still_regresses_against_production() -> None:
    """四轮 #3：换 baseline_id（b1→b2）不能把退化候选偷渡成"新 lineage v1"跳过回归。

    只要系统已有生产批准，候选就必须与当前生产基线比较；换 id 不是免检通道。
    """
    b1 = _artifact(fingerprint=_fp())
    p1 = _candidate(b1, value_accuracy=1.0)
    prod = approve_baseline(b1, p1, approved_by="claude", approved_at=_AT)
    approved_p1 = p1.with_approval(prod)
    # 攻击者把 id 换成 b2、指标退化到 0.1，试图绕过回归
    b2 = BaselineArtifact(baseline_id="b2", fingerprint=_fp(),
                          products=(_raw_product(pred_sha256=_B),))
    degraded = _candidate(b2, value_accuracy=0.1)
    with pytest.raises(BaselineNotApprovableError, match="回归失败"):
        approve_baseline(b2, degraded, approved_by="claude", prior=[prod],
                         prior_profile=approved_p1, approved_at=_AT)


def test_q4_6_rotated_baseline_id_requires_prior_profile() -> None:
    """四轮 #3：换 id 且省略 prior_profile 同样被拒（有生产基线即须提供回归基线）。"""
    b1 = _artifact(fingerprint=_fp())
    prod = approve_baseline(b1, _candidate(b1, value_accuracy=1.0), approved_by="claude",
                            approved_at=_AT)
    b2 = BaselineArtifact(baseline_id="b2", fingerprint=_fp(),
                          products=(_raw_product(pred_sha256=_B),))
    with pytest.raises(BaselineNotApprovableError, match="必须提供 prior_profile"):
        approve_baseline(b2, _candidate(b2, value_accuracy=1.0), approved_by="claude", prior=[prod],
                         approved_at=_AT)


def test_q4_6_lineage_reset_is_explicit_and_auditable() -> None:
    """真正的新 lineage/bootstrap 必须显式 allow_lineage_reset=True（人工授权、可审计），
    而非靠换 baseline_id 隐式绕过。真新 lineage = **新评测基准**（golden_release_hash 变更）。"""
    b1 = _artifact(fingerprint=_fp())  # golden rh1
    prod = approve_baseline(b1, _candidate(b1, value_accuracy=1.0), approved_by="claude",
                            approved_at=_AT)
    # 真新 lineage：新 baseline_id **且**新 golden 集（rh2）——回归无从比较，reset 才合法
    b2 = BaselineArtifact(baseline_id="b2", fingerprint=_fp(golden_release_hash="rh2"),
                          products=(_raw_product(pred_sha256=_B),))
    reset = approve_baseline(b2, _candidate(b2, value_accuracy=1.0), approved_by="human-lead",
                             prior=[prod], allow_lineage_reset=True,
                             lineage_reset_reason="启用 gs-v2 新 lineage", approved_at=_AT)
    assert reset.baseline_id == "b2"
    assert reset.version == 1
    assert reset.lineage_reset is True  # 跳过回归的重置在批准记录中留痕（可审计）
    assert reset.lineage_reset_reason == "启用 gs-v2 新 lineage"


def test_q4_6_lineage_reset_same_baseline_id_rejected() -> None:
    """codex 五轮 #4：reset 不能给**同一** lineage 降级——同 baseline_id + reset=True 直接拒，
    否则 reset 就成了通用"关闭回归"开关。"""
    a = _artifact()
    first = approve_baseline(a, _candidate(a, value_accuracy=1.0), approved_by="claude",
                             approved_at=_AT)
    with pytest.raises(BaselineNotApprovableError, match="必须开新 lineage"):
        approve_baseline(a, _candidate(a, value_accuracy=0.1), approved_by="bot",
                         prior=[first], allow_lineage_reset=True,
                         lineage_reset_reason="想跳过回归", approved_at=_AT)


def test_q4_6_lineage_reset_requires_reason() -> None:
    """codex 五轮 #4：reset 必须带非空 reason（记入批准记录，可审计）。

    用一个"否则合法"的 reset（新 id + 新 golden 集 rh2）只缺 reason，隔离到 reason 校验。"""
    b1 = _artifact(fingerprint=_fp())
    prod = approve_baseline(b1, _candidate(b1, value_accuracy=1.0), approved_by="claude",
                            approved_at=_AT)
    b2 = BaselineArtifact(baseline_id="b2", fingerprint=_fp(golden_release_hash="rh2"),
                          products=(_raw_product(pred_sha256=_B),))
    with pytest.raises(BaselineNotApprovableError, match="非空 reason"):
        approve_baseline(b2, _candidate(b2, value_accuracy=1.0), approved_by="human",
                         prior=[prod], allow_lineage_reset=True, approved_at=_AT)


def test_q4_6_normal_first_approval_is_not_marked_lineage_reset() -> None:
    """首次批准（无 prior）不是 lineage 重置——lineage_reset 仅标记"有生产基线却显式跳过回归"。"""
    a = _artifact()
    first = approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)
    assert first.lineage_reset is False
    assert first.lineage_reset_reason is None


def test_q4_6_lineage_reset_same_golden_set_rejected() -> None:
    """红队 R6/弱点1：reset 的"真新 lineage"不能只看 baseline_id——同一 golden 集
    （golden_release_hash 相同）换个新 id 仍是同一评测基准，必须走零容差回归，
    不得借 reset 洗白降级。否则 `baseline_id` 只是可随意更换的弱代理。"""
    b1 = _artifact(fingerprint=_fp())  # golden rh1
    prod = approve_baseline(b1, _candidate(b1, value_accuracy=1.0), approved_by="claude",
                            approved_at=_AT)
    # 新 baseline_id，但 golden 集不变（rh1）→ 同一评测基准；画像退化
    b2 = BaselineArtifact(baseline_id="b2", fingerprint=_fp(),
                          products=(_raw_product(pred_sha256=_B),))
    with pytest.raises(BaselineNotApprovableError, match="新评测基准|golden"):
        approve_baseline(b2, _candidate(b2, value_accuracy=0.5), approved_by="human",
                         prior=[prod], allow_lineage_reset=True,
                         lineage_reset_reason="想借 reset 跳过回归", approved_at=_AT)


def test_q4_6_reset_cannot_launder_same_goldenset_downgrade_end_to_end() -> None:
    """红队 R6/弱点1 端到端：同 golden 集的退化候选，常规回归路径与 reset 逃生门**双双**被拒——
    退化画像拿不到任何批准，自然到不了 gate（不再是"关回归"的旁路）。"""
    b1 = _artifact(fingerprint=_fp())
    p1 = _candidate(b1, value_accuracy=1.0)
    prod = approve_baseline(b1, p1, approved_by="claude", approved_at=_AT)
    approved_p1 = p1.with_approval(prod)
    # 同 golden 集（rh1）+ 换品牌 id + 退化 1.0→0.98
    b2 = BaselineArtifact(baseline_id="gs-v2-rebrand", fingerprint=_fp(),
                          products=(_raw_product(pred_sha256=_B),))
    degraded = _candidate(b2, value_accuracy=0.98)
    with pytest.raises(BaselineNotApprovableError, match="回归失败"):  # 常规路径：回归拦下
        approve_baseline(b2, degraded, approved_by="claude", prior=[prod],
                         prior_profile=approved_p1, approved_at=_AT)
    # reset 逃生门同样拦下（同 golden 集）
    with pytest.raises(BaselineNotApprovableError, match="新评测基准|golden"):
        approve_baseline(b2, degraded, approved_by="human", prior=[prod],
                         allow_lineage_reset=True, lineage_reset_reason="rebrand",
                         approved_at=_AT)


def test_q4_6_lineage_reset_without_prior_is_rejected() -> None:
    """红队 R6/弱点3：无 prior 生产批准却传 allow_lineage_reset=True 属调用方误用——应显式
    报错，不静默吞掉 reset 意图与 reason（首批准本就无需 reset，避免审计信息丢失）。"""
    a = _artifact()
    with pytest.raises(BaselineNotApprovableError, match="无 prior|无生产批准|首批准"):
        approve_baseline(a, _candidate(a, value_accuracy=1.0), approved_by="human",
                         prior=[], allow_lineage_reset=True,
                         lineage_reset_reason="紧急初始化", approved_at=_AT)


@pytest.mark.parametrize("bad_id", ["b1 ", " b1", "b1\n", "b1\t", "  ", ""])
def test_q2_1_baseline_id_rejects_surrounding_whitespace(bad_id: str) -> None:
    """红队 R6/弱点2：baseline_id 带首尾空白/纯空白构造期即拒——否则 'prod-A ' 这类肉眼等同
    生产基线的 id 会污染审计，并可能绕过新 lineage 的精确串匹配。"""
    with pytest.raises(ValidationError):
        BaselineArtifact(baseline_id=bad_id, fingerprint=_fp(), products=(_raw_product(),))


# ------------------------------------------------------------- release_hash

def _rec(value: str, product: str = "P1") -> GoldenRecord:
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id="f1", field_name="f1", value=value, tri_state="present",
        evidence=[Evidence(page=1, quote=value)],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT,
    )


def test_q2_release_hash_is_stable_and_order_independent() -> None:
    assert release_hash([_rec("20日")]) == release_hash([_rec("20日")])
    a = [_rec("v1", "P1"), _rec("v2", "P2")]
    assert release_hash(a) == release_hash(list(reversed(a)))


def test_q2_release_hash_ignores_created_at() -> None:
    base = _rec("20日")
    later = base.model_copy(update={"created_at": datetime(2027, 1, 1, tzinfo=UTC)})
    assert release_hash([base]) == release_hash([later])


def _lineage_rec(**ov: object) -> GoldenRecord:
    base: dict[str, object] = dict(
        product_id="P1", product_name="产品P1", doc="terms.pdf", field_id="f1",
        field_name="等待期", value="20日", tri_state="present", disputed=False,
        reasoning="因为条款第X条", annotator_model="m1", schema_version="v1.1+x",
        created_at=_AT,
        evidence=[Evidence(
            page=1, quote="第20日", knowledge_id="k1", raw_kb_id="raw1",
            source_revision="a" * 64, file_hash="b" * 64, original_digest="c" * 64,
            parser_version="pv1", chunk_id="chunk-1", chunk_hash="d" * 64,
            lineage_status="linked",
        )],
    )
    base.update(ov)
    return GoldenRecord(**base)  # type: ignore[arg-type]


def test_q2_release_hash_covers_full_semantic_model() -> None:
    """复审 #7：canonical 全量哈希——任一影响评测/回验/来源审计的字段变化都改变 hash。"""
    base = release_hash([_lineage_rec()])
    assert base != release_hash([_lineage_rec(doc="brochure.pdf")])
    assert base != release_hash([_lineage_rec(product_name="改名")])
    assert base != release_hash([_lineage_rec(field_name="改字段名")])
    assert base != release_hash([_lineage_rec(reasoning="换了理由")])
    assert base != release_hash([_lineage_rec(disputed=True, disputed_reason="quote_mismatch")])
    assert base != release_hash([_lineage_rec(schema_version="v2")])
    assert base != release_hash([_lineage_rec(annotator_model="m2")])
    ev = _lineage_rec().evidence[0]
    assert base != release_hash([_lineage_rec(
        evidence=[ev.model_copy(update={"source_revision": "e" * 64})])])
    assert base != release_hash([_lineage_rec(
        evidence=[ev.model_copy(update={"file_hash": "f" * 64})])])


def test_q2_3_approval_record_is_frozen() -> None:
    a = _artifact()
    rec = approve_baseline(a, _candidate(a), approved_by="claude", approved_at=_AT)
    assert isinstance(rec, ApprovalRecord)
    with pytest.raises(Exception):  # noqa: B017,PT011
        rec.version = 9
