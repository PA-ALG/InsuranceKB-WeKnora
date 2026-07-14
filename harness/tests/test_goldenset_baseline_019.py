"""019 spec Q2：baseline artifact + 不可变批准记录（严格 TDD，先红后绿）。"""

from datetime import UTC, datetime

import pytest

from insurance_harness.goldenset import (
    ApprovalRecord,
    BaselineArtifact,
    BaselineNotApprovableError,
    Evidence,
    GoldenRecord,
    ProductRunStatus,
    RunFingerprint,
    approve_baseline,
    release_hash,
)

_AT = datetime(2026, 7, 14, tzinfo=UTC)


def _fp(**overrides: str) -> RunFingerprint:
    base = dict(
        git_sha="abc123", schema_version="v1.1+deadbeefcafe", model_id="deepseek-v4-flash",
        prompt_version="p1", template_profile="tpl1", source_profile="src1",
        golden_release_hash="rh1",
    )
    base.update(overrides)
    return RunFingerprint(**base)


def _artifact(
    *,
    fingerprint: RunFingerprint | None = None,
    dead_letter_count: int = 0,
    judge_queue_count: int = 0,
    judgements_count: int = 0,
    products: tuple[ProductRunStatus, ...] | None = None,
) -> BaselineArtifact:
    default = (
        ProductRunStatus(
            product_id="P1", pred_count=10, dead_letter_count=dead_letter_count,
            judge_queue_count=judge_queue_count, judgements_count=judgements_count,
            keypoints_status="ready", eval_report_path="eval/P1.json",
        ),
    )
    return BaselineArtifact(
        baseline_id="b1", fingerprint=fingerprint or _fp(),
        products=default if products is None else products,
    )


# ------------------------------------------------------------- Q2.1 unresolved

def test_q2_1_unresolved_is_dead_letter_plus_pending_judge() -> None:
    a = _artifact(dead_letter_count=2, judge_queue_count=5, judgements_count=3)
    assert a.products[0].unresolved == 4  # 2 dead + (5-3) pending
    assert a.unresolved_total() == 4


def test_q2_1_fully_judged_queue_has_no_pending() -> None:
    a = _artifact(dead_letter_count=0, judge_queue_count=3, judgements_count=3)
    assert a.products[0].unresolved == 0


def test_q2_1_over_judged_does_not_go_negative() -> None:
    a = _artifact(dead_letter_count=1, judge_queue_count=2, judgements_count=5)
    assert a.products[0].unresolved == 1  # pending 夹到 0，仅 dead-letter


def test_q2_1_unresolved_total_sums_products() -> None:
    a = _artifact(products=(
        ProductRunStatus(product_id="P1", pred_count=5, dead_letter_count=2),
        ProductRunStatus(product_id="P2", pred_count=5, judge_queue_count=3),
    ))
    assert a.unresolved_total() == 5  # 2 + 3


# ------------------------------------------------------------- Q2.2 批准阻断

def test_q2_2_each_missing_fingerprint_field_is_listed() -> None:
    fp = _fp(git_sha=" ", model_id="")
    assert set(fp.missing_fields()) == {"git_sha", "model_id"}


def test_q2_2_missing_fingerprint_field_blocks_approval() -> None:
    a = _artifact(fingerprint=_fp(git_sha=" "))
    assert "fingerprint.git_sha 缺失" in a.approval_blockers()
    with pytest.raises(BaselineNotApprovableError, match="git_sha"):
        approve_baseline(a, approved_by="claude", profile_hash="ph1", approved_at=_AT)


def test_q2_2_unresolved_items_block_approval() -> None:
    a = _artifact(dead_letter_count=1)
    assert any("未解决" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="未解决"):
        approve_baseline(a, approved_by="claude", profile_hash="ph1", approved_at=_AT)


def test_q2_2_empty_products_block_approval() -> None:
    a = BaselineArtifact(baseline_id="b1", fingerprint=_fp(), products=())
    assert any("无任何产品" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError):
        approve_baseline(a, approved_by="claude", profile_hash="ph1", approved_at=_AT)


# --------------------------------------------------- Q2.1 产物齐全性（codex #3）

def _product(**ov: object) -> ProductRunStatus:
    base: dict[str, object] = dict(
        product_id="P1", pred_count=10, keypoints_status="ready",
        eval_report_path="eval/P1.json",
    )
    base.update(ov)
    return ProductRunStatus(**base)  # type: ignore[arg-type]


def test_q2_1_zero_pred_blocks_approval() -> None:
    a = BaselineArtifact(baseline_id="b1", fingerprint=_fp(), products=(_product(pred_count=0),))
    assert any("无预测产物" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="无预测产物"):
        approve_baseline(a, approved_by="claude", profile_hash="ph1", approved_at=_AT)


