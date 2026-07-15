"""019 spec Q1.3~Q1.5：release 校验器（严格 TDD，先红后绿；成功 + 各失败分支）。"""

from datetime import UTC, datetime
from pathlib import Path

from insurance_harness.goldenset import (
    Evidence,
    ExpectedProduct,
    GoldenRecord,
    build_release,
    validate_release,
)
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry

_LINE = ProductLineSchema(
    line_key="t",
    sheet_name="测试",
    fields=(
        FieldSpec(name="犹豫期", field_id="hesitation_period", source_sheet="t"),
        FieldSpec(name="等待期", field_id="waiting_period", source_sheet="t"),
        FieldSpec(
            name="内部备注", field_id="internal_note", extractable=False, source_sheet="t"
        ),
    ),
)
_REGISTRY = SchemaRegistry(version="v1.1+deadbeefcafe", lines={"t": _LINE}, glossary=())
_EXPECTED = [ExpectedProduct(product_id="P1", line_key="t")]


def _rec(field_id: str, value: str | None, *, disputed: bool = False) -> GoldenRecord:
    return GoldenRecord(
        product_id="P1", product_name="产品P1", doc="保险条款.pdf",
        field_id=field_id, field_name=field_id, value=value,
        tri_state="present" if value else "absent_explicitly",
        evidence=[Evidence(page=1, quote=value)] if value else [],
        disputed=disputed, disputed_reason="quote_mismatch" if disputed else None,
        annotator_model="claude-test", schema_version="v1.1+deadbeefcafe",
        created_at=datetime(2026, 7, 11, tzinfo=UTC),
    )


def _full() -> list[GoldenRecord]:
    return [_rec("hesitation_period", "20日"), _rec("waiting_period", "90天")]


def _check(result: object, name: str) -> object:
    return next(c for c in result.checks if c.name == name)  # type: ignore[attr-defined]


def test_q1_valid_release_passes(tmp_path: Path) -> None:
    build_release(_full(), tmp_path / "gs")
    result = validate_release(
        tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED, require_evidence=False
    )
    assert result.passed, result.failures()
    assert {c.name for c in result.checks} == {
        "release_immutable", "products_complete", "disputed_rate",
        "extractable_coverage", "self_eval",
    }


def test_q1_3_non_extractable_field_not_counted_missing(tmp_path: Path) -> None:
    # internal_note 非 extractable，缺记录不应导致 extractable_coverage 失败
    build_release(_full(), tmp_path / "gs")
    result = validate_release(tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED)
    assert _check(result, "extractable_coverage").passed  # type: ignore[attr-defined]


def test_q1_3_missing_product_fails(tmp_path: Path) -> None:
    build_release(_full(), tmp_path / "gs")
    expected = _EXPECTED + [ExpectedProduct(product_id="P2", line_key="t")]
    result = validate_release(tmp_path / "gs", registry=_REGISTRY, expected=expected)
    check = _check(result, "products_complete")
    assert not result.passed and not check.passed and "P2" in check.detail  # type: ignore[attr-defined]


def test_q1_3_extra_product_does_not_fail_completeness(tmp_path: Path) -> None:
    # release 有 P1，expected 为空 → 不缺产品，completeness 仍通过（额外产品只记 detail）
    build_release(_full(), tmp_path / "gs")
    result = validate_release(tmp_path / "gs", registry=_REGISTRY, expected=[])
    assert _check(result, "products_complete").passed  # type: ignore[attr-defined]


def test_q1_3_high_disputed_rate_fails(tmp_path: Path) -> None:
    records = [_rec("hesitation_period", "20日", disputed=True),
               _rec("waiting_period", "90天")]  # 1/2 = 0.5 > 0.2
    build_release(records, tmp_path / "gs")
    result = validate_release(tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED)
    assert not _check(result, "disputed_rate").passed  # type: ignore[attr-defined]


def test_q1_3_disputed_rate_at_threshold_passes(tmp_path: Path) -> None:
    # 1/5 = 0.2，等于阈值不算超
    records = [_rec("hesitation_period", "20日", disputed=True)] + [
        _rec("waiting_period", f"{i}天") for i in range(4)
    ]
    build_release(records, tmp_path / "gs")
    result = validate_release(
        tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED, max_disputed_rate=0.2
    )
    assert _check(result, "disputed_rate").passed  # type: ignore[attr-defined]


def test_q1_3_missing_extractable_field_fails(tmp_path: Path) -> None:
    build_release([_rec("hesitation_period", "20日")], tmp_path / "gs")  # 缺 waiting_period
    result = validate_release(tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED)
    check = _check(result, "extractable_coverage")
    assert not check.passed and "waiting_period" in check.detail  # type: ignore[attr-defined]


def test_q1_4_self_eval_is_one_on_consistent_release(tmp_path: Path) -> None:
    build_release(_full(), tmp_path / "gs")
    result = validate_release(
        tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED, require_evidence=False
    )
    check = _check(result, "self_eval")
    assert check.passed and "P/R/F1=1.0" in check.detail  # type: ignore[attr-defined]


def test_q1_4_evidence_required_by_default_without_dataset_root_fails(tmp_path: Path) -> None:
    """codex #6：默认强制证据回验；无 dataset_root 无法回验 → self_eval 失败，不静默跳过。"""
    build_release(_full(), tmp_path / "gs")
    result = validate_release(tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED)
    check = _check(result, "self_eval")
    assert not check.passed and "未回验" in check.detail  # type: ignore[attr-defined]
    assert not result.passed


def test_q1_3_disputed_default_threshold_is_five_percent(tmp_path: Path) -> None:
    """codex #6：默认 max_disputed_rate=0.05；10% disputed 的产品应判失败。"""
    records = [_rec("hesitation_period", "20日", disputed=True)] + [
        _rec("waiting_period", f"{i}天") for i in range(9)
    ]  # 1/10 = 0.10 > 0.05
    build_release(records, tmp_path / "gs")
    result = validate_release(
        tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED, require_evidence=False
    )
    assert not _check(result, "disputed_rate").passed  # type: ignore[attr-defined]


def test_q1_4_missing_manifest_flags_not_immutable(tmp_path: Path) -> None:
    build_release(_full(), tmp_path / "gs")
    (tmp_path / "gs" / "manifest.json").unlink()  # 破坏"已完成 release"标志
    result = validate_release(tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED)
    assert not _check(result, "release_immutable").passed  # type: ignore[attr-defined]
    assert not result.passed


def test_q1_failures_helper_returns_only_failed(tmp_path: Path) -> None:
    build_release([_rec("hesitation_period", "20日")], tmp_path / "gs")  # 缺 waiting_period
    result = validate_release(
        tmp_path / "gs", registry=_REGISTRY, expected=_EXPECTED, require_evidence=False
    )
    names = {c.name for c in result.failures()}
    assert names == {"extractable_coverage"}
