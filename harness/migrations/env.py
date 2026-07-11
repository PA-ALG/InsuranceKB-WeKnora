"""Alembic 环境：连接串优先级 -x db_url > HARNESS_DB_URL > alembic.ini。"""

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from insurance_harness.db.base import Base
from insurance_harness.db import models  # noqa: F401  # 注册全部 ORM 表

config = context.config
target_metadata = Base.metadata


def _resolve_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    url = x_args.get("db_url") or os.environ.get("HARNESS_DB_URL") or config.get_main_option(
        "sqlalchemy.url"
    )
    if not url:
        raise RuntimeError("缺少数据库连接串：用 -x db_url=... 或环境变量 HARNESS_DB_URL")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_resolve_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
