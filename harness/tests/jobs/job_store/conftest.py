"""OpenSpec 035 deterministic lane：JobStore 存储层合同（SQLite 单线程）的共用配置与行辅助。

真实并发/一致性证据只来自 `integration_postgres` lane（P1.12，见 jobs/job_store_postgres）；
本目录只验证单线程可判定的存储层行为：幂等、状态机路由、fencing、配置化策略、
Decision 幂等与指标查询。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from insurance_harness.db.base import Base, make_engine, make_session_factory
from tests.jobs.job_store.helpers import SessionFactory


@pytest.fixture
def job_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{tmp_path}/jobs.db")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(job_engine: Engine) -> SessionFactory:
    return make_session_factory(job_engine)
