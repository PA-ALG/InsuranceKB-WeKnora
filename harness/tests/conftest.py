from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.config import HarnessSettings
from insurance_harness.schemas import SchemaRegistry, load_schema_registry

BASE_URL = "http://weknora.test"


@pytest.fixture
def settings() -> HarnessSettings:
    return HarnessSettings(
        weknora_base_url=BASE_URL,
        weknora_api_key="sk-test",
        poll_interval_s=0.01,
        poll_timeout_s=0.5,
        retry_max_attempts=3,
    )


@pytest.fixture
async def client(settings: HarnessSettings) -> AsyncIterator[WeKnoraClient]:
    c = WeKnoraClient(settings)
    yield c
    await c.aclose()


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_BASELINE_DIR = REPO_ROOT / "docs" / "insurance-kb" / "schema-baseline"
DATASET_DIR = REPO_ROOT / "dataset" / "shouxian_product"


@pytest.fixture(scope="session")
def schema_dir() -> Path:
    return SCHEMA_BASELINE_DIR


@pytest.fixture(scope="session")
def registry() -> "SchemaRegistry":
    return load_schema_registry(SCHEMA_BASELINE_DIR)


# --- change 007：知识域 DB 夹具（sqlite 仅测试用，边界见 db/README.md） ---


@pytest.fixture
def kb_session(tmp_path: Path) -> "Iterator[Session]":
    from insurance_harness.db import models as _db_models  # noqa: F401
    from insurance_harness.db.base import Base, make_engine, make_session_factory
    from insurance_harness.knowledge import tables as _kb_tables  # noqa: F401

    engine = make_engine(f"sqlite:///{tmp_path}/kb.db")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    yield session
    session.close()
    engine.dispose()
