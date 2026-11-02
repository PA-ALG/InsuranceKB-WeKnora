"""PV-5b RED (Codex): fixed Git data dates, not refresh audit dates (Issue #532).

Synthetic Git commits and local registry files only. No business registry, HTTP or model calls.
The old implementation reports the refresh day instead of the pinned commit's UTC+8 day.
"""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.bundle.client import ReleaseMember
from insurance_harness.ingest.identity_refresh import plan_refresh
from insurance_harness.ingest.registry import load_registry, registry_document, save_registry
from insurance_harness.ingest.registry_migration import migrate_registry, plan_migration
from insurance_harness.ingest.version_catalog import (
    VersionCatalog,
    catalog_from_checkout,
    load_catalog,
    save_catalog,
)
from insurance_harness.ingest.version_metadata import entity_metadata
from tests.ingest.manifest_repo import git, meta, repository, write_meta
from tests.ingest.test_identity_refresh import TYPES, active, claim_member, entity_member
from tests.ingest.upload_helpers import PRODUCTS
from tests.ingest.version_helpers import rich_v1

WHEN = "2026-10-20T16:30:00+00:00"  # the snapshot is October 21 in UTC+8
AUDIT1 = datetime(2026, 11, 1, 8, tzinfo=UTC)
AUDIT2 = datetime(2026, 11, 3, 9, tzinfo=UTC)
REAL_REPLACE = os.replace


def pinned(root: Path, clock: pytest.MonkeyPatch, when: str = WHEN) -> str:
    with clock.context() as env:
        env.setenv("GIT_AUTHOR_DATE", "2001-01-01T00:00:00+00:00")
        env.setenv("GIT_COMMITTER_DATE", when)
        return repository(
            root,
            *(
                ("在售", pid, meta(pid, 1, PRODUCTS[pid]["name"], PRODUCTS[pid]["clause_code"]))
                for pid in ("1828", "1814")
            ),
        )


def next_commit(root: Path, when: str) -> str:
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "next snapshot"],
        env=os.environ | {"GIT_AUTHOR_DATE": WHEN, "GIT_COMMITTER_DATE": when},
        check=True,
        capture_output=True,
    )
    return git(root, "rev-parse", "HEAD")


def basis_date(value: Any, product: str = "1828") -> str | None:
    lifecycle = entity_metadata(product, value.products[product], value.metadata_basis).lifecycle
    assert lifecycle is not None
    return lifecycle.basis_date


def legacy_catalog(value: VersionCatalog) -> VersionCatalog:
    document = value.model_dump(mode="json")
    document.pop("snapshot_date", None)
    return VersionCatalog.model_validate_json(json.dumps(document))


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ("2026-10-20T15:59:59+00:00", "2026-10-20"),
        ("2026-10-20T16:00:00+00:00", "2026-10-21"),
        ("2026-10-22T02:00:00+14:00", "2026-10-21"),
    ],
)
def test_snapshot_uses_committer_time_in_utc_plus_eight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str, expected: str
) -> None:
    root = tmp_path / "repo"
    commit = pinned(root, monkeypatch, when)
    built = catalog_from_checkout(root, commit)
    assert built.model_dump().get("snapshot_date") == expected
    assert built.commit == commit


def test_date_and_records_come_from_fixed_objects_not_head_or_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    commit = pinned(root, monkeypatch)
    first = catalog_from_checkout(root, commit)
    newer = next_commit(root, "2026-11-02T20:00:00+00:00")
    write_meta(root, "在售", "1828", "broken working tree")
    assert catalog_from_checkout(root, commit).document() == first.document()
    assert catalog_from_checkout(root, commit).model_dump().get("snapshot_date") == "2026-10-21"
    changed = catalog_from_checkout(root, newer)
    assert changed.model_dump().get("snapshot_date") == "2026-11-03"
    assert changed.versions == first.versions  # only the commit metadata changed
    assert changed.digest() != first.digest()
    _, digest = save_catalog(changed, tmp_path / "registry.json")
    assert (
        load_catalog(
            tmp_path / "registry.json", digest, repository=changed.repository, commit=newer
        )
        == changed
    )


def test_same_commit_with_different_audit_times_keeps_data_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    built = catalog_from_checkout(root, pinned(root, monkeypatch))
    before = rich_v1()
    first, _ = plan_migration(before, built, now=AUDIT1)
    assert basis_date(first) == "2026-10-21"
    # A real derived-version change may update the audit time without changing the source date.
    renamed = first.model_copy(deep=True)
    renamed.products["1828"].names = ["乙安康医疗保险"]
    second, _ = plan_migration(renamed, built, refresh=True, now=AUDIT2)
    assert second.metadata_basis is not None and first.metadata_basis is not None
    assert second.metadata_basis.synced_at != first.metadata_basis.synced_at
    assert basis_date(second) == basis_date(first) == "2026-10-21"
    again, _ = plan_migration(second, built, refresh=True, now=datetime(2026, 12, 1, tzinfo=UTC))
    assert again == second  # audit-only churn must not defeat the existing no-op


