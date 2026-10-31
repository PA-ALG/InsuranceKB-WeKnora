"""OpenSpec 039 wiki-worker 进程外壳：共用的任务、记录型 JobStore 与设置辅助。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.jobs.job_store_postgres.helpers import PostgresRuntime, _fresh_runtime


@pytest.fixture(scope="module")
def postgres_039_runtime() -> Iterator[PostgresRuntime]:
    """Reuse P1's controlled PostgreSQL 16 database lifecycle for P3 acceptance."""
    yield from _fresh_runtime()
