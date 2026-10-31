"""010 结构化导入：通道一 bootstrap 的 Space 绑定、幂等、dry-run 与 CLI。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, KnowledgeSpace
from insurance_harness.db.scope import UnboundKnowledgeSpace
from insurance_harness.structured_import import (
    bootstrap_from_dir,
)
from tests.ingest.structured_import.helpers import _bound_space, _claims_footprint, _meta_dir

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

_REAL_DATASET = Path(__file__).resolve().parents[4] / "dataset" / "shouxian_product"


def _product_count(session: Session, space_id: str) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(InsuranceProduct).where(
                InsuranceProduct.space_id == space_id
            )
        ).scalar_one()
    )


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
