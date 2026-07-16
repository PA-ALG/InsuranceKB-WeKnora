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
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
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
    session_factory = make_session_factory(make_engine(db_url))
    with session_factory() as session:
        try:
            report = bootstrap_from_dir(
                session, args.root, space_id=args.space_id, apply=args.apply
            )
        except (UnboundKnowledgeSpace, ScopeViolation):
            # fail-closed：不泄露 space 存在性/绑定细节（016 语义）
            print("[fail-closed] KnowledgeSpace 校验未通过，未执行任何写入")
            return 1
    print(report.summary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
