"""SQLAlchemy 基础设施。

生产使用 PostgreSQL（`postgresql+psycopg://`，docker-compose.harness.yml）；
测试允许 SQLite（差异边界见 db/README.md）。连接串经 ``HarnessSettings.db_url``
或显式传入，禁止硬编码。
"""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_engine(db_url: str, *, echo: bool = False) -> Engine:
    return create_engine(db_url, echo=echo, future=True)


def make_session_factory(engine: Engine) -> Callable[[], Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
