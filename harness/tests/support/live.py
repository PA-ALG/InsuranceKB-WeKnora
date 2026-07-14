"""Resource-safe helpers for real live test scopes."""

from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager

from insurance_harness.db.base import make_engine, make_session_factory
from insurance_harness.db.scope import KnowledgeScope, load_scope

AsyncCleanup = Callable[[], Awaitable[None]]


@contextmanager
def live_scope_context(
    database_url: str,
    space_id: str,
) -> Iterator[KnowledgeScope]:
    """Keep a loaded scope's Session and Engine alive for the caller's context."""
    engine = make_engine(database_url)
    try:
        session = make_session_factory(engine)()
        try:
            yield load_scope(session, space_id)
        finally:
            try:
                session.close()
            finally:
                del session
    finally:
        try:
            engine.dispose()
        finally:
            del engine


async def run_cleanups_preserving_failure(
    cleanups: Sequence[AsyncCleanup],
    *,
    primary_error: BaseException | None,
) -> None:
    """Attempt every live cleanup without replacing an in-flight test failure."""

    first_cleanup_error: BaseException | None = None
    for cleanup in cleanups:
        try:
            await cleanup()
        except BaseException as cleanup_error:
            note = f"live cleanup failed with {type(cleanup_error).__name__}"
            if primary_error is not None:
                primary_error.add_note(note)
            elif first_cleanup_error is None:
                first_cleanup_error = cleanup_error
            else:
                first_cleanup_error.add_note(note)
    if first_cleanup_error is not None:
        raise first_cleanup_error