def test_real_refresh_backfills_legacy_then_repeated_identity_plan_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    built = catalog_from_checkout(root, pinned(root, monkeypatch))
    path = tmp_path / "registry.json"
    old, _ = plan_migration(rich_v1(), legacy_catalog(built), now=AUDIT1)
    save_registry(old, path)
    assert basis_date(old) == "2026-11-01"  # legacy fallback, no read-time guessing
    initial = path.read_bytes()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert migrate_registry(path, built, refresh=True, dry_run=True, now=AUDIT2).status == "dry_run"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before
    assert migrate_registry(path, built, refresh=True, now=AUDIT2).status == "committed"
    updated = load_registry(path)
    assert basis_date(updated) == "2026-10-21"
    assert any(p.read_bytes() == initial for p in tmp_path.glob("*.backup-*.json"))
    first = plan_refresh(
        active(
            entity_member("1828"), entity_member("1814"), claim_member("1828", "waiting_period")
        ),
        updated,
        TYPES,
    )
    delivered = active(*(ReleaseMember(**m.model_dump(mode="json")) for m in first.members))
    files = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert migrate_registry(path, built, refresh=True, now=AUDIT1).status == "no_op"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == files
    assert plan_refresh(delivered, load_registry(path), TYPES).noop
    # Even a changed audit timestamp cannot alter the published identity after backfill.
    audit_only = updated.model_copy(deep=True)
    assert audit_only.metadata_basis is not None
    audit_only.metadata_basis.synced_at = "2027-01-01T00:00:00Z"
    assert plan_refresh(delivered, audit_only, TYPES).noop


def test_refresh_backfills_a_missing_date_even_when_catalog_digest_already_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    built = catalog_from_checkout(root, pinned(root, monkeypatch))
    value, _ = plan_migration(rich_v1(), built, now=AUDIT1)
    assert value.metadata_basis is not None
    value.metadata_basis = value.metadata_basis.model_copy(update={"snapshot_date": None})
    refreshed, _ = plan_migration(value, built, refresh=True, now=AUDIT2)
    assert basis_date(refreshed) == "2026-10-21"
    assert refreshed.metadata_basis is not None
    assert refreshed.metadata_basis.synced_at == "2026-11-03T09:00:00Z"


def test_refresh_after_commit_change_uses_new_snapshot_not_audit_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    built = catalog_from_checkout(root, pinned(root, monkeypatch))
    old, _ = plan_migration(rich_v1(), built, now=AUDIT1)
    newer = catalog_from_checkout(root, next_commit(root, "2026-10-22T16:00:00+00:00"))
    refreshed, _ = plan_migration(old, newer, refresh=True, now=AUDIT2)
    assert basis_date(refreshed) == "2026-10-23"
    assert refreshed.metadata_basis is not None
    assert refreshed.metadata_basis.commit == newer.commit


def test_legacy_catalog_and_nested_basis_keep_their_old_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    built = legacy_catalog(catalog_from_checkout(root, pinned(root, monkeypatch)))
    document = built.document()
    assert "snapshot_date" not in json.loads(document)
    assert VersionCatalog.model_validate_json(document).document() == document
    old, _ = plan_migration(rich_v1(), built, now=AUDIT1)
    data = registry_document(old)
    assert "snapshot_date" not in json.loads(data)["metadata_basis"]
    path = tmp_path / "registry.json"
    path.write_bytes(data)
    assert registry_document(load_registry(path)) == data
    assert basis_date(load_registry(path)) == "2026-11-01"
    assert path.read_bytes() == data


@pytest.mark.parametrize("bad", ["2026-02-30", "2026-1-01", "", 20261021, True])
def test_invalid_snapshot_dates_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: object
) -> None:
    root = tmp_path / "repo"
    catalog = catalog_from_checkout(root, pinned(root, monkeypatch))
    value, _ = plan_migration(rich_v1(), catalog, now=AUDIT1)
    assert value.metadata_basis is not None
    for model in (catalog, value.metadata_basis):
        with pytest.raises(ValidationError):
            type(model).model_validate(model.model_dump() | {"snapshot_date": bad})


class Crash(BaseException):
    """Synthetic process interruption, not an ordinary I/O failure."""


def test_legacy_committed_journal_recovers_before_date_backfill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    built = catalog_from_checkout(root, pinned(root, monkeypatch))
    path = tmp_path / "registry.json"
    save_registry(rich_v1(), path)
    original = path.read_bytes()

    def committed_then_crash(source: str, target: str) -> None:
        REAL_REPLACE(source, target)
        raise Crash

    monkeypatch.setattr(os, "replace", committed_then_crash)
    with pytest.raises(Crash):
        migrate_registry(path, legacy_catalog(built), now=AUDIT1)
    monkeypatch.setattr(os, "replace", REAL_REPLACE)
    before_backfill = path.read_bytes()
    assert "snapshot_date" not in json.loads(before_backfill)["metadata_basis"]
    result = migrate_registry(path, built, refresh=True, now=AUDIT2)
    assert (result.status, result.recovered) == ("committed", "committed")
    assert basis_date(load_registry(path)) == "2026-10-21"
    backups = [p.read_bytes() for p in tmp_path.glob("*.backup-*.json")]
    assert original in backups and before_backfill in backups
    assert not path.with_name(path.name + ".migration-journal.json").exists()
