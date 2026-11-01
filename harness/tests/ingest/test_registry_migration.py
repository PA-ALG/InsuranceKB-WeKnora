"""PV-1 acceptance (written by Claude): migrating a registry to v2, and recovering a migration.

Spec docs/design/slices/PV-1-登记表v2与版本迁移.md §4, §5; PV-0 appendix A §1.3, §1.4, §4.
A "crash" is a BaseException the migration does not handle (a killed process); an ordinary
exception before the replace is a failure it cleans up after.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.ingest.registry import ProductRegistry, load_registry, save_registry
from insurance_harness.ingest.registry_migration import (
    MigrationError,
    migrate_registry,
    plan_migration,
)
from tests.ingest.upload_helpers import PRODUCTS, entry, registry
from tests.ingest.version_helpers import catalog, of, rich_v1, version

ROLES = ("terms", "brochure", "rate_table")
REAL_REPLACE = os.replace


class Crash(BaseException):
    """The process dies here."""


def v1_projection(value: ProductRegistry) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(value.model_dump_json())
    data["contract"] = "product-registry.v1"
    data.pop("metadata_basis", None)
    for product in data["products"].values():
        product.pop("version", None)
    return data


def files(path: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.parent.iterdir()) if p.is_file()}


def journal(path: Path) -> Path:
    return path.with_name(path.name + ".migration-journal.json")


def records(path: Path) -> list[dict[str, Any]]:
    log = path.with_name(path.name + ".migrations.jsonl")
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(path.name + ".backup-*.json"))


def written(tmp_path: Path, value: ProductRegistry) -> Path:
    path = tmp_path / "registry.json"
    save_registry(value, path)
    return path


CATALOG = catalog(of("1828"), of("1814"))


# 1. Matching -----------------------------------------------------------------------------------


def test_every_record_and_id_is_kept_and_only_version_fields_are_added() -> None:
    before = rich_v1()
    after, matches = plan_migration(before, CATALOG)
    assert v1_projection(after) == json.loads(before.model_dump_json())
    assert sorted(after.products) == sorted(before.products)
    assert {m.product_id: (m.outcome, m.version_key) for m in matches} == {
        "1814": ("matched", "1814-1"),
        "1828": ("matched", "1828-1"),
    }


def test_unmatched_shared_and_split_codes_leave_the_version_fields_empty() -> None:
    value = registry(p1828=entry("1828", *ROLES), p1814=entry("1814", *ROLES), p596=entry("596"))
    value.products["596"].clause_codes.append(PRODUCTS["1826"]["clause_code"])
    shared = PRODUCTS["1814"]["clause_code"]
    data = catalog(
        of("1828", key="1828-2"),
        version("1814-1", PRODUCTS["1814"]["name"], shared),
        version("1814-2", PRODUCTS["1814"]["name"], shared),
        of("596"),
        of("1826"),
    )
    after, matches = plan_migration(value, data)
    outcome = {m.product_id: (m.outcome, m.version_key) for m in matches}
    assert outcome == {
        "1828": ("matched", "1828-2"),
        "1814": ("ambiguous", None),  # a shared clause code never names one version
        "596": ("ambiguous", None),  # two codes of the entry point at two versions
    }
    ambiguous = after.products["1814"].version
    assert ambiguous is not None and ambiguous.version_ambiguous
    assert ambiguous.version_key is None and ambiguous.sale_start is None
    bare, _ = plan_migration(registry(p1828=entry("1828", *ROLES)), catalog(of("1814")))
    unmatched = bare.products["1828"].version
    assert unmatched is not None and unmatched.version_key is None
    assert not unmatched.version_ambiguous and unmatched.family is not None


def test_two_entries_on_one_version_are_refused() -> None:
    value = registry(p1828=entry("1828", *ROLES), p1814=entry("1814", *ROLES))
    value.products["1814"].clause_codes = [PRODUCTS["1828"]["clause_code"]]
    with pytest.raises(MigrationError) as caught:
        plan_migration(value, CATALOG)
    assert caught.value.code == "MIGRATION_VERSION_DUPLICATE"


def test_a_predecessor_is_linked_only_when_it_is_unique() -> None:
    value = registry(p1828=entry("1828", *ROLES), p1826=entry("1826", *ROLES))
    chained = catalog(
        of("1828", key="1828-2", start="2025-10-01"),
        of("1826", key="1828-1", start="2024-01-01", end="2025-10-01", status="discontinued"),
    )
    after, matches = plan_migration(value, chained)
    newer = after.products["1828"].version
    assert newer is not None and newer.predecessor == "1826"
    assert {m.product_id: m.predecessor for m in matches} == {"1828": "1826", "1826": None}
    gap = catalog(
        of("1828", key="1828-2", start="2025-10-02"),
        of("1826", key="1828-1", start="2024-01-01", end="2025-10-01", status="discontinued"),
    )
    unlinked, _ = plan_migration(value, gap)
    assert all(p.version and p.version.predecessor is None for p in unlinked.products.values())


def test_a_name_that_differs_is_reported_and_never_rewritten() -> None:
    renamed = of("1828", name="平安安佑福（全能版）重大疾病保险（2026）")
    after, matches = plan_migration(registry(p1828=entry("1828", *ROLES)), catalog(renamed))
    assert [m.name_differs for m in matches] == [True]
    assert after.products["1828"].names == [PRODUCTS["1828"]["name"]]


# 2. The command --------------------------------------------------------------------------------


def test_a_migration_backs_up_journals_and_records(tmp_path: Path) -> None:
    path = written(tmp_path, rich_v1())
    original = path.read_bytes()
    report = migrate_registry(path, CATALOG)
    assert (report.status, report.recovered) == ("committed", None)
    assert load_registry(path).contract == "product-registry.v2"
    [backup] = backups(path)
    assert backup.read_bytes() == original
    assert not journal(path).exists()
    assert [r["result"] for r in records(path)] == ["committed"]
    assert report.retired == ["1828"]


def test_a_dry_run_and_a_second_run_write_nothing(tmp_path: Path) -> None:
    path = written(tmp_path, rich_v1())
    before = files(path)
    assert migrate_registry(path, CATALOG, dry_run=True).status == "dry_run"
    assert files(path) == before
    migrate_registry(path, CATALOG)
    after = files(path)
    assert migrate_registry(path, CATALOG).status == "no_op"
    assert files(path) == after


def test_a_refresh_needs_v2_and_changes_only_version_fields(tmp_path: Path) -> None:
    path = written(tmp_path, rich_v1())
    with pytest.raises(MigrationError) as caught:
        migrate_registry(path, CATALOG, refresh=True)
    assert caught.value.code == "MIGRATION_TARGET_INVALID"
    migrate_registry(path, CATALOG)
    ended = catalog(of("1828", end="2026-06-01", status="discontinued"), of("1814"))
    before = load_registry(path)
    assert migrate_registry(path, ended, refresh=True).status == "committed"
    after = load_registry(path)
    assert v1_projection(after) == v1_projection(before)
    version_after = after.products["1828"].version
    assert version_after is not None and version_after.sale_end == "2026-06-01"
    assert len(backups(path)) == 2


# 3. Failures and recovery ----------------------------------------------------------------------


def test_a_failure_before_the_replace_keeps_the_original_and_closes_the_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = written(tmp_path, rich_v1())
    original = path.read_bytes()

    def broken(source: object, target: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        migrate_registry(path, CATALOG)
    assert path.read_bytes() == original
    assert not journal(path).exists()
    assert [r["result"] for r in records(path)] == ["not_executed"]
    assert not list(tmp_path.glob(".registry.json.*.tmp"))
    assert len(backups(path)) == 1


def test_a_crash_before_the_journal_leaves_nothing_to_recover(tmp_path: Path) -> None:
    path = written(tmp_path, rich_v1())
    original = path.read_bytes()
    stray = path.with_name(path.name + ".backup-20261101T000000Z-stray.json")
    stray.write_bytes(original)  # a backup written before the process died
    report = migrate_registry(path, CATALOG)
    assert (report.status, report.recovered) == ("committed", None)
    assert stray.read_bytes() == original
    assert len(backups(path)) == 2  # the new backup never overwrites an existing one


@pytest.mark.parametrize("refresh", [False, True])
def test_a_crash_after_the_journal_and_before_the_replace_is_redone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refresh: bool
) -> None:
    path = written(tmp_path, rich_v1())
    if refresh:  # review R6: a refresh keeps the v1 projection, so only the journal can tell
        migrate_registry(path, CATALOG)
    target = catalog(of("1828", end="2026-06-01", status="discontinued"), of("1814"))
    before = path.read_bytes()

    def crash(source: object, target: object) -> None:
        raise Crash

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(Crash):
        migrate_registry(path, target, refresh=refresh)
    assert journal(path).exists() and path.read_bytes() == before
    monkeypatch.setattr(os, "replace", REAL_REPLACE)
    report = migrate_registry(path, target, refresh=refresh)
    assert (report.status, report.recovered) == ("committed", "not_executed")
    version_after = load_registry(path).products["1828"].version
    assert version_after is not None and version_after.sale_end == "2026-06-01"
    assert [r["result"] for r in records(path)][-2:] == ["not_executed", "committed"]
    assert not journal(path).exists()


def test_a_crash_after_the_replace_is_confirmed_not_redone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = written(tmp_path, rich_v1())

    def replace_then_crash(source: str, target: str) -> None:
        REAL_REPLACE(source, target)
        raise Crash

    monkeypatch.setattr(os, "replace", replace_then_crash)
    with pytest.raises(Crash):
        migrate_registry(path, CATALOG)
    assert journal(path).exists()
    committed = path.read_bytes()
    monkeypatch.setattr(os, "replace", REAL_REPLACE)
    report = migrate_registry(path, CATALOG)
    assert (report.status, report.recovered) == ("no_op", "committed")
    assert path.read_bytes() == committed
    assert len(backups(path)) == 1  # not migrated again
    assert [r["result"] for r in records(path)] == ["committed"]


def test_a_target_that_matches_neither_digest_stops_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = written(tmp_path, rich_v1())

    def crash(source: object, target: object) -> None:
        raise Crash

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(Crash):
        migrate_registry(path, CATALOG)
    monkeypatch.setattr(os, "replace", REAL_REPLACE)
    save_registry(registry(p1828=entry("1828", "terms")), path)  # changed by hand meanwhile
    before = files(path)
    with pytest.raises(MigrationError) as caught:
        migrate_registry(path, CATALOG)
    assert caught.value.code == "MIGRATION_RECOVERY_UNSAFE"
    assert files(path) == before