def test_q2_1_pending_keypoints_blocks_approval() -> None:
    a = BaselineArtifact(
        baseline_id="b1", fingerprint=_fp(), products=(_product(keypoints_status="pending"),)
    )
    assert any("关键点未完成" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="关键点"):
        approve_baseline(a, approved_by="claude", profile_hash="ph1", approved_at=_AT)


def test_q2_1_missing_eval_report_blocks_approval() -> None:
    a = BaselineArtifact(
        baseline_id="b1", fingerprint=_fp(), products=(_product(eval_report_path=None),)
    )
    assert any("缺 eval 报告" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="eval"):
        approve_baseline(a, approved_by="claude", profile_hash="ph1", approved_at=_AT)


# ------------------------------------------------------------- Q2.3 批准版本/不可变

def test_q2_3_approval_is_versioned_and_immutable() -> None:
    a = _artifact()
    first = approve_baseline(a, approved_by="claude", profile_hash="ph1", approved_at=_AT)
    assert first.version == 1
    second = approve_baseline(
        a, approved_by="claude", profile_hash="ph1", prior=[first], approved_at=_AT
    )
    assert second.version == 2
    with pytest.raises(Exception):  # noqa: B017,PT011  frozen ValidationError
        first.version = 9
    assert first.version == 1


def test_q2_3_version_isolated_per_baseline() -> None:
    a = _artifact()  # baseline_id="b1"
    other = ApprovalRecord(
        baseline_id="OTHER", version=7, approved_by="x", approved_at=_AT,
        fingerprint=_fp(), profile_hash="ph-other",
    )
    rec = approve_baseline(
        a, approved_by="claude", profile_hash="ph1", prior=[other], approved_at=_AT
    )
    assert rec.version == 1  # 别的 baseline 的版本不影响 b1


def test_q2_3_approval_carries_fingerprint_and_profile_hash() -> None:
    a = _artifact()
    rec = approve_baseline(a, approved_by="claude", profile_hash="ph1", approved_at=_AT)
    assert rec.fingerprint == a.fingerprint and rec.approved_by == "claude"
    assert rec.profile_hash == "ph1"  # codex #2：批准绑定被批准画像内容哈希


def test_q4_6_failing_regression_blocks_approval() -> None:
    """codex #2/Q4.6：候选相对已批准画像回归失败时，approve 必须拒绝。"""
    from insurance_harness.goldenset.profile import FieldVerdict
    a = _artifact()
    bad = FieldVerdict(field_id="<regression>", eligible=False, failures=("f1: 退化",))
    with pytest.raises(BaselineNotApprovableError, match="回归"):
        approve_baseline(
            a, approved_by="claude", profile_hash="ph1", regression=bad, approved_at=_AT
        )


def test_q4_6_passing_regression_allows_approval() -> None:
    from insurance_harness.goldenset.profile import FieldVerdict
    a = _artifact()
    ok = FieldVerdict(field_id="<regression>", eligible=True)
    rec = approve_baseline(
        a, approved_by="claude", profile_hash="ph1", regression=ok, approved_at=_AT
    )
    assert rec.version == 1


# ------------------------------------------------------------- release_hash

def _rec(value: str, product: str = "P1") -> GoldenRecord:
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id="f1", field_name="f1", value=value, tri_state="present",
        evidence=[Evidence(page=1, quote=value)],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT,
    )


def test_q2_release_hash_is_stable_and_content_addressable() -> None:
    assert release_hash([_rec("20日")]) == release_hash([_rec("20日")])
    assert release_hash([_rec("20日")]) != release_hash([_rec("21日")])


def test_q2_release_hash_is_order_independent() -> None:
    a = [_rec("v1", "P1"), _rec("v2", "P2")]
    assert release_hash(a) == release_hash(list(reversed(a)))


def _full_rec(**ov: object) -> GoldenRecord:
    base: dict[str, object] = dict(
        product_id="P1", product_name="产品P1", doc="d.pdf", field_id="f1",
        field_name="f1", value="20日", tri_state="present",
        evidence=[Evidence(page=1, quote="第20日")], annotator_model="m1",
        schema_version="v1.1+x", created_at=_AT,
    )
    base.update(ov)
    return GoldenRecord(**base)  # type: ignore[arg-type]


def test_q2_release_hash_covers_all_semantic_fields() -> None:
    """codex #7：改 evidence/schema/annotator/disputed 任一都必须改变 hash。"""
    base = release_hash([_full_rec()])
    assert base != release_hash([_full_rec(evidence=[Evidence(page=2, quote="第20日")])])
    assert base != release_hash([_full_rec(evidence=[Evidence(page=1, quote="改了引文")])])
    assert base != release_hash([_full_rec(schema_version="v2")])
    assert base != release_hash([_full_rec(annotator_model="m2")])
    assert base != release_hash([_full_rec(disputed=True)])
