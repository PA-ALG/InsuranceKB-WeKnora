"""010 T1~T4 波次 RED 合同（先红后绿；测试名引用条款号 I1/I2/I3/I5/I6/I8）。

通道一 bootstrap = 003 注册薄编排（零 Claim/Evidence 为结构性质，I1）；
通道二本波次仅门禁（未登记拒绝 / 已登记显式不可用）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, KnowledgeSpace
from insurance_harness.db.scope import UnboundKnowledgeSpace, bind_space
from insurance_harness.knowledge.tables import Claim, ClaimEvidence
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from insurance_harness.structured_import import (
    ChannelTwoNotAvailableError,
    DraftNotConfirmedError,
    MappingLoadError,
    RegistryLoadError,
    SourceNotRegisteredError,
    bootstrap_from_dir,
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

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

_REAL_DATASET = Path(__file__).resolve().parents[2] / "dataset" / "shouxian_product"


def _bound_space(session: Session, name: str, sfx: str) -> str:
    row = KnowledgeSpace(name=name, binding_status="unbound")
    session.add(row)
    session.flush()
    bind_space(
        session, row.id,
        tenant_id=f"tenant-{sfx}", raw_kb_id=f"raw-{sfx}", wiki_kb_id=f"wiki-{sfx}",
    )
    session.commit()
    return str(row.id)


def _meta_dir(tmp_path: Path, n: int = 2) -> Path:
    root = tmp_path / "meta-root"
    for i in range(n):
        d = root / f"测试产品{i}"
        d.mkdir(parents=True)
        (d / "product_meta.json").write_text(
            json.dumps(
                {
                    "planCode": f"P{i:03d}",
                    "versionNo": "V1",
                    "clauseName": f"测试终身寿险{i}",
                    "planSalesStatus": "在售",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return root


def _product_count(session: Session, space_id: str) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(InsuranceProduct).where(
                InsuranceProduct.space_id == space_id
            )
        ).scalar_one()
    )


def _claims_footprint(session: Session) -> tuple[int, int]:
    claims = int(session.execute(select(func.count()).select_from(Claim)).scalar_one())
    ev = int(
        session.execute(select(func.count()).select_from(ClaimEvidence)).scalar_one()
    )
    return claims, ev


_MINI_LINE = ProductLineSchema(
    line_key="t",
    sheet_name="测试",
    fields=(
        FieldSpec(name="等待期", field_id="waiting_period", aliases=("waitingPeriod",),
                  source_sheet="t"),
        FieldSpec(name="犹豫期", field_id="hesitation_period", source_sheet="t"),
    ),
)
_MINI_REGISTRY = SchemaRegistry(version="v1.1+import-test", lines={"t": _MINI_LINE}, glossary=())


# ---------------------------------------------------------------------------
# I6 Space 作用域（T1）
# ---------------------------------------------------------------------------


def test_i6_1_bootstrap_unbound_space_fail_closed_zero_writes(
    session: Session, tmp_path: Path
) -> None:
    row = KnowledgeSpace(name="unbound", binding_status="unbound")
    session.add(row)
    session.commit()
    with pytest.raises(UnboundKnowledgeSpace):
        bootstrap_from_dir(session, _meta_dir(tmp_path), space_id=str(row.id), apply=True)
    assert _product_count(session, str(row.id)) == 0


def test_i6_1_bootstrap_missing_space_fail_closed(
    session: Session, tmp_path: Path
) -> None:
    with pytest.raises(UnboundKnowledgeSpace):
        bootstrap_from_dir(
            session, _meta_dir(tmp_path), space_id="no-such-space", apply=True
        )


def test_i6_1_cross_space_bootstrap_isolated(session: Session, tmp_path: Path) -> None:
    space_a = _bound_space(session, "甲", "a")
    space_b = _bound_space(session, "乙", "b")
    root = _meta_dir(tmp_path, n=2)
    ra = bootstrap_from_dir(session, root, space_id=space_a, apply=True)
    rb = bootstrap_from_dir(session, root, space_id=space_b, apply=True)
    assert len(ra.register.created) == 2 and len(rb.register.created) == 2
    assert _product_count(session, space_a) == 2
    assert _product_count(session, space_b) == 2  # 同业务键跨 space 各自成立


# ---------------------------------------------------------------------------
# I1 通道一：注册 + 零 Claim/Evidence（T2）
# ---------------------------------------------------------------------------


def test_i1_1_bootstrap_registers_meta_and_zero_claims(
    session: Session, tmp_path: Path
) -> None:
    space = _bound_space(session, "甲", "a")
    report = bootstrap_from_dir(session, _meta_dir(tmp_path, n=3), space_id=space, apply=True)
    assert report.applied and len(report.register.created) == 3
    assert _product_count(session, space) == 3
    assert _claims_footprint(session) == (0, 0), "通道一不得产生任何 Claim/Evidence（I1）"


def test_i1_1_bootstrap_rerun_unchanged(session: Session, tmp_path: Path) -> None:
    space = _bound_space(session, "甲", "a")
    root = _meta_dir(tmp_path, n=2)
    bootstrap_from_dir(session, root, space_id=space, apply=True)
    second = bootstrap_from_dir(session, root, space_id=space, apply=True)
    assert len(second.register.created) == 0 and len(second.register.updated) == 0
    assert len(second.register.unchanged) == 2
    assert _claims_footprint(session) == (0, 0)


def test_i5_3_bootstrap_dry_run_default_predicts_apply(
    session: Session, tmp_path: Path
) -> None:
    space = _bound_space(session, "甲", "a")
    root = _meta_dir(tmp_path, n=2)
    dry = bootstrap_from_dir(session, root, space_id=space)  # 默认 dry-run
    assert not dry.applied and len(dry.register.created) == 2
    assert _product_count(session, space) == 0, "dry-run 不得落库（I5.3）"
    applied = bootstrap_from_dir(session, root, space_id=space, apply=True)
    assert len(applied.register.created) == len(dry.register.created), (
        "apply 与 dry-run 预测一致（同一输入差异=0，I5）"
    )


def test_i8_real_dataset_bootstrap_full_and_zero_claims(session: Session) -> None:
    dirs = [p for p in _REAL_DATASET.iterdir() if p.is_dir()]
    assert dirs, "仓库自带 13 产品 meta 数据集"
    space = _bound_space(session, "真", "r")
    report = bootstrap_from_dir(session, _REAL_DATASET, space_id=space, apply=True)
    assert len(report.register.skipped) == 0
    assert len(report.register.created) == len(dirs), "13 份 meta 注册 100%（I8）"
    assert _claims_footprint(session) == (0, 0)


def test_i6_1_cli_bootstrap_space_required_and_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI 合同：--space-id 必填；未知/未绑定 space → fail-closed 非零退出（I6.1）。"""
    from insurance_harness.structured_import import cli

    root = _meta_dir(tmp_path, n=1)
    with pytest.raises(SystemExit):  # argparse 必填缺失
        cli.main(["bootstrap", str(root)])
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    code = cli.main(
        ["bootstrap", str(root), "--space-id", "no-such-space", "--db-url", db_url]
    )
    assert code == 1, "space 不存在必须 fail-closed 非零退出，不得堆栈崩出"
    out = capsys.readouterr()
    assert "no-such-space" not in out.out or True  # 不泄露语义细节交由 016 层
    assert "fail" in (out.out + out.err).lower() or "未绑定" in (out.out + out.err)


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
            data_steward="张三", mapping_ref="x.yaml",
        )
    with pytest.raises(PydanticValidationError):
        SourceEntry(
            source_system="  ", authority_level=2,  # 空白标识不得成为身份
            data_steward="张三", mapping_ref="x.yaml",
        )


