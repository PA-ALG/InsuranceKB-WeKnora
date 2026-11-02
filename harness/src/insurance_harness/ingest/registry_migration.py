"""Migrate a registry to v2, or refresh its version fields, with a journal (PV-1 Spec §4).

Reading a registry never writes it; only this command does, under the registry lock. It backs up
the file (never overwriting a backup), writes the new content to a temporary file, then writes an
operation journal before the atomic replace, which is the commit point. A later run that finds the
journal open decides from the journal's digests alone what happened: the expected new content is
committed and only confirmed, the old content with its backup intact was never replaced and may be
done again, anything else stops without writing (PV-0 appendix A §4).
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from insurance_harness.identity.attribution import AttributionPolicy, load_attribution_policy
from insurance_harness.identity.versions import canonical_clause_code
from insurance_harness.ingest.migration_journal import (
    Journal,
    MigrationError,
    close_journal,
    file_digest,
    fsync_dir,
    journal_path,
    now_text,
    read_journal,
    sha,
    write_new,
)
from insurance_harness.ingest.product_versions import (
    MetadataBasis,
    ProductVersion,
    line_of,
    predecessors,
    same_name,
    version_of,
)
from insurance_harness.ingest.registry import (
    CONTRACT,
    V2,
    ProductRegistry,
    RegistryError,
    load_registry,
    registry_document,
)
from insurance_harness.ingest.registry_lock import RegistryBusy, RegistryLock
from insurance_harness.ingest.version_catalog import (
    CatalogError,
    VersionCatalog,
    catalog_from_checkout,
    save_catalog,
)

__all__ = [
    "EntryMatch",
    "MigrationError",
    "MigrationReport",
    "migrate_command",
    "migrate_registry",
    "plan_migration",
]


class EntryMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str
    outcome: Literal["matched", "unmatched", "ambiguous"]
    version_key: str | None
    predecessor: str | None
    name_differs: bool


class MigrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["no_op", "dry_run", "committed"]
    recovered: Literal["committed", "not_executed"] | None
    entries: list[EntryMatch]
    retired: list[str]  # entries whose retired materials the v2 format keeps as they are


def plan_migration(
    registry: ProductRegistry,
    catalog: VersionCatalog,
    *,
    refresh: bool = False,
    now: datetime | None = None,
    policy: AttributionPolicy | None = None,
) -> tuple[ProductRegistry, list[EntryMatch]]:
    """The v2 registry (version fields from the catalog, everything else as it was) and a match
    per entry. A refresh recomputes the version fields of a v2 registry."""
    if registry.contract != (V2 if refresh else CONTRACT):
        raise MigrationError("MIGRATION_TARGET_INVALID")
    policy = policy or load_attribution_policy()
    versions: dict[str, ProductVersion] = {}
    matches: dict[str, tuple[str, str | None, bool]] = {}
    for product_id, product in sorted(registry.products.items()):
        codes = {canonical_clause_code(c, policy.clause_code_pattern) for c in product.clause_codes}
        found = [catalog.keys_for(code) for code in codes if code is not None]
        keys = {key for group in found for key in group}
        ambiguous = any(len(group) > 1 for group in found) or len(keys) > 1
        record = catalog.get(keys.pop()) if len(keys) == 1 and not ambiguous else None
        versions[product_id] = version_of(record, product.names[0], policy, ambiguous=ambiguous)
        outcome = "ambiguous" if ambiguous else "matched" if record else "unmatched"
        differs = record is not None and not same_name(record.name, product.names[0])
        matches[product_id] = (outcome, record.version_key if record else None, differs)
    taken = [v.version_key for v in versions.values() if v.version_key]
    if len(set(taken)) != len(taken):
        raise MigrationError("MIGRATION_VERSION_DUPLICATE")
    lines = {pid: line_of(product.names[0], policy) for pid, product in registry.products.items()}
    linked = predecessors(versions, lines)
    planned = registry.model_copy(deep=True)
    for product_id, product in planned.products.items():
        update = {"predecessor": linked[product_id]}
        product.version = versions[product_id].model_copy(update=update)
    planned.contract = V2
    old = registry.metadata_basis
    unchanged = refresh and old is not None and old.catalog_sha256 == catalog.digest() and all(
        planned.products[pid].version == registry.products[pid].version for pid in planned.products
    )
    planned.metadata_basis = old if unchanged else MetadataBasis(
        repository=catalog.repository,
        commit=catalog.commit,
        catalog_sha256=catalog.digest(),
        synced_at=now_text(now),
    )
    try:
        planned = ProductRegistry.model_validate(planned.model_dump())
    except ValueError:
        raise MigrationError("MIGRATION_RESULT_INVALID") from None
    report = [
        EntryMatch(
            product_id=pid,
            outcome=outcome,  # type: ignore[arg-type]
            version_key=key,
            predecessor=linked[pid],
            name_differs=differs,
        )
        for pid, (outcome, key, differs) in matches.items()
    ]
    return planned, report


def _v1_view(registry: ProductRegistry) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(registry.model_dump_json())
    data.update(contract=CONTRACT, metadata_basis=None)
    for product in data["products"].values():
        product["version"] = None
    return data


def _confirm(path: Path, journal: Journal) -> None:
    """Read the committed file back against the journal and its backup; the journal stays open
    when anything does not check out (review R3)."""
    backup = path.with_name(journal.backup_file)
    if file_digest(backup) != journal.backup_sha256 or file_digest(path) != journal.new_sha256:
        raise MigrationError("MIGRATION_READBACK_FAILED")
    try:
        current, before = load_registry(path), load_registry(backup)
    except RegistryError:
        raise MigrationError("MIGRATION_READBACK_FAILED") from None
    if current.contract != V2 or _v1_view(current) != _v1_view(before):
        raise MigrationError("MIGRATION_READBACK_FAILED")
    close_journal(path, journal, "committed")


def _recover(path: Path) -> Literal["committed", "not_executed"]:
    """Settle an open journal from its digests alone: the backup it names must be intact in either
    branch; anything else stops without writing (PV-0 appendix A §4)."""
    journal = read_journal(path)
    current = file_digest(path)
    if file_digest(path.with_name(journal.backup_file)) != journal.backup_sha256:
        raise MigrationError("MIGRATION_RECOVERY_UNSAFE")
    if current == journal.new_sha256:
        try:
            _confirm(path, journal)
        except MigrationError:
            raise MigrationError("MIGRATION_RECOVERY_UNSAFE") from None
        return "committed"
    if current == journal.old_sha256:
        path.with_name(journal.temp_file).unlink(missing_ok=True)
        close_journal(path, journal, "not_executed")
        return "not_executed"
    raise MigrationError("MIGRATION_RECOVERY_UNSAFE")


def migrate_registry(
    path: Path,
    catalog: VersionCatalog,
    *,
    refresh: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> MigrationReport:
    """Migrate (or refresh) the registry file; the caller holds the registry lock."""
    recovered = None
    if journal_path(path).exists():
        if dry_run:
            raise MigrationError("MIGRATION_JOURNAL_OPEN")
        recovered = _recover(path)
    try:
        current = load_registry(path)
    except RegistryError:
        raise MigrationError("MIGRATION_TARGET_INVALID") from None
    retired = sorted(pid for pid, p in current.products.items() if p.retired)
    if not refresh and current.contract == V2:
        return MigrationReport(status="no_op", recovered=recovered, entries=[], retired=retired)
    planned, entries = plan_migration(current, catalog, refresh=refresh, now=now)
    if planned == current or dry_run:
        status: Literal["no_op", "dry_run"] = "no_op" if planned == current else "dry_run"
        return MigrationReport(status=status, recovered=recovered, entries=entries, retired=retired)
    old, new = path.read_bytes(), registry_document(planned)
    operation = uuid.uuid4().hex[:12]
    journal = Journal(
        operation=operation,
        kind="refresh" if refresh else "migrate",
        old_sha256=sha(old),
        new_sha256=sha(new),
        backup_file=f"{path.name}.backup-{now_text(now).replace(':', '')}-{operation}.json",
        backup_sha256=sha(old),
        temp_file=f".{path.name}.{operation}.tmp",
        manifest_commit=catalog.commit,
        catalog_sha256=catalog.digest(),
        started_at=now_text(now),
    )
    temp = path.with_name(journal.temp_file)
    write_new(path.with_name(journal.backup_file), old)  # each write is complete and verified
    save_catalog(catalog, path)
    write_new(temp, new)
    try:
        write_new(journal_path(path), journal.model_dump_json().encode("utf-8"))
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    try:
        os.replace(temp, path)  # the commit point
    except Exception:  # a crash (BaseException) leaves the journal open for recovery
        temp.unlink(missing_ok=True)
        close_journal(path, journal, "not_executed")
        raise
    fsync_dir(path.parent)
    _confirm(path, journal)
    return MigrationReport(
        status="committed", recovered=recovered, entries=entries, retired=retired
    )


def migrate_command(args: argparse.Namespace) -> int:
    """`migrate-registry`: the registry lock, the pinned catalog, then the journaled migration."""
    try:
        with RegistryLock(args.registry):
            catalog = catalog_from_checkout(args.manifest_dir, args.manifest_commit)
            report = migrate_registry(
                args.registry, catalog, refresh=args.refresh, dry_run=args.dry_run
            )
    except RegistryBusy:
        print("REGISTRY_BUSY", file=sys.stderr)
        return 3
    except (CatalogError, MigrationError, RegistryError) as error:
        print(error.code, file=sys.stderr)
        return 1
    except OSError:
        print("REGISTRY_IO_ERROR", file=sys.stderr)
        return 1
    print(report.model_dump_json())
    return 0
