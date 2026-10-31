"""010 结构化导入：版本更新、歧义字段、身份规范化与映射 fail-fast。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from insurance_harness.structured_import import (
    MappingLoadError,
    bootstrap_from_dir,
)
from insurance_harness.structured_import.mapping import (
    MappingRule,
    load_mapping,
    propose_mapping_draft,
)
from insurance_harness.structured_import.registry import (
    SourceEntry,
    SourceRegistry,
    resolve_source,
)
from tests.ingest.structured_import.helpers import _MINI_REGISTRY, _bound_space, _meta_dir

# ---------------------------------------------------------------------------
# codex PR#14 复审收口：阻断项 RED（先复现缺陷，再随实现转绿）
# ---------------------------------------------------------------------------


def _single_product_dir(root: Path, plan: str, version: str, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "product_meta.json").write_text(
        json.dumps(
            {"planCode": plan, "versionNo": version, "clauseName": name,
             "planSalesStatus": "在售"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def test_i5_new_version_reported_updated_not_unchanged(
    session: Session, tmp_path: Path
) -> None:
    """阻断3：同 planCode 新增版本是真实副作用，必须报 updated，不得报 unchanged。"""
    space = _bound_space(session, "甲", "a")
    root = tmp_path / "verroot"
    _single_product_dir(root, "P1", "V1", "健康终身寿险")
    bootstrap_from_dir(session, root, space_id=space, apply=True)
    session.commit()
    _single_product_dir(root, "P1", "V2", "健康终身寿险")  # 产品级属性不变，仅新版本
    r = bootstrap_from_dir(session, root, space_id=space, apply=True)
    session.commit()
    assert r.registration.unchanged == [], "新增版本被谎报为 unchanged（阻断3）"
    assert r.registration.updated == ["P1"], "新增版本应报 updated"


def test_i2_ambiguous_field_surfaced_not_silently_picked() -> None:
    """阻断4：同名同分命中 ≥2 field_id 时落 ambiguities，绝不臆断产单一规则。"""
    line = ProductLineSchema(
        line_key="L", sheet_name="s",
        fields=(
            FieldSpec(name="健康告知", field_id="health_disclosure", source_sheet="s"),
            FieldSpec(name="健康告知", field_id="zh_f23783e0ff", source_sheet="s"),
        ),
    )
    reg = SchemaRegistry(version="v", lines={"L": line}, glossary=())
    draft = propose_mapping_draft({"健康告知": "示例"}, reg)
    assert not any(r.source_field == "健康告知" for r in draft.rules), (
        "歧义键不得产生单一臆断规则（阻断4）"
    )
    amb = next((a for a in draft.ambiguities if a.source_field == "健康告知"), None)
    assert amb is not None, "歧义必须显式披露供人工裁决"
    assert set(amb.candidates) == {"health_disclosure", "zh_f23783e0ff"}


def test_i2_line_key_scopes_candidates() -> None:
    """阻断4：指定 line_key 时候选限定到该线，消解跨线同名假歧义。"""
    line_a = ProductLineSchema(
        line_key="A", sheet_name="a",
        fields=(FieldSpec(name="等待期", field_id="waiting_a", source_sheet="a"),),
    )
    line_b = ProductLineSchema(
        line_key="B", sheet_name="b",
        fields=(FieldSpec(name="等待期", field_id="waiting_b", source_sheet="b"),),
    )
    reg = SchemaRegistry(version="v", lines={"A": line_a, "B": line_b}, glossary=())
    # 不限定 → 跨线同名 → 歧义
    d_all = propose_mapping_draft({"等待期": "90天"}, reg)
    assert d_all.ambiguities and not d_all.rules
    # 限定 A → 唯一命中，无歧义
    d_a = propose_mapping_draft({"等待期": "90天"}, reg, line_key="A")
    assert not d_a.ambiguities
    assert [r.field_id for r in d_a.rules] == ["waiting_a"]


def test_i3_source_system_whitespace_normalized_at_identity() -> None:
    """阻断6a：身份字段构造期 strip 归一，避免 ' a ' 登记后以 'a' resolve 落空。"""
    e = SourceEntry(
        source_system=" official-catalog ", authority_level=2,
        data_steward=" 张三 ", mapping_ref="x.yaml", record_schema_ref="s.yaml",
    )
    assert e.source_system == "official-catalog"
    assert e.data_steward == "张三"
    assert resolve_source(SourceRegistry(entries=(e,)), "official-catalog") is e


def test_i3_source_entry_extra_key_forbidden() -> None:
    """阻断6b：拼错键（recrod_schema_ref）必须 fail-fast，不静默丢弃。"""
    from pydantic import ValidationError as PVE

    with pytest.raises(PVE):
        SourceEntry.model_validate(
            {"source_system": "x", "authority_level": 2, "data_steward": "张三",
             "mapping_ref": "x.yaml", "record_schema_ref": "s.yaml",
             "recrod_schema_ref": "typo"}
        )


def test_i3_record_schema_ref_required() -> None:
    """阻断6：I3 明列来源须声明记录 schema 引用——缺失即构造期拒。"""
    from pydantic import ValidationError as PVE

    with pytest.raises(PVE):
        SourceEntry.model_validate(
            {"source_system": "x", "authority_level": 2, "data_steward": "张三",
             "mapping_ref": "x.yaml"}
        )


def test_i2_mapping_rule_typo_key_fail_fast(tmp_path: Path) -> None:
    """阻断6：映射规则拼错键（transformre）不得静默回落默认 identity，须 fail-fast。"""
    bad = tmp_path / "typo.yaml"
    bad.write_text(
        "mapping_id: t\nconfirmed: true\nrules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n    transformre: identity\n",
        encoding="utf-8",
    )
    with pytest.raises(MappingLoadError):
        load_mapping(bad, _MINI_REGISTRY)


def test_i2_mapping_top_level_typo_key_fail_fast(tmp_path: Path) -> None:
    """二次复核：顶层未知键（confirmd）不得静默吞——严格 wire model，与 registry 对称。"""
    bad = tmp_path / "top.yaml"
    bad.write_text(
        "mapping_id: probe\nconfirmed: true\nconfirmd: false\nrules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n",
        encoding="utf-8",
    )
    with pytest.raises(MappingLoadError, match="confirmd"):
        load_mapping(bad, _MINI_REGISTRY)


def test_i2_mapping_whitespace_source_field_fail_fast() -> None:
    """二次复核：空白 source_field 构造期即拒（019：空白不成为身份；min_length 拦不住）。"""
    from pydantic import ValidationError as PVE

    with pytest.raises(PVE):
        MappingRule(source_field="   ", field_id="waiting_period")


def test_i2_mapping_normalized_duplicate_source_field_fail_fast(tmp_path: Path) -> None:
    """二次复核：'wp' 与 ' wp ' 规范化后同一身份——重复检测须基于规范化值。"""
    dup = tmp_path / "dup-norm.yaml"
    dup.write_text(
        "mapping_id: d\nconfirmed: true\nrules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n"
        "  - source_field: ' wp '\n    field_id: hesitation_period\n",
        encoding="utf-8",
    )
    with pytest.raises(MappingLoadError, match="重复"):
        load_mapping(dup, _MINI_REGISTRY)


@pytest.mark.parametrize("value", ['"true"', "1"], ids=["string-true", "int-one"])
def test_i2_mapping_confirmed_requires_strict_bool(tmp_path: Path, value: str) -> None:
    """P0：confirmed 只认真布尔——"true"/1 不得被宽松转换成已确认（I2 审批门禁 fail-closed）。"""
    bad = tmp_path / "loose.yaml"
    bad.write_text(
        f"mapping_id: l\nconfirmed: {value}\nrules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n",
        encoding="utf-8",
    )
    with pytest.raises(MappingLoadError):
        load_mapping(bad, _MINI_REGISTRY)


def test_i2_mapping_rule_identity_normalized_at_construction() -> None:
    """二次复核：身份字段构造期 strip 归一（比较点用规范化值，与 SourceEntry 对称）。"""
    r = MappingRule(source_field=" wp ", field_id=" waiting_period ", transformer=" identity ")
    assert r.source_field == "wp"
    assert r.field_id == "waiting_period"
    assert r.transformer == "identity"


def test_i6_cli_migrate_runs_from_arbitrary_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """阻断2：从任意 CWD（无 migrations/ 子目录）运行 CLI，迁移不得因相对 script_location 崩溃。"""
    from insurance_harness.structured_import import cli

    root = _meta_dir(tmp_path, n=1)
    db_url = f"sqlite:///{tmp_path / 'cwd.db'}"
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    monkeypatch.chdir(workdir)  # 既非 harness/ 也无 migrations/
    # 迁移应成功推进到 space 校验（不存在 → fail-closed 返回 1）；旧代码会在迁移阶段抛错
    code = cli.main(["bootstrap", str(root), "--space-id", "no-such-space", "--db-url", db_url])
    assert code == 1


def test_i8_cli_empty_dir_nonzero_exit(tmp_path: Path) -> None:
    """T2：空输入/零注册视为操作异常（多半指错目录），非零退出让自动化可发现。"""
    from insurance_harness.db.base import make_engine, make_session_factory
    from insurance_harness.structured_import import cli

    db_url = f"sqlite:///{tmp_path / 'empty.db'}"
    cli._migrate(db_url)  # 先建库（alembic）
    eng = make_engine(db_url)
    with make_session_factory(eng)() as s:
        space = _bound_space(s, "甲", "a")
    eng.dispose()
    empty = tmp_path / "empty-root"
    empty.mkdir()
    code = cli.main(["bootstrap", str(empty), "--space-id", space, "--db-url", db_url])
    assert code == 2, "空目录/零注册应非零退出（T2）"
