"""010 CLI::

    python -m insurance_harness.structured_import.cli bootstrap <dir> \
        --space-id ID [--apply] [--db-url URL]

dry-run 默认；``--apply`` 才落库（12 #5 治理规范）。space 未绑定/不存在
→ fail-closed 退出码 1（016 语义，不堆栈崩出、不泄露细节）。
通道二子命令排在 T5+（018+021 之后）。
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from insurance_harness.config import HarnessSettings
from insurance_harness.db.base import make_engine, make_session_factory
from insurance_harness.db.scope import ScopeViolation, UnboundKnowledgeSpace

from .service import bootstrap_from_dir

_DEFAULT_SQLITE = "sqlite:///harness_product.db"


def _resolve_db_url(arg: str | None) -> str:
    """--db-url > HARNESS_DB_URL > 本地 SQLite（对齐 product/cli 惯例）。"""
    if arg:
        return arg
    try:
        settings_url = HarnessSettings().db_url  # type: ignore[call-arg]
    except ValidationError:
        settings_url = os.environ.get("HARNESS_DB_URL")
    if settings_url:
        return settings_url
    print(f"[提示] 未配置数据库连接串，使用本地 SQLite（仅测试用）：{_DEFAULT_SQLITE}")
    return _DEFAULT_SQLITE


def _migrate(db_url: str) -> None:
    """对齐 product/cli._migrate：显式**绝对** script_location，避免 Alembic 把相对
    ``migrations`` 解析到 CWD——从仓库根运行时找不到 env.py（阻断2）。db_url 做 ``%``
    转义（ConfigParser 插值）并经 ``-x db_url=`` 传入。"""
    from alembic import command
    from alembic.config import Config

    harness_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(harness_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(harness_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    cfg.cmd_opts = argparse.Namespace(x=[f"db_url={db_url}"])
    command.upgrade(cfg, "head")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="structured_import")
    sub = parser.add_subparsers(dest="cmd", required=True)
    boot = sub.add_parser("bootstrap", help="通道一：meta 目录 → 003 产品注册（零 Claim）")
    boot.add_argument("root", type=Path)
    boot.add_argument("--space-id", required=True)
    boot.add_argument("--apply", action="store_true", help="缺省 dry-run，不落库")
    boot.add_argument("--db-url", default=None)
    args = parser.parse_args(argv)

    db_url = _resolve_db_url(args.db_url)
    _migrate(db_url)
    engine = make_engine(db_url)
    try:
        session_factory = make_session_factory(engine)
        with session_factory() as session:
            try:
                report = bootstrap_from_dir(
                    session, args.root, space_id=args.space_id, apply=args.apply
                )
            except (UnboundKnowledgeSpace, ScopeViolation):
                # fail-closed：不泄露 space 存在性/绑定细节（016 语义）
                session.rollback()  # 清理本操作半成品，不连带影响外部（此处为独占 Session）
                print("[fail-closed] KnowledgeSpace 校验未通过，未执行任何写入")
                return 1
            # 事务归 CLI（Session 所有者）：apply 提交、dry-run 回滚（阻断1）
            if args.apply:
                session.commit()
            else:
                session.rollback()
    finally:
        engine.dispose()  # 释放连接池（阻断2 附带：CLI 退出前 dispose）

    print(report.summary)
    for line in report.registration.skipped:  # 显式打印跳过原因，不只报计数（T2 诚实）
        print(f"  skipped: {line}")
    reg = report.registration
    if not (reg.created or reg.updated or reg.unchanged):
        # 空输入/零注册多半是指错目录：非零退出让自动化能发现（T2），不静默 exit 0
        print("[空] 未发现可注册的产品目录（检查路径/结构）")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
