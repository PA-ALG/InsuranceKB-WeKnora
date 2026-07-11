"""spec G1：schema 注册表加载器。"""

from pathlib import Path

import pytest

from insurance_harness.schemas import (
    SchemaLoadError,
    SchemaRegistry,
    load_schema_registry,
    stable_field_id,
)

EXPECTED_LINES = {
    "medical",
    "critical-illness",
    "accident-medical",
    "accident",
    "term-life",
    "whole-life",
    "annuity",
    "endowment",
    "long-term-care",
    "supplementary-pension",
    "disability-income",
}


def test_g1_1_loads_all_lines(registry: SchemaRegistry) -> None:
    assert set(registry.lines) == EXPECTED_LINES


def test_g1_1_base_fields_merged_into_every_line(registry: SchemaRegistry) -> None:
    for line in registry.lines.values():
        names = {f.name for f in line.fields}
        assert "险种代码" in names, line.line_key
        # v1.1 基础扩展同样并入（extensions-v1.1.yaml）
        ids = {f.field_id for f in line.fields}
        assert "regulatory_filing_no" in ids, line.line_key


def test_g1_1_line_extensions_routed(registry: SchemaRegistry) -> None:
    ci = {f.field_id for f in registry.line("critical-illness").fields}
    assert {"disease_definition_standard", "death_benefit", "health_disclosure"} <= ci
    for key in ("annuity", "supplementary-pension"):
        assert "annuity_start_age" in {f.field_id for f in registry.line(key).fields}
    # 分红型跨险种组
    assert "dividend_distribution" in {f.field_id for f in registry.line("whole-life").fields}
    assert "disability_assessment_standard" in {
        f.field_id for f in registry.line("accident").fields
    }


def test_g1_1_extractable_and_risk_metadata(registry: SchemaRegistry) -> None:
    medical = registry.line("medical")
    zero_deductible = next(f for f in medical.fields if f.name == "0免赔")
    assert zero_deductible.extractable is False  # 取值来源=人工填充
    exclusions = next(f for f in medical.fields if f.field_id == "exclusions_official")
    assert exclusions.risk_level == "high"
    assert exclusions.evidence_required is True
    assert exclusions.value_type == "long"


def test_g1_1_glossary_exposed(registry: SchemaRegistry) -> None:
    assert {t.name for t in registry.glossary} == {"就医绿通", "费用垫付", "其他增值服务"}


def test_g1_3_version_format_and_stability(schema_dir: Path) -> None:
    r1 = load_schema_registry(schema_dir)
    r2 = load_schema_registry(schema_dir)
    assert r1.version.startswith("v1.1+")
    assert len(r1.version.split("+")[1]) == 12
    assert r1.version == r2.version  # 同内容 → 同版本


def test_field_id_deterministic() -> None:
    assert stable_field_id("条款备案/批复文号", "Regulatory Filing No") == "regulatory_filing_no"
    a = stable_field_id("犹豫期")
    assert a == stable_field_id("犹豫期") and a.startswith("zh_")
    assert stable_field_id("犹豫期") != stable_field_id("等待期")


def _write_minimal_baseline(tmp: Path, *, dup: bool = False) -> None:
    (tmp / "base.yaml").write_text(
        "sheet: 基础字段\nfields:\n- {字段名: 险种代码, 取值来源: 官网同步}\n",
        encoding="utf-8",
    )
    fields = "- {字段名: 保什么, 取值来源: 保险责任}\n"
    if dup:
        fields += "- {字段名: 保什么, 取值来源: 保险责任}\n"
    (tmp / "medical.yaml").write_text(
        f"sheet: 医疗保险（医疗险）\nfields:\n{fields}", encoding="utf-8"
    )


def test_g1_2_duplicate_field_fails_fast(tmp_path: Path) -> None:
    _write_minimal_baseline(tmp_path, dup=True)
    with pytest.raises(SchemaLoadError, match="medical.*保什么|保什么"):
        load_schema_registry(tmp_path)


def test_g1_2_missing_base_fails_fast(tmp_path: Path) -> None:
    (tmp_path / "medical.yaml").write_text(
        "sheet: 医疗保险（医疗险）\nfields:\n- {字段名: 保什么}\n", encoding="utf-8"
    )
    with pytest.raises(SchemaLoadError, match="base"):
        load_schema_registry(tmp_path)


def test_g1_2_unknown_extension_group_fails_fast(tmp_path: Path) -> None:
    _write_minimal_baseline(tmp_path)
    (tmp_path / "extensions-v1.1.yaml").write_text(
        "险种级扩展:\n  不存在的险种:\n  - {字段名: X, field_id: x}\n", encoding="utf-8"
    )
    with pytest.raises(SchemaLoadError, match="不存在的险种"):
        load_schema_registry(tmp_path)


def test_g1_2_missing_dir_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(SchemaLoadError, match="不存在"):
        load_schema_registry(tmp_path / "nope")