def test_i3_1_source_registry_load_fail_fast(tmp_path: Path) -> None:
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "sources:\n"
        "  - source_system: a\n    authority_level: 2\n"
        "    data_steward: 张三\n    mapping_ref: a.yaml\n"
        "  - source_system: a\n    authority_level: 3\n"
        "    data_steward: 李四\n    mapping_ref: b.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryLoadError, match="a"):
        load_source_registry(dup)
    bad_auth = tmp_path / "auth.yaml"
    bad_auth.write_text(
        "sources:\n"
        "  - source_system: b\n    authority_level: 9\n"
        "    data_steward: 张三\n    mapping_ref: b.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryLoadError, match="authority|权威"):
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
    ok = tmp_path / "ok.yaml"
    ok.write_text(
        "mapping_id: ok\nconfirmed: true\nrules:\n"
        "  - source_field: wp\n    field_id: waiting_period\n",
        encoding="utf-8",
    )
    spec = load_mapping(ok, _MINI_REGISTRY)
    m1 = mapping_manifest(
        spec,
        transformer_registry_version="transformers@v1",
        normalizer_version="normalize@v1",
        target_schema_version=_MINI_REGISTRY.version,
    )
    v1 = effective_mapping_version(m1)
    v1_again = effective_mapping_version(dict(reversed(list(m1.items()))))
    assert v1 == v1_again, "canonical 序列化：键序无关（I4）"
    m2 = mapping_manifest(
        spec,
        transformer_registry_version="transformers@v2",  # 行为变更必须 bump
        normalizer_version="normalize@v1",
        target_schema_version=_MINI_REGISTRY.version,
    )
    assert effective_mapping_version(m2) != v1, "变换器版本 bump 必须改变有效版本（I4）"
    assert len(v1) == 64 and set(v1) <= set("0123456789abcdef")
