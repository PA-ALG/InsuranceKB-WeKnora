"""The files a registry migration writes before its commit point (PV-1 Spec §4; review R3, R4).

Every file is created exclusively, written completely (a short write is continued), synced and
read back against its digest before the migration may replace the registry; a failed attempt
removes the partial file it created. The operation journal is a strict record: a malformed one is
a typed error, never a guess, and its file names must be the registry's own siblings.
"""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_SHA = r"^[0-9a-f]{64}$"


class MigrationError(ValueError):
    """A caller-safe code; never a path or file content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Journal(BaseModel):
    """What one operation is about to commit, written and synced before the atomic replace."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    operation: str = Field(pattern=r"^[0-9a-f]{12}$")
    kind: Literal["migrate", "refresh"]
    old_sha256: str = Field(pattern=_SHA)
    new_sha256: str = Field(pattern=_SHA)
    backup_file: str = Field(pattern=r"^[^/\\\x00]+$")
    backup_sha256: str = Field(pattern=_SHA)
    temp_file: str = Field(pattern=r"^[^/\\\x00]+$")
    manifest_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    catalog_sha256: str = Field(pattern=_SHA)
    started_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def now_text(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fsync_dir(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("no progress writing")
        view = view[written:]


def write_new(path: Path, data: bytes) -> None:
    """Create the file (never overwriting one), write it completely, sync it and check it reads
    back with the same digest. On an ordinary failure the partial file is removed."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        try:
            _write_all(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if sha(path.read_bytes()) != sha(data):
            raise MigrationError("MIGRATION_WRITE_FAILED")
        fsync_dir(path.parent)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    found: dict[str, object] = {}
    for key, value in pairs:
        if key in found:
            raise ValueError("a repeated journal key")
        found[key] = value
    return found


def journal_path(path: Path) -> Path:
    return path.with_name(path.name + ".migration-journal.json")


def read_journal(path: Path) -> Journal:
    """The open journal of this registry; anything malformed or naming another file is refused."""
    try:  # a repeated key is refused, never resolved to its last value (review R3)
        data = json.loads(journal_path(path).read_bytes(), object_pairs_hook=_unique)
        journal = Journal.model_validate(data)
    except (OSError, ValidationError, ValueError, RecursionError):
        raise MigrationError("MIGRATION_JOURNAL_INVALID") from None
    backup, temp = journal.backup_file, journal.temp_file
    if not (backup.startswith(f"{path.name}.backup-") and backup.endswith(".json")) or not (
        temp.startswith(f".{path.name}.") and temp.endswith(".tmp")
    ):
        raise MigrationError("MIGRATION_JOURNAL_INVALID")
    return journal


def file_digest(path: Path) -> str | None:
    """The digest of a regular file that is not a symlink, else None."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return sha(path.read_bytes())
    except OSError:
        return None


def close_journal(path: Path, journal: Journal, result: str) -> None:
    """Append the outcome to the migration records, then remove the open journal."""
    line = json.dumps(journal.model_dump() | {"result": result, "closed_at": now_text()})
    with path.with_name(path.name + ".migrations.jsonl").open("ab") as records:
        records.write(line.encode("utf-8") + b"\n")
        records.flush()
        os.fsync(records.fileno())
    journal_path(path).unlink(missing_ok=True)
    fsync_dir(path.parent)
