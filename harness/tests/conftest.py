from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.config import HarnessSettings
from insurance_harness.schemas import SchemaRegistry, load_schema_registry

if TYPE_CHECKING:
    from insurance_harness.db.models import KnowledgeSpace
    from insurance_harness.db.scope import KnowledgeScope

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


# --- change 016：显式 KnowledgeSpace / KnowledgeScope 测试夹具 ---


@pytest.fixture
def session(tmp_path: Path) -> "Iterator[Session]":
    from insurance_harness.db import models as _db_models  # noqa: F401
    from insurance_harness.db.base import Base, make_engine, make_session_factory

    engine = make_engine(f"sqlite:///{tmp_path}/scope.db")
    Base.metadata.create_all(engine)
    db_session = make_session_factory(engine)()
    yield db_session
    db_session.close()
    engine.dispose()


def make_bound_space(
    session: Session,
    *,
    tenant_id: str,
    raw_kb_id: str,
    wiki_kb_id: str,
) -> "KnowledgeSpace":
    """Persist a fully bound space; tests must opt in explicitly."""
    from insurance_harness.db.models import KnowledgeSpace

    row = KnowledgeSpace(
        name=f"{tenant_id}:{raw_kb_id}:{wiki_kb_id}",
        binding_status="bound",
        tenant_id=tenant_id,
        raw_kb_id=raw_kb_id,
        wiki_kb_id=wiki_kb_id,
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def bound_space(session: Session) -> "Callable[..., KnowledgeSpace]":
    """Return a factory pinned to this test's real database session."""

    def create(*, tenant_id: str, raw_kb_id: str, wiki_kb_id: str) -> "KnowledgeSpace":
        return make_bound_space(
            session,
            tenant_id=tenant_id,
            raw_kb_id=raw_kb_id,
            wiki_kb_id=wiki_kb_id,
        )

    return create


@pytest.fixture
def bound_scope(session: Session) -> "Callable[..., KnowledgeScope]":
    """Return a scope factory requiring every external binding explicitly."""
    from insurance_harness.db.scope import load_scope

    def create(*, tenant_id: str, raw_kb_id: str, wiki_kb_id: str) -> "KnowledgeScope":
        row = make_bound_space(
            session,
            tenant_id=tenant_id,
            raw_kb_id=raw_kb_id,
            wiki_kb_id=wiki_kb_id,
        )
        return load_scope(session, row.id)

    return create


@pytest.fixture
def adapter_scope(
    bound_scope: "Callable[..., KnowledgeScope]",
) -> "KnowledgeScope":
    """A persisted bound scope for the legacy WeKnora adapter contract tests."""
    return bound_scope(
        tenant_id="tenant-1",
        raw_kb_id="kb-1",
        wiki_kb_id="wiki-1",
    )
