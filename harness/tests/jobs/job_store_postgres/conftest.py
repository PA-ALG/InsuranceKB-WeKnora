"""OpenSpec 035 P1.12：JobStore/Outbox 在真实 PostgreSQL 16 的并发合同——共用运行时、配置与行辅助。

覆盖 033 §16.2 对 P1 的义务：多 worker 并发单领、lease 过期接管、迟到
（旧 generation）worker 全写路径拒绝、完成事务 + outbox 原子性（含崩溃/
中断模拟），以及限额、跨 Space fail closed、毒性任务回收有界、Decision
幂等与指标查询。`service_shell/worker` 复用这里的 PostgreSQL 运行时。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.jobs.job_store_postgres.helpers import PostgresRuntime, _fresh_runtime


@pytest.fixture(scope="module")
def postgres_runtime() -> Iterator[PostgresRuntime]:
    yield from _fresh_runtime()


@pytest.fixture
def isolated_postgres_runtime() -> Iterator[PostgresRuntime]:
    """函数级独立数据库：供依赖全局计数（全局限额）的断言使用。"""
    yield from _fresh_runtime()
