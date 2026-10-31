"""010 结构化导入：通道二、来源注册表、映射草稿与 manifest 版本。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import UnboundKnowledgeSpace
from insurance_harness.schemas import SchemaRegistry
from insurance_harness.structured_import import (
    ChannelTwoNotAvailableError,
    DraftNotConfirmedError,
    MappingLoadError,
    RegistryLoadError,
    SourceNotRegisteredError,
    import_records,
)
from insurance_harness.structured_import.mapping import (
    effective_mapping_version,
    load_mapping,
    mapping_manifest,
    propose_mapping_draft,
)
from insurance_harness.structured_import.registry import (
    SourceEntry,
    SourceRegistry,
    load_source_registry,
)
from tests.ingest.structured_import.helpers import _MINI_REGISTRY, _bound_space, _claims_footprint

# ---------------------------------------------------------------------------
# I1/I3 通道二门禁（T3）
# ---------------------------------------------------------------------------


def _registry_one() -> SourceRegistry:
    return SourceRegistry(
        entries=(
            SourceEntry(
                source_system="official-catalog",
                authority_level=2,
                data_steward="产品运营组",
                mapping_ref="official-catalog.yaml",
                record_schema_ref="official-catalog.schema.yaml",
            ),
        )
    )


def test_i1_2_channel_two_unregistered_source_fail_closed(session: Session) -> None:
    space = _bound_space(session, "甲", "a")
    with pytest.raises(SourceNotRegisteredError):
        import_records(
            session, _registry_one(),
            source_system="rogue-feed", records=[{"planCode": "X"}], space_id=space,
        )
    assert _claims_footprint(session) == (0, 0)


def test_i1_2_channel_two_registered_source_explicitly_unavailable(
    session: Session,
) -> None:
    space = _bound_space(session, "甲", "a")
    with pytest.raises(ChannelTwoNotAvailableError, match="018|021"):
        import_records(
            session, _registry_one(),
            source_system="official-catalog", records=[{"planCode": "X"}], space_id=space,
        )
    assert _claims_footprint(session) == (0, 0), "已登记来源也零落库（诚实不可用）"


def test_i1_2_channel_two_unbound_space_fail_closed_before_registry(
    session: Session,
) -> None:
    """对称路径：通道二与 bootstrap 同享 space 纪律（I6.1）。"""
    row = KnowledgeSpace(name="unbound2", binding_status="unbound")
    session.add(row)
    session.commit()
    with pytest.raises(UnboundKnowledgeSpace):
        import_records(
            session, _registry_one(),
            source_system="official-catalog", records=[], space_id=str(row.id),
        )


def test_i3_1_source_entry_domain_constraints_on_model(tmp_path: Path) -> None:
    """构造期约束在模型上，不可绕过 loader（21 号第 3 行 / 019 领域类型教训）。"""
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        SourceEntry(
            source_system="x", authority_level=9,  # 越界必须在构造期拦截
            data_steward="张三", mapping_ref="x.yaml", record_schema_ref="s.yaml",
        )
    with pytest.raises(PydanticValidationError):
        SourceEntry(
            source_system="  ", authority_level=2,  # 空白标识不得成为身份
            data_steward="张三", mapping_ref="x.yaml", record_schema_ref="s.yaml",
        )


def test_i3_1_source_registry_load_fail_fast(tmp_path: Path) -> None:
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "sources:\n"
        "  - source_system: a\n    authority_level: 2\n"
        "    data_steward: 张三\n    mapping_ref: a.yaml\n    record_schema_ref: a.s.yaml\n"
        "  - source_system: a\n    authority_level: 3\n"
        "    data_steward: 李四\n    mapping_ref: b.yaml\n    record_schema_ref: b.s.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryLoadError, match="重复"):
        load_source_registry(dup)
    bad_auth = tmp_path / "auth.yaml"
    bad_auth.write_text(
        "sources:\n"
        "  - source_system: b\n    authority_level: 9\n"
        "    data_steward: 张三\n    mapping_ref: b.yaml\n    record_schema_ref: b.s.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryLoadError, match="authority|权威|less than"):
        load_source_registry(bad_auth)


# ---------------------------------------------------------------------------
# I2/I4 映射与 manifest（T4）
# ---------------------------------------------------------------------------


def test_i2_1_mapping_loader_fail_fast(tmp_path: Path) -> None:
    unknown_field = tmp_path / "m1.yaml"
    unknown_field.write_text(
        "mapping_id: m1\nconfirmed: true\nrules:\n"
        "  - source_field: wp\n    field_id: no_such_field\n",
        encoding="utf-8",
    )
    with pytest.raises(MappingLoadError, match="no_such_field"):
        load_mapping(unknown_field, _MINI_REGISTRY)
    unknown_tf = tmp_path / "m2.yaml"
    unknown_tf.write_text(
        "mapping_id: m2\nconfirmed: true\nrules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n    transformer: nope\n",
        encoding="utf-8",
    )
    with pytest.raises(MappingLoadError, match="nope"):
        load_mapping(unknown_tf, _MINI_REGISTRY)
    dup_src = tmp_path / "m3.yaml"
    dup_src.write_text(
        "mapping_id: m3\nconfirmed: true\nrules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n"
        "  - source_field: wp\n    field_id: hesitation_period\n",
        encoding="utf-8",
    )
    with pytest.raises(MappingLoadError, match="wp"):
        load_mapping(dup_src, _MINI_REGISTRY)


@pytest.mark.parametrize(
    "header", ["confirmed: false\n", ""], ids=["explicit-false", "missing-default"]
)
def test_i2_3_unconfirmed_draft_rejected(tmp_path: Path, header: str) -> None:
    """对称路径：confirmed 显式 false 与缺省默认都必须拒（fail-closed 默认）。"""
    draft = tmp_path / "draft.yaml"
    draft.write_text(
        f"mapping_id: d1\n{header}rules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n",
        encoding="utf-8",
    )
    with pytest.raises(DraftNotConfirmedError):
        load_mapping(draft, _MINI_REGISTRY)


def test_i2_4_draft_confidence_bounded_on_model() -> None:
    """DraftRule.confidence 构造期界 0..1（019 Rate 教训：越界比率不可入）。"""
    from pydantic import ValidationError as PydanticValidationError

    from insurance_harness.structured_import.mapping import DraftRule

    with pytest.raises(PydanticValidationError):
        DraftRule(source_field="a", field_id="waiting_period", confidence=1.5, basis="x")


def test_i2_4_draft_generation_deterministic(tmp_path: Path) -> None:
    record = {"waitingPeriod": "90天", "totallyUnknown": 3.14}
    d1 = propose_mapping_draft(record, _MINI_REGISTRY)
    d2 = propose_mapping_draft(record, _MINI_REGISTRY)
    assert d1 == d2, "草案生成必须确定性（I2）"
    assert not d1.confirmed
    hit = next((r for r in d1.rules if r.source_field == "waitingPeriod"), None)
    assert hit is not None and hit.field_id == "waiting_period" and hit.confidence > 0
    assert hit.basis  # 命中依据可追溯
    assert not any(r.source_field == "totallyUnknown" for r in d1.rules), (
        "未匹配键不得乱配（宁缺勿假）"
    )


def test_i4_manifest_effective_version_semantics(tmp_path: Path) -> None:
    from insurance_harness.structured_import import transformers as tf

    ok = tmp_path / "ok.yaml"
    ok.write_text(
        "mapping_id: ok\nconfirmed: true\nrules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n",
        encoding="utf-8",
    )
    spec = load_mapping(ok, _MINI_REGISTRY)
    m1 = mapping_manifest(spec, _MINI_REGISTRY)
    # 阻断5：版本来自权威模块常量 + SchemaRegistry，非调用方自由字符串
    assert m1["transformer_registry_version"] == tf.TRANSFORMER_REGISTRY_VERSION
    assert m1["normalizer_version"] == tf.NORMALIZER_VERSION
    assert m1["target_schema_version"] == _MINI_REGISTRY.version
    v1 = effective_mapping_version(m1)
    v1_again = effective_mapping_version(dict(reversed(list(m1.items()))))
    assert v1 == v1_again, "canonical 序列化：键序无关（I4）"
    # schema 版本变化 → digest 变化（I4：转换/来源版本两轴）
    other = SchemaRegistry(version="v-bumped", lines=_MINI_REGISTRY.lines, glossary=())
    assert effective_mapping_version(mapping_manifest(spec, other)) != v1
    assert len(v1) == 64 and set(v1) <= set("0123456789abcdef")


def test_i4_transformer_registry_immutable_and_pinned() -> None:
    """阻断5：注册表不可变 + 形状 pin——增删变换器而不 bump 版本会令测试失败。"""
    from types import MappingProxyType

    from insurance_harness.structured_import import transformers as tf

    assert isinstance(tf.TRANSFORMERS, MappingProxyType), "注册表须不可变"
    with pytest.raises(TypeError):
        tf.TRANSFORMERS["identity"] = lambda s: "X"  # type: ignore[index]
    # 形状 pin：增删变换器须同步 bump TRANSFORMER_REGISTRY_VERSION
    assert set(tf.TRANSFORMERS) == {"identity"}
    assert tf.TRANSFORMER_REGISTRY_VERSION == "transformers@v1"
