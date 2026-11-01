"""The filed versions of the product repository at one pinned commit (PV-1 Spec §2.1).

Each folder of the repository's on-sale and off-sale trees is one filed version, keyed
`planCode-versionNo`. The records are read from the commit's own tree objects, never from the
working tree, so untracked, ignored or edited files cannot enter a catalog that names the commit;
a tracked symlink is refused. The folders are untrusted input: every record is checked (a repeated
JSON key included) and the whole catalog is refused when one is malformed or a version key repeats.
A registry stores the catalog beside itself, content-addressed and never rewritten, and names its
digest, repository and commit; reading it back checks all three (review R2 on #505).
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.identity.attribution import load_attribution_policy
from insurance_harness.identity.versions import canonical_clause_code

CONTRACT: Literal["product-catalog.v1"] = "product-catalog.v1"
REPOSITORY = "PA-ALG/pingan-life-product-documents"
_TREES = ("在售", "停售")
_STATUSES = {"在售": "on_sale", "停售": "discontinued"}
_MAX_META_BYTES = 256 * 1024
_VERSION_NO = re.compile(r"^([A-Za-z0-9]{1,32})-([0-9]{1,4})$")
_META_PATH = re.compile(r"^(在售|停售)/[^/]+/product_meta\.json$")
_REGULAR = {"100644", "100755"}
_OID = re.compile(r"^[0-9a-f]{40}$")
_OFFLINE = {"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}  # never reach the network
DateText = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
_Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class CatalogError(ValueError):
    """A caller-safe code; never a path or file content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class VersionRecord(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version_key: str = Field(pattern=r"^[A-Za-z0-9]{1,32}-[0-9]{1,4}$")
    plan_code: str = Field(pattern=r"^[A-Za-z0-9]{1,32}$")
    version_no: int = Field(ge=1)
    name: str = Field(min_length=1)
    clause_code: str | None
    sale_start: DateText | None
    sale_end: DateText | None
    source_status: Literal["on_sale", "discontinued"] | None
    channel: str | None
    plan_type: str | None

    @model_validator(mode="after")
    def _consistent(self) -> "VersionRecord":
        if self.version_key != f"{self.plan_code}-{self.version_no}":
            raise ValueError("a version key that is not its plan code and number")
        dates = [d for d in (self.sale_start, self.sale_end) if d is not None]
        for text in dates:
            date.fromisoformat(text)
        if self.sale_start and self.sale_end and self.sale_start >= self.sale_end:
            raise ValueError("a sale period that ends before it starts")
        return self


class VersionCatalog(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    contract: Literal["product-catalog.v1"]
    repository: str = Field(min_length=1)
    commit: _Commit
    versions: tuple[VersionRecord, ...]
    _by_code: dict[str, tuple[str, ...]] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _unique(self) -> "VersionCatalog":
        keys = [v.version_key for v in self.versions]
        if len(set(keys)) != len(keys):
            raise ValueError("a version key repeats")
        found: dict[str, list[str]] = {}
        for version in self.versions:
            if version.clause_code is not None:
                found.setdefault(version.clause_code, []).append(version.version_key)
        self._by_code = {code: tuple(sorted(keys)) for code, keys in found.items()}
        return self

    def keys_for(self, clause_code: str) -> tuple[str, ...]:
        """The versions that print this canonical clause code; more than one means it is shared."""
        return self._by_code.get(clause_code, ())

    def get(self, version_key: str) -> VersionRecord | None:
        return next((v for v in self.versions if v.version_key == version_key), None)

    def document(self) -> bytes:
        return self.model_dump_json(indent=1).encode("utf-8") + b"\n"

    def digest(self) -> str:
        return hashlib.sha256(self.document()).hexdigest()


def catalog_file(registry_path: Path, digest: str) -> Path:
    return registry_path.with_name(f"{registry_path.name}.catalog-{digest[:12]}.json")


def _git(directory: Path, *args: str, stdin: bytes | None = None) -> bytes:
    try:
        done = subprocess.run(
            ["git", "-C", str(directory), *args],
            input=stdin, capture_output=True, timeout=300, check=False, env=os.environ | _OFFLINE,
        )
    except (OSError, subprocess.SubprocessError):
        raise CatalogError("CATALOG_COMMIT_MISMATCH") from None
    if done.returncode != 0:
        raise CatalogError("CATALOG_COMMIT_MISMATCH")
    return done.stdout


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise CatalogError("CATALOG_INVALID")  # json.loads would keep only the last one
        found[key] = value
    return found


def _tracked(directory: Path, commit: str) -> list[tuple[str, str]]:
    """(tree, blob) of every product_meta.json in the commit's on-sale and off-sale trees."""
    listing = _git(directory, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *_TREES)
    found = []
    for line in filter(None, listing.split(b"\0")):
        header, tab, raw = line.partition(b"\t")
        try:  # git allows any bytes in a name; one that is not UTF-8 refuses the catalog
            mode, kind, blob = header.decode("ascii").split(" ")
            path = raw.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            raise CatalogError("CATALOG_INVALID") from None
        if not tab or not _OID.fullmatch(blob):
            raise CatalogError("CATALOG_INVALID")
        if not path.endswith("/product_meta.json"):
            continue
        if not _META_PATH.fullmatch(path) or mode not in _REGULAR or kind != "blob":
            raise CatalogError("CATALOG_INVALID")  # a symlink, or a file deeper in the tree
        found.append((path.split("/", 1)[0], blob))
    return found


def _blobs(directory: Path, blobs: list[str]) -> list[bytes]:
    """The blobs' content from the object store, in order. One object at a time: its header is
    checked (a missing, non-blob or oversized object refuses the catalog) before its body is read,
    so no read is larger than the size limit."""
    try:
        process = subprocess.Popen(
            ["git", "-C", str(directory), "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=os.environ | _OFFLINE,
        )
    except OSError:
        raise CatalogError("CATALOG_COMMIT_MISMATCH") from None
    assert process.stdin is not None and process.stdout is not None
    watchdog = threading.Timer(300, process.kill)
    watchdog.start()
    try:
        contents = []
        for blob in blobs:
            process.stdin.write(f"{blob}\n".encode("ascii"))
            process.stdin.flush()
            header = process.stdout.readline(128)
            parts = header.removesuffix(b"\n").split(b" ")
            if (
                not header.endswith(b"\n")
                or len(parts) != 3
                or parts[:2] != [blob.encode("ascii"), b"blob"]
                or not parts[2].isdigit()
                or int(parts[2]) > _MAX_META_BYTES
            ):
                raise CatalogError("CATALOG_INVALID")  # missing, not a blob, malformed or too big
            body = process.stdout.read(int(parts[2]) + 1)
            if len(body) != int(parts[2]) + 1 or not body.endswith(b"\n"):
                raise CatalogError("CATALOG_INVALID")  # truncated
            contents.append(body[:-1])
        return contents
    except OSError:
        raise CatalogError("CATALOG_INVALID") from None
    finally:
        watchdog.cancel()
        process.kill()
        process.wait()
        process.stdin.close()
        process.stdout.close()


def _text(meta: dict[str, Any], key: str) -> str | None:
    value = meta.get(key)
    if value is not None and not isinstance(value, str):
        raise CatalogError("CATALOG_INVALID")
    value = (value or "").strip()
    return value or None


def _record(meta: dict[str, Any], tree: str, pattern: str) -> VersionRecord:
    plan = _text(meta, "actualPlanCode")
    found = _VERSION_NO.fullmatch(_text(meta, "versionNo") or "")
    if plan is None or found is None or found.group(1) != plan:
        raise CatalogError("CATALOG_INVALID")
    code = _text(meta, "sccode")
    status = _STATUSES.get(_text(meta, "planSalesStatus") or "")
    if status is not None and status != _STATUSES[tree]:
        raise CatalogError("CATALOG_INVALID")  # a folder in the other tree
    try:
        return VersionRecord(
            version_key=found.group(0),
            plan_code=plan,
            version_no=int(found.group(2)),
            name=_text(meta, "clauseName") or "",
            clause_code=canonical_clause_code(code, pattern) if code else None,
            sale_start=_text(meta, "startDate"),
            sale_end=_text(meta, "endDate"),
            source_status=status,  # type: ignore[arg-type]
            channel=_text(meta, "planSalesChannel"),
            plan_type=_text(meta, "planPlanType"),
        )
    except ValidationError:
        raise CatalogError("CATALOG_INVALID") from None


def catalog_from_checkout(directory: Path, commit: str) -> VersionCatalog:
    """The catalog of exactly this commit of the repository cloned at `directory`, read from its
    object store (the working tree may be sparse, dirty or hold untracked files)."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise CatalogError("CATALOG_COMMIT_MISMATCH")
    resolved = _git(directory, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
    if resolved.decode("ascii", "replace").strip() != commit:
        raise CatalogError("CATALOG_COMMIT_MISMATCH")
    pattern = load_attribution_policy().clause_code_pattern
    tracked = _tracked(directory, commit)
    records = []
    for (tree, _), content in zip(tracked, _blobs(directory, [b for _, b in tracked]), strict=True):
        try:
            meta = json.loads(content.decode("utf-8"), object_pairs_hook=_unique)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise CatalogError("CATALOG_INVALID") from None
        if not isinstance(meta, dict):
            raise CatalogError("CATALOG_INVALID")
        records.append(_record(meta, tree, pattern))
    if not records:
        raise CatalogError("CATALOG_INVALID")
    try:
        return VersionCatalog(
            contract=CONTRACT,
            repository=REPOSITORY,
            commit=commit,
            versions=tuple(sorted(records, key=lambda r: (r.plan_code, r.version_no))),
        )
    except ValidationError:
        raise CatalogError("CATALOG_INVALID") from None


def save_catalog(catalog: VersionCatalog, registry_path: Path) -> tuple[str, str]:
    """Write the catalog beside the registry once: (file name, digest). An existing file of that
    name must hold exactly this catalog; it is never rewritten."""
    data, digest = catalog.document(), catalog.digest()
    target = catalog_file(registry_path, digest)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise CatalogError("CATALOG_INVALID")
        return target.name, digest
    handle = tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(handle.name, target)  # fails if another run wrote it meanwhile: never replaced
    finally:
        Path(handle.name).unlink(missing_ok=True)
    return target.name, digest


def load_catalog(
    registry_path: Path,
    digest: str,
    *,
    repository: str | None = None,
    commit: str | None = None,
) -> VersionCatalog:
    """The catalog a v2 registry names, refused unless its bytes have exactly that digest and it
    comes from the repository and commit the registry's basis names (when given)."""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CatalogError("CATALOG_INVALID")
    try:
        data = catalog_file(registry_path, digest).read_bytes()
    except OSError:
        raise CatalogError("CATALOG_INVALID") from None
    if hashlib.sha256(data).hexdigest() != digest:
        raise CatalogError("CATALOG_INVALID")
    try:
        catalog = VersionCatalog.model_validate_json(data)
    except ValidationError:
        raise CatalogError("CATALOG_INVALID") from None
    if (repository is not None and catalog.repository != repository) or (
        commit is not None and catalog.commit != commit
    ):
        raise CatalogError("CATALOG_INVALID")
    return catalog
