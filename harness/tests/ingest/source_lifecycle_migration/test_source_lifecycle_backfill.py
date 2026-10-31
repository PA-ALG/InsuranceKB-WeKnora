"""021 source lifecycle (SQLite): backfill of historical 017 sources into open issues."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import cast

from alembic import command
from sqlalchemy import Connection, Engine, text

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.knowledge import tables as _knowledge_tables  # noqa: F401
from tests.ingest.source_lifecycle_migration.helpers import (
    MIGRATION_PATH,
    _cfg,
    _db,
    _seed_claim,
    _seed_evidence,
    _seed_space,
)


def _seed_change_set(
    engine: Engine,
    *,
    change_set_id: str,
    space_id: str,
    source_kind: str,
    knowledge_ids: list[str],
    external_record_id: str,
    revision: str,
    created_at: datetime,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO change_sets "
                "(id, space_id, source_kind, knowledge_ids, external_record_id, "
                "source_revision, status, created_by, created_at, updated_at) VALUES "
                "(:id, :space_id, :source_kind, :knowledge_ids, :external_record_id, "
                ":revision, 'applied', 'historical-test', :created_at, :created_at)"
            ),
            {
                "id": change_set_id,
                "space_id": space_id,
                "source_kind": source_kind,
                "knowledge_ids": json.dumps(knowledge_ids),
                "external_record_id": external_record_id,
                "revision": revision,
                "created_at": created_at,
            },
        )


def _seed_historical_017_sources(
    engine: Engine,
    *,
    reverse_timestamps: bool = False,
) -> None:
    early = datetime(2025, 1, 1, tzinfo=UTC)
    late = datetime(2026, 7, 19, tzinfo=UTC)
    if reverse_timestamps:
        early, late = late, early
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=early,
    )
    _seed_space(
        engine,
        space_id="space-b",
        tenant_id="tenant-b",
        raw_kb_id="raw-b",
        now=early,
    )
    for claim_id, space_id in (
        ("claim-evidence", "space-a"),
        ("claim-both", "space-a"),
        ("claim-legacy", "space-a"),
        ("claim-wrong-raw", "space-a"),
        ("claim-foreign", "space-b"),
    ):
        _seed_claim(engine, claim_id=claim_id, space_id=space_id, now=early)

    # Evidence-only: deliberately make the lexical-small revision newer by time.
    _seed_evidence(
        engine,
        evidence_id="evidence-a-f",
        claim_id="claim-evidence",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-a",
        revision="f" * 64,
        extracted_at=early,
    )
    _seed_evidence(
        engine,
        evidence_id="evidence-a-0",
        claim_id="claim-evidence",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-a",
        revision="0" * 64,
        extracted_at=late,
    )
    # Evidence + ChangeSet duplicate for the same source/revision.
    _seed_evidence(
        engine,
        evidence_id="evidence-c-a",
        claim_id="claim-both",
        knowledge_id="knowledge-c",
        raw_kb_id="raw-a",
        revision="a" * 64,
        extracted_at=late,
    )
    # Same knowledge_id in another Space must remain independently scoped.
    _seed_evidence(
        engine,
        evidence_id="evidence-b-a",
        claim_id="claim-foreign",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-b",
        revision="b" * 64,
        extracted_at=early,
    )
    # Legacy and malformed cross-raw Evidence are not trustworthy 017 identities.
    _seed_evidence(
        engine,
        evidence_id="evidence-legacy",
        claim_id="claim-legacy",
        knowledge_id="knowledge-legacy",
        raw_kb_id=None,
        revision=None,
        extracted_at=late,
        source_aware=False,
    )
    _seed_evidence(
        engine,
        evidence_id="evidence-wrong-raw",
        claim_id="claim-wrong-raw",
        knowledge_id="knowledge-wrong-raw",
        raw_kb_id="raw-b",
        revision="9" * 64,
        extracted_at=late,
    )

    # ChangeSet-only: reverse lexical and created_at order; no latest is selected.
    _seed_change_set(
        engine,
        change_set_id="changeset-b-e",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-b"],
        external_record_id="knowledge-b",
        revision="e" * 64,
        created_at=early,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-b-1",
        space_id="space-a",
        source_kind="recompile",
        knowledge_ids=["knowledge-b"],
        external_record_id="knowledge-b",
        revision="1" * 64,
        created_at=late,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-c-a",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-c"],
        external_record_id="knowledge-c",
        revision="a" * 64,
        created_at=early,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-c-c",
        space_id="space-a",
        source_kind="recompile",
        knowledge_ids=["knowledge-c"],
        external_record_id="knowledge-c",
        revision="c" * 64,
        created_at=late,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-c-tombstone",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-c"],
        external_record_id="knowledge-c",
        revision="retract:" + "D" * 56,
        created_at=late,
    )

    # 017 legacy retract and malformed/non-source aggregates must be ignored.
    _seed_change_set(
        engine,
        change_set_id="changeset-legacy-retract",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["legacy-empty"],
        external_record_id="legacy:" + "d" * 57,
        revision="retract:" + "e" * 56,
        created_at=late,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-malformed",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-other"],
        external_record_id="knowledge-malformed",
        revision="7" * 64,
        created_at=late,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-manual",
        space_id="space-a",
        source_kind="manual_edit",
        knowledge_ids=["knowledge-manual"],
        external_record_id="knowledge-manual",
        revision="8" * 64,
        created_at=late,
    )


def _load_0006_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0006_021", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _issue_rows(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, space_id, tenant_id, raw_kb_id, knowledge_id, "
                    "observed_revisions, reason, status, resolved_revision, "
                    "created_at, updated_at FROM source_lifecycle_backfill_issues "
                    "ORDER BY space_id, knowledge_id"
                )
            ).tuples()
        )


def test_l5_backfill_017_historical_sources_creates_only_scoped_open_issues(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "historical-backfill")
    command.upgrade(_cfg(url), "0012")
    _seed_historical_017_sources(engine)

    command.upgrade(_cfg(url), "0006")

    rows = _issue_rows(engine)
    assert [
        (
            row[1],
            row[2],
            row[3],
            row[4],
            json.loads(cast(str, row[5])),
            row[6],
            row[7],
            row[8],
        )
        for row in rows
    ] == [
        (
            "space-a",
            "tenant-a",
            "raw-a",
            "knowledge-a",
            ["0" * 64, "f" * 64],
            "historical_017_source_ordering_unavailable",
            "open",
            None,
        ),
        (
            "space-a",
            "tenant-a",
            "raw-a",
            "knowledge-b",
            ["1" * 64, "e" * 64],
            "historical_017_source_ordering_unavailable",
            "open",
            None,
        ),
        (
            "space-a",
            "tenant-a",
            "raw-a",
            "knowledge-c",
            ["a" * 64, "c" * 64, "retract:" + "d" * 56],
            "historical_017_source_ordering_unavailable_with_tombstone_event",
            "open",
            None,
        ),
        (
            "space-b",
            "tenant-b",
            "raw-b",
            "knowledge-a",
            ["b" * 64],
            "historical_017_source_ordering_unavailable",
            "open",
            None,
        ),
    ]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM source_heads")) == 0
        assert connection.scalar(text("SELECT count(*) FROM source_events")) == 0


def test_l5_backfill_is_idempotent_and_never_uses_time_or_hash_as_latest(
    tmp_path: Path,
) -> None:
    snapshots: list[list[tuple[object, ...]]] = []
    engines: list[Engine] = []
    for name, reverse_timestamps in (("normal-time", False), ("reversed-time", True)):
        url, engine = _db(tmp_path, name)
        engines.append(engine)
        command.upgrade(_cfg(url), "0012")
        _seed_historical_017_sources(
            engine,
            reverse_timestamps=reverse_timestamps,
        )
        command.upgrade(_cfg(url), "0006")
        snapshots.append(_issue_rows(engine))

    # IDs and observed sets are deterministic; creation timestamps may differ by run.
    assert [tuple(row[:9]) for row in snapshots[0]] == [
        tuple(row[:9]) for row in snapshots[1]
    ]
    before_rerun = snapshots[0]
    module = _load_0006_migration()
    backfill = cast(
        Callable[[Connection], None],
        module._backfill_historical_017_sources,
    )
    with engines[0].begin() as connection:
        backfill(connection)

    assert _issue_rows(engines[0]) == before_rerun
    for engine in engines:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM source_heads")) == 0
            assert connection.scalar(text("SELECT count(*) FROM source_events")) == 0


def test_l5_backfill_source_aware_tombstone_only_creates_open_issue_but_legacy_retract_does_not(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "tombstone-only-backfill")
    command.upgrade(_cfg(url), "0012")
    now = datetime(2026, 7, 19, tzinfo=UTC)
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=now,
    )
    source_tombstone = "retract:" + "A" * 56
    _seed_change_set(
        engine,
        change_set_id="changeset-source-tombstone",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-tombstone"],
        external_record_id="knowledge-tombstone",
        revision=source_tombstone,
        created_at=now,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-legacy-tombstone",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["legacy-empty"],
        external_record_id="legacy:" + "b" * 57,
        revision="retract:" + "C" * 56,
        created_at=now,
    )

    command.upgrade(_cfg(url), "0006")

    rows = _issue_rows(engine)
    assert len(rows) == 1
    assert rows[0][1:8] == (
        "space-a",
        "tenant-a",
        "raw-a",
        "knowledge-tombstone",
        json.dumps([source_tombstone.lower()]),
        "historical_017_source_ordering_unavailable_with_tombstone_event",
        "open",
    )
    before_rerun = rows
    module = _load_0006_migration()
    backfill = cast(
        Callable[[Connection], None],
        module._backfill_historical_017_sources,
    )
    with engine.begin() as connection:
        backfill(connection)

    assert _issue_rows(engine) == before_rerun
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM source_heads")) == 0
        assert connection.scalar(text("SELECT count(*) FROM source_events")) == 0
