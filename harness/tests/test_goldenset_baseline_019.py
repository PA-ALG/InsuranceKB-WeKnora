"""019 spec Q2 + codex 复审：baseline artifact / 不可变批准 / 内容寻址产物 / 强绑定批准链。

严格 TDD + 对抗性负例：批准链的不变量必须"非法状态不可构造"——
错绑画像、省略回归、伪造产物引用都必须被拒（不靠调用方自觉）。
"""

from datetime import UTC, datetime

import pytest

from insurance_harness.goldenset import (
    ApprovalRecord,
    ArtifactRef,
    BaselineArtifact,
    BaselineNotApprovableError,
    Evidence,
    GoldenRecord,
    ProductRunStatus,
    RunFingerprint,
    approve_baseline,
    release_hash,
)
from insurance_harness.goldenset.profile import FieldMetrics, QualityProfile

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _fp(**overrides: str) -> RunFingerprint:
    base = dict(
        git_sha="abc123", schema_version="v1.1+deadbeefcafe", model_id="deepseek-v4-flash",
        prompt_version="p1", template_profile="tpl1", source_profile="src1",
        golden_release_hash="rh1",
    )
    base.update(overrides)
    return RunFingerprint(**base)


def _profile(fp: RunFingerprint | None = None, *, value_accuracy: float = 1.0) -> QualityProfile:
    """一份达标画像，指纹默认与 _artifact 一致（批准要求两者指纹相等）。"""
    metrics = FieldMetrics(
        field_id="f1", support=12, value_accuracy=value_accuracy,
        hallucination_rate=0.0, evidence_accuracy=1.0, tri_state_confusion={},
    )
    return QualityProfile(profile_version=1, fingerprint=fp or _fp(), fields={"f1": metrics})


def _ref(count: int = 10, *, sha256: str = _HASH_A, path: str = "artifacts/x.json") -> ArtifactRef:
    return ArtifactRef(path=path, sha256=sha256, count=count)


def _product(**ov: object) -> ProductRunStatus:
    base: dict[str, object] = dict(
        product_id="P1", pred_count=10, keypoints_status="ready",
        run_manifest_ref=_ref(1), pred_ref=_ref(10), eval_ref=_ref(1),
    )
    base.update(ov)
    return ProductRunStatus(**base)  # type: ignore[arg-type]


def _artifact(
    *,
    fingerprint: RunFingerprint | None = None,
    dead_letter_count: int = 0,
    judge_queue_count: int = 0,
    judgements_count: int = 0,
    products: tuple[ProductRunStatus, ...] | None = None,
) -> BaselineArtifact:
    default = (
        _product(
            dead_letter_count=dead_letter_count,
            judge_queue_count=judge_queue_count, judgements_count=judgements_count,
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
        _product(product_id="P1", pred_count=5, dead_letter_count=2, pred_ref=_ref(5)),
        _product(product_id="P2", pred_count=5, judge_queue_count=3, pred_ref=_ref(5)),
    ))
    assert a.unresolved_total() == 5  # 2 + 3


# ------------------------------------------------- Q2.1 内容寻址产物（codex #3）

def test_q2_1_zero_pred_blocks_approval() -> None:
    a = BaselineArtifact(
        baseline_id="b1", fingerprint=_fp(),
        products=(_product(pred_count=0, pred_ref=_ref(0)),),
    )
    assert any("无预测产物" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="无预测产物"):
        approve_baseline(a, _profile(), approved_by="claude", approved_at=_AT)


def test_q2_1_pending_keypoints_blocks_approval() -> None:
    a = BaselineArtifact(
        baseline_id="b1", fingerprint=_fp(),
        products=(_product(keypoints_status="pending"),),
    )
    with pytest.raises(BaselineNotApprovableError, match="关键点"):
        approve_baseline(a, _profile(), approved_by="claude", approved_at=_AT)


def test_q2_1_missing_artifact_ref_blocks_approval() -> None:
    a = BaselineArtifact(
        baseline_id="b1", fingerprint=_fp(), products=(_product(eval_ref=None),),
    )
    assert any("缺产物引用 eval_ref" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="eval_ref"):
        approve_baseline(a, _profile(), approved_by="claude", approved_at=_AT)


def test_q2_1_empty_sha256_ref_is_not_present() -> None:
    # 用任意路径 + 空/非法 sha256 冒充产物 → 不算存在，阻断批准。
    a = BaselineArtifact(
        baseline_id="b1", fingerprint=_fp(),
        products=(_product(pred_ref=ArtifactRef(path="pred.jsonl", sha256="", count=10)),),
    )
    assert any("缺产物引用 pred_ref" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError):
        approve_baseline(a, _profile(), approved_by="claude", approved_at=_AT)


def test_q2_1_pred_ref_count_must_match_pred_count() -> None:
    a = BaselineArtifact(
        baseline_id="b1", fingerprint=_fp(),
        products=(_product(pred_count=10, pred_ref=_ref(7)),),  # 7 != 10
    )
    assert any("不一致" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="不一致"):
        approve_baseline(a, _profile(), approved_by="claude", approved_at=_AT)


# ------------------------------------------------------------- Q2.2 指纹缺项

def test_q2_2_each_missing_fingerprint_field_is_listed() -> None:
    fp = _fp(git_sha=" ", model_id="")
    assert set(fp.missing_fields()) == {"git_sha", "model_id"}


