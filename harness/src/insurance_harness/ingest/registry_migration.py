"""Migrate a registry to v2, or refresh its version fields, with a journal (PV-1 Spec §4).

Reading a registry never writes it; only this command does, under the registry lock. It backs up
the file (never overwriting a backup), writes the new content to a temporary file, then writes an
operation journal before the atomic replace, which is the commit point. A later run that finds the
journal open decides from the journal's digests alone what happened: the expected new content is
committed and only confirmed, the old content with its backup intact was never replaced and may be
done again, anything else stops without writing (PV-0 appendix A §4).
"""

import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from insurance_harness.identity.attribution import AttributionPolicy, load_attribution_policy
from insurance_harness.identity.versions import canonical_clause_code
from insurance_harness.ingest.product_versions import (
    MetadataBasis,
    ProductVersion,
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
from insurance_harness.ingest.version_catalog import VersionCatalog, save_catalog


class MigrationError(ValueError):
    """A caller-safe code; never a path or file content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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


def _now(now: datetime | None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    linked = predecessors(versions)
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
        synced_at=_now(now),
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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new(path: Path, data: bytes) -> None:
    """Create the file or fail: a backup or a journal is never overwritten."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_dir(path.parent)


def _journal(path: Path) -> Path:
    return path.with_name(path.name + ".migration-journal.json")


def _close(path: Path, entry: dict[str, Any], result: str) -> None:
    """Append the outcome to the migration records, then remove the open journal."""
    line = json.dumps(entry | {"result": result, "closed_at": _now(None)}, ensure_ascii=False)
    with path.with_name(path.name + ".migrations.jsonl").open("ab") as records:
        records.write(line.encode("utf-8") + b"\n")
        records.flush()
        os.fsync(records.fileno())
    _journal(path).unlink(missing_ok=True)
    _fsync_dir(path.parent)


def _confirm(path: Path, entry: dict[str, Any]) -> None:
    """Read the committed file back; the journal stays open if it does not check out."""
    data = path.read_bytes()
    try:
        current = load_registry(path)
        backup = load_registry(path.with_name(entry["backup_file"]))
    except RegistryError:
        raise MigrationError("MIGRATION_READBACK_FAILED") from None
    if _sha(data) != entry["new_sha256"] or current.contract != V2:
        raise MigrationError("MIGRATION_READBACK_FAILED")
    if _v1_view(current) != _v1_view(backup):
        raise MigrationError("MIGRATION_READBACK_FAILED")
    _close(path, entry, "committed")


def _recover(path: Path) -> Literal["committed", "not_executed"]:
    """Settle an open journal from its digests alone; anything unexpected stops without writing."""
    try:
        entry = json.loads(_journal(path).read_text(encoding="utf-8"))
        current = _sha(path.read_bytes())
        backup = path.with_name(entry["backup_file"])
        backup_sha = _sha(backup.read_bytes()) if backup.is_file() else None
    except (OSError, ValueError, KeyError, TypeError):
        raise MigrationError("MIGRATION_RECOVERY_UNSAFE") from None
    if current == entry["new_sha256"]:
        _confirm(path, entry)
        return "committed"
    if current == entry["old_sha256"] and backup_sha == entry["backup_sha256"]:
        path.with_name(entry["temp_file"]).unlink(missing_ok=True)
        _close(path, entry, "not_executed")
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
    if _journal(path).exists():
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
    backup = path.with_name(f"{path.name}.backup-{_now(now).replace(':', '')}-{operation}.json")
    _write_new(backup, old)
    save_catalog(catalog, path)
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    with handle:
        handle.write(new)
        handle.flush()
        os.fsync(handle.fileno())
    temp = Path(handle.name)
    entry = {
        "operation": operation,
        "kind": "refresh" if refresh else "migrate",
        "old_sha256": _sha(old),
        "new_sha256": _sha(new),
        "backup_file": backup.name,
        "backup_sha256": _sha(old),
        "temp_file": temp.name,
        "manifest_commit": catalog.commit,
        "catalog_sha256": catalog.digest(),
        "started_at": _now(now),
    }
    try:
        _write_new(_journal(path), json.dumps(entry, ensure_ascii=False).encode("utf-8"))
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    try:
        os.replace(temp, path)  # the commit point
    except Exception:  # a crash (BaseException) leaves the journal open for recovery
        temp.unlink(missing_ok=True)
        _close(path, entry, "not_executed")
        raise
    _fsync_dir(path.parent)
    _confirm(path, entry)
    return MigrationReport(
        status="committed", recovered=recovered, entries=entries, retired=retired
    )
