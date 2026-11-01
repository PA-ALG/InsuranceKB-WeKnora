"""The filed versions of the product repository at one pinned commit (PV-1 Spec §2.1).

Each folder of the repository's on-sale and off-sale trees is one filed version, keyed
`planCode-versionNo`. The folders are untrusted input: every record is checked and the whole
catalog is refused when one is malformed or a version key repeats. A registry stores the catalog
it was built from beside itself, content-addressed and never rewritten, and names its digest.
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
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


def _git(directory: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise CatalogError("CATALOG_COMMIT_MISMATCH") from None
    if done.returncode != 0:
        raise CatalogError("CATALOG_COMMIT_MISMATCH")
    return done.stdout


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
    """The catalog of a clean checkout of the repository at exactly this commit."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise CatalogError("CATALOG_COMMIT_MISMATCH")
    if _git(directory, "rev-parse", "HEAD").strip() != commit:
        raise CatalogError("CATALOG_COMMIT_MISMATCH")
    if _git(directory, "status", "--porcelain", "--untracked-files=no").strip():
        raise CatalogError("CATALOG_DIRTY")
    pattern = load_attribution_policy().clause_code_pattern
    records = []
    for tree in _TREES:
        for path in sorted((directory / tree).glob("*/product_meta.json")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_META_BYTES:
                raise CatalogError("CATALOG_INVALID")
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
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


def load_catalog(registry_path: Path, digest: str) -> VersionCatalog:
    """The catalog a v2 registry names, refused unless its bytes have exactly that digest."""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CatalogError("CATALOG_INVALID")
    try:
        data = catalog_file(registry_path, digest).read_bytes()
    except OSError:
        raise CatalogError("CATALOG_INVALID") from None
    if hashlib.sha256(data).hexdigest() != digest:
        raise CatalogError("CATALOG_INVALID")
    try:
        return VersionCatalog.model_validate_json(data)
    except ValidationError:
        raise CatalogError("CATALOG_INVALID") from None
