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
    MappingRule,
    effective_mapping_version,
    load_mapping,
    mapping_manifest,
    propose_mapping_draft,
)
from insurance_harness.structured_import.registry import (
    SourceEntry,
    SourceRegistry,
    load_source_registry,
    resolve_source,
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
    assert len(ra.registration.created) == 2 and len(rb.registration.created) == 2
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
    assert report.applied and len(report.registration.created) == 3
    assert _product_count(session, space) == 3
    assert _claims_footprint(session) == (0, 0), "通道一不得产生任何 Claim/Evidence（I1）"


def test_i1_1_bootstrap_rerun_unchanged(session: Session, tmp_path: Path) -> None:
    space = _bound_space(session, "甲", "a")
    root = _meta_dir(tmp_path, n=2)
    bootstrap_from_dir(session, root, space_id=space, apply=True)
    second = bootstrap_from_dir(session, root, space_id=space, apply=True)
    assert len(second.registration.created) == 0 and len(second.registration.updated) == 0
    assert len(second.registration.unchanged) == 2
    assert _claims_footprint(session) == (0, 0)


def test_i5_3_bootstrap_dry_run_default_predicts_apply(
    session: Session, tmp_path: Path
) -> None:
    space = _bound_space(session, "甲", "a")
    root = _meta_dir(tmp_path, n=2)
    dry = bootstrap_from_dir(session, root, space_id=space)  # 默认 dry-run
    assert not dry.applied and len(dry.registration.created) == 2
    session.rollback()  # 事务归调用方：dry-run 由调用方回滚（阻断1 契约）
    assert _product_count(session, space) == 0, "dry-run 回滚后不得落库（I5.3）"
    applied = bootstrap_from_dir(session, root, space_id=space, apply=True)
    session.commit()  # 调用方提交
    assert len(applied.registration.created) == len(dry.registration.created), (
        "apply 与 dry-run 预测一致（同一输入差异=0，I5）"
    )
    assert _product_count(session, space) == 2, "apply 提交后落库"


def test_i5_service_does_not_commit_foreign_transaction(
    session: Session, tmp_path: Path
) -> None:
    """阻断1：服务绝不 commit/rollback 它不拥有的 Session（不越界连带调用方工作单元）。"""
    space = _bound_space(session, "甲", "a")
    stray = KnowledgeSpace(name="stray-pending-unrelated", binding_status="unbound")
    session.add(stray)  # 调用方无关的**未提交**行
    report = bootstrap_from_dir(session, _meta_dir(tmp_path, n=2), space_id=space, apply=True)
    assert len(report.registration.created) == 2
    # 服务若擅自 session.commit()，整批已落库、下面 rollback 变 no-op → 断言失败（RED）
    session.rollback()
    assert _product_count(session, space) == 0, "服务擅自提交产品行（阻断1）"
    stray_left = session.execute(
        select(func.count()).select_from(KnowledgeSpace).where(
            KnowledgeSpace.name == "stray-pending-unrelated"
        )
    ).scalar_one()
    assert stray_left == 0, "服务擅自连带提交调用方无关行（阻断1）"


def test_i8_real_dataset_bootstrap_full_and_zero_claims(session: Session) -> None:
    dirs = [p for p in _REAL_DATASET.iterdir() if p.is_dir()]
    assert dirs, "仓库自带 13 产品 meta 数据集"
    space = _bound_space(session, "真", "r")
    report = bootstrap_from_dir(session, _REAL_DATASET, space_id=space, apply=True)
    assert len(report.registration.skipped) == 0
    assert len(report.registration.created) == len(dirs), "13 份 meta 注册 100%（I8）"
    assert _claims_footprint(session) == (0, 0)


def test_i6_1_cli_bootstrap_space_required_and_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI 合同：--space-id 必填；missing 与 unbound 两路径 → fail-closed 非零退出、
    **同形常量响应且不回显被查询标识**（I6.1 防枚举；去掉原 `or True` 空断言，T1）。"""
    from insurance_harness.db.base import make_engine, make_session_factory
    from insurance_harness.structured_import import cli

    root = _meta_dir(tmp_path, n=1)
    with pytest.raises(SystemExit):  # argparse 必填缺失
        cli.main(["bootstrap", str(root)])

    # 路径①：missing space（不存在的标识）
    db1 = f"sqlite:///{tmp_path / 'm.db'}"
    code1 = cli.main(["bootstrap", str(root), "--space-id", "no-such-space", "--db-url", db1])
    resp_missing = capsys.readouterr()
    assert code1 == 1, "missing space 必须 fail-closed 非零退出，不得堆栈崩出"

    # 路径②：unbound space（存在但未绑定）——先种子一个 unbound 行
    db2 = f"sqlite:///{tmp_path / 'u.db'}"
    cli._migrate(db2)
    eng = make_engine(db2)
    with make_session_factory(eng)() as s:
        ub = KnowledgeSpace(name="ub", binding_status="unbound")
        s.add(ub)
        s.commit()
        unbound_id = str(ub.id)
    eng.dispose()
    code2 = cli.main(["bootstrap", str(root), "--space-id", unbound_id, "--db-url", db2])
    resp_unbound = capsys.readouterr()
    assert code2 == 1, "unbound space 必须 fail-closed 非零退出"

    # 防枚举：两路径响应逐字相同，且都不回显被查询的 space 标识
    assert "no-such-space" not in (resp_missing.out + resp_missing.err)
    assert unbound_id not in (resp_unbound.out + resp_unbound.err)
    assert resp_missing.out == resp_unbound.out, "missing/unbound 须同形常量响应，不可区分"
    assert "校验未通过" in resp_missing.out


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