def test_q2_2_missing_fingerprint_field_blocks_approval() -> None:
    fp = _fp(git_sha=" ")
    a = _artifact(fingerprint=fp)
    assert "fingerprint.git_sha 缺失" in a.approval_blockers()
    with pytest.raises(BaselineNotApprovableError, match="git_sha"):
        approve_baseline(a, _profile(fp), approved_by="claude", approved_at=_AT)


def test_q2_2_unresolved_items_block_approval() -> None:
    a = _artifact(dead_letter_count=1)
    assert any("未解决" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError, match="未解决"):
        approve_baseline(a, _profile(), approved_by="claude", approved_at=_AT)


def test_q2_2_empty_products_block_approval() -> None:
    a = BaselineArtifact(baseline_id="b1", fingerprint=_fp(), products=())
    assert any("无任何产品" in b for b in a.approval_blockers())
    with pytest.raises(BaselineNotApprovableError):
        approve_baseline(a, _profile(), approved_by="claude", approved_at=_AT)


# ------------------------------------------------ Q4.3 身份绑定（codex #1 强绑定）

def test_q4_3_profile_fingerprint_must_match_artifact() -> None:
    """画像指纹与 artifact 指纹不一致（画像不属于该次运行）→ 拒绝批准，哈希无从冒充。"""
    a = _artifact(fingerprint=_fp())
    wrong_profile = _profile(_fp(model_id="other-model"))
    with pytest.raises(BaselineNotApprovableError, match="指纹与 artifact 指纹不一致"):
        approve_baseline(a, wrong_profile, approved_by="claude", approved_at=_AT)


def test_q4_3_approval_binds_internally_computed_hash() -> None:
    a = _artifact()
    profile = _profile()
    rec = approve_baseline(a, profile, approved_by="claude", approved_at=_AT)
    assert rec.profile_hash == profile.content_hash()  # 内部计算，非调用方传入
    assert rec.fingerprint == a.fingerprint == profile.fingerprint


# ------------------------------------------------- Q2.3 版本化 / 不可变

def test_q2_3_approval_is_versioned_and_immutable() -> None:
    a = _artifact()
    p1 = _profile()
    first = approve_baseline(a, p1, approved_by="claude", approved_at=_AT)
    assert first.version == 1
    # 有 prior 必须给 prior_profile（见下 Q4.6）；此处提供不退化的候选。
    second = approve_baseline(
        a, _profile(), approved_by="claude", prior=[first], prior_profile=p1,
        approved_at=_AT,
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
    rec = approve_baseline(a, _profile(), approved_by="claude", prior=[other], approved_at=_AT)
    assert rec.version == 1  # 别的 baseline 的版本不影响 b1


# ------------------------------------------------ Q4.6 回归强制（codex #2）

def test_q4_6_prior_approval_requires_prior_profile() -> None:
    """已有批准版本时省略 prior_profile → 拒绝（不能靠省参数跳过回归）。"""
    a = _artifact()
    first = approve_baseline(a, _profile(), approved_by="claude", approved_at=_AT)
    with pytest.raises(BaselineNotApprovableError, match="必须提供 prior_profile"):
        approve_baseline(a, _profile(), approved_by="claude", prior=[first], approved_at=_AT)


def test_q4_6_failing_regression_blocks_approval() -> None:
    a = _artifact()
    p1 = _profile(value_accuracy=1.0)
    first = approve_baseline(a, p1, approved_by="claude", approved_at=_AT)
    worse = _profile(value_accuracy=0.5)  # 相对已批准退化
    with pytest.raises(BaselineNotApprovableError, match="回归"):
        approve_baseline(
            a, worse, approved_by="claude", prior=[first], prior_profile=p1, approved_at=_AT
        )


def test_q4_6_non_regressing_candidate_approves_as_next_version() -> None:
    a = _artifact()
    p1 = _profile(value_accuracy=1.0)
    first = approve_baseline(a, p1, approved_by="claude", approved_at=_AT)
    rec = approve_baseline(
        a, _profile(value_accuracy=1.0), approved_by="claude",
        prior=[first], prior_profile=p1, approved_at=_AT,
    )
    assert rec.version == 2


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


def test_q2_release_hash_ignores_created_at() -> None:
    """created_at 是标注时间戳、非内容语义——同内容不同时间不改变 release 身份。"""
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
    """canonical 全量哈希：任一影响评测/回验/来源审计的字段变化都改变 hash（codex #7）。"""
    base = release_hash([_lineage_rec()])
    assert base != release_hash([_lineage_rec(doc="brochure.pdf")])
    assert base != release_hash([_lineage_rec(product_name="改名")])
    assert base != release_hash([_lineage_rec(field_name="改字段名")])
    assert base != release_hash([_lineage_rec(reasoning="换了理由")])
    assert base != release_hash([_lineage_rec(disputed=True, disputed_reason="quote_mismatch")])
    assert base != release_hash([_lineage_rec(schema_version="v2")])
    assert base != release_hash([_lineage_rec(annotator_model="m2")])
    # evidence 来源审计 lineage 字段变化也必须改变 hash
    ev = _lineage_rec().evidence[0]
    assert base != release_hash([_lineage_rec(
        evidence=[ev.model_copy(update={"source_revision": "e" * 64})]
    )])
    assert base != release_hash([_lineage_rec(
        evidence=[ev.model_copy(update={"file_hash": "f" * 64})]
    )])
