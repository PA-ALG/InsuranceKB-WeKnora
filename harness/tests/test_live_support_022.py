"""OpenSpec 022 P0.1: live scope resource lifetime regression coverage."""

import gc
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from insurance_harness.db.base import Base, make_engine
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import is_database_bound_scope
from tests.support.live import live_scope_context, run_cleanups_preserving_failure


def test_p0_1_live_scope_context_keeps_attestation_until_exit(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path}/live-scope.db"
    seed_engine = make_engine(database_url)
    Base.metadata.create_all(seed_engine)
    try:
        with Session(seed_engine) as session:
            session.add(
                KnowledgeSpace(
                    id="live-scope",
                    name="live-scope",
                    binding_status="bound",
                    tenant_id="live-tenant",
                    raw_kb_id="live-raw",
                    wiki_kb_id="live-wiki",
                )
            )
            session.commit()
    finally:
        seed_engine.dispose()

    with live_scope_context(database_url, "live-scope") as scope:
        assert is_database_bound_scope(scope)

    gc.collect()
    assert not is_database_bound_scope(scope)


async def test_p0_3_live_cleanup_attempts_all_actions_without_masking_primary() -> None:
    events: list[str] = []
    primary_error = RuntimeError("primary assertion")

    async def failed_delete() -> None:
        events.append("delete")
        raise OSError("cleanup detail must not replace primary")

    async def close_client() -> None:
        events.append("close")

    await run_cleanups_preserving_failure(
        (failed_delete, close_client),
        primary_error=primary_error,
    )

    assert events == ["delete", "close"]
    assert primary_error.__notes__ == ["live cleanup failed with OSError"]

    events.clear()
    with pytest.raises(OSError, match="cleanup detail must not replace primary"):
        await run_cleanups_preserving_failure(
            (failed_delete, close_client),
            primary_error=None,
        )
    assert events == ["delete", "close"]
