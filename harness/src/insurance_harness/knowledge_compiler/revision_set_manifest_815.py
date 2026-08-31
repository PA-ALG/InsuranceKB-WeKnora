"""Deterministic exact-read validator for the EC-01 RevisionSet manifest."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, NoReturn, cast

import pdfplumber

_ROLES: Final[tuple[str, ...]] = ("terms", "brochure", "rate_table")
_FILES: Final[dict[str, tuple[str, str]]] = {
    "terms": ("terms.manifest.json", "terms.pdf"),
    "brochure": ("brochure.manifest.json", "brochure.pdf"),
    "rate_table": ("rate_table.manifest.json", "rate_table.pdf"),
}
_SET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "canonicalization",
        "compiler_source_identity",
        "contract",
        "created_at",
        "items",
        "knowledge_base_id",
        "ordered_roles",
        "revision_set_sha256",
        "runtime_identity",
        "source_effects",
        "tenant_id",
    }
)
_SUMMARY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "manifest_file",
        "manifest_file_sha256",
        "manifest_self_sha256",
        "material_file",
        "material_file_sha256",
        "role",
    }
)
_ITEM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "chunk_count",
        "compiler_source_revision_id",
        "contract",
        "file_name",
        "file_sha256",
        "file_size",
        "knowledge_base_id",
        "knowledge_id",
        "manifest_self_sha256",
        "material_file",
        "mime_type",
        "ordered_chunk_projection",
        "page_count",
        "parse_completed_at",
        "parse_identity",
        "parse_manifest_algorithm",
        "parse_manifest_sha256",
        "parse_status",
        "resource_binding_count",
        "resource_id",
        "resource_physical_path",
        "resource_state",
        "role",
        "tenant_id",
        "weknora_parse_attempt",
    }
)
_PARSE_IDENTITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "app_commit",
        "app_version",
        "chunk_overlap",
        "chunk_size",
        "chunker_config_digest",
        "docreader",
        "embedding_model_id",
        "parser_engine",
        "separators_digest",
    }
)
_CHUNK_KEYS: Final[frozenset[str]] = frozenset(
    {"chunk_id", "chunk_index", "content_sha256"}
)
_SHA256_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")
_VALIDATION_CONTRACT: Final[str] = "revision-set-validation.815.v1"
_VALIDATION_ROW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "compiler_source_revision_id",
        "compiler_source_revision_id_match",
        "file_sha256",
        "file_sha256_match",
        "file_size",
        "file_size_match",
        "knowledge_id",
        "page_count",
        "page_count_match",
        "parse_manifest_sha256",
        "parse_manifest_sha256_match",
        "role",
        "weknora_parse_attempt",
    }
)


class RevisionSetValidationError(ValueError):
    """Typed rejection from the ordinary RevisionSet validator."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RevisionSetItemValidation815V1:
    role: str
    knowledge_id: str
    weknora_parse_attempt: int
    file_size: int
    file_sha256: str
    page_count: int
    parse_manifest_sha256: str
    compiler_source_revision_id: str
    file_size_match: bool
    file_sha256_match: bool
    page_count_match: bool
    parse_manifest_sha256_match: bool
    compiler_source_revision_id_match: bool

    def to_wire(self) -> dict[str, object]:
        return {
            "compiler_source_revision_id": self.compiler_source_revision_id,
            "compiler_source_revision_id_match": (
                self.compiler_source_revision_id_match
            ),
            "file_sha256": self.file_sha256,
            "file_sha256_match": self.file_sha256_match,
            "file_size": self.file_size,
            "file_size_match": self.file_size_match,
            "knowledge_id": self.knowledge_id,
            "page_count": self.page_count,
            "page_count_match": self.page_count_match,
            "parse_manifest_sha256": self.parse_manifest_sha256,
            "parse_manifest_sha256_match": self.parse_manifest_sha256_match,
            "role": self.role,
            "weknora_parse_attempt": self.weknora_parse_attempt,
        }


@dataclass(frozen=True)
class RevisionSetValidation815V1:
    contract: Literal["revision-set-validation.815.v1"]
    status: Literal["PASS"]
    ordered_roles: tuple[str, ...]
    rows: tuple[RevisionSetItemValidation815V1, ...]
    materials_reopened: int
    parse_manifests_recomputed: int
    source_revision_ids_recomputed: int
    revision_set_external_sha256: str
    revision_set_sha256: str
    provider_calls: Literal[0]
    validation_sha256: str

    def to_wire(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "materials_reopened": self.materials_reopened,
            "ordered_roles": list(self.ordered_roles),
            "parse_manifests_recomputed": self.parse_manifests_recomputed,
            "provider_calls": self.provider_calls,
            "revision_set_external_sha256": self.revision_set_external_sha256,
            "revision_set_sha256": self.revision_set_sha256,
            "rows": [row.to_wire() for row in self.rows],
            "source_revision_ids_recomputed": self.source_revision_ids_recomputed,
            "status": self.status,
            "validation_sha256": self.validation_sha256,
        }


def _reject(reason: str) -> NoReturn:
    raise RevisionSetValidationError(reason)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _domain_hash(domain: str, value: dict[str, object], self_key: str) -> str:
    unsigned = dict(value)
    unsigned.pop(self_key, None)
    return _sha256(domain.encode("ascii") + b"\0" + _canonical_bytes(unsigned))


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and frozenset(value) <= _SHA256_CHARS
    )


def _require_string(value: object, reason: str) -> str:
    if type(value) is not str or not value:
        _reject(reason)
    return value


def _require_integer(value: object, reason: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        _reject(reason)
    return value


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_nlink,
        left.st_uid,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_nlink,
        right.st_uid,
        right.st_size,
        right.st_mtime_ns,
    )


def _read_exact_file(root_fd: int, name: str) -> bytes:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        _reject("REVISION_SET_PATH_INVALID")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=root_fd)
    except OSError:
        _reject("REVISION_SET_FILE_NOT_READY")
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
        ):
            _reject("REVISION_SET_FILE_METADATA_INVALID")
        chunks: list[bytes] = []
        while block := os.read(descriptor, 1024 * 1024):
            chunks.append(block)
        after = os.fstat(descriptor)
        if not _same_file_identity(before, after):
            _reject("REVISION_SET_FILE_CHANGED")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _decode_canonical_json(payload: bytes, reason: str) -> dict[str, object]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _reject(reason)
    if type(decoded) is not dict or payload != _canonical_bytes(decoded) + b"\n":
        _reject(reason)
    return cast(dict[str, object], decoded)


def _pdf_page_count(payload: bytes) -> int:
    try:
        with pdfplumber.open(io.BytesIO(payload)) as document:
            pages = len(document.pages)
    except Exception:
        _reject("REVISION_SET_PDF_INVALID")
    if pages <= 0:
        _reject("REVISION_SET_PDF_INVALID")
    return pages


def _parse_manifest_sha256(item: dict[str, object]) -> str:
    entries = item.get("ordered_chunk_projection")
    chunk_count = _require_integer(item.get("chunk_count"), "REVISION_SET_ITEM_INVALID")
    if type(entries) is not list or len(entries) != chunk_count:
        _reject("REVISION_SET_PARSE_MANIFEST_INVALID")
    knowledge_id = _require_string(
        item.get("knowledge_id"), "REVISION_SET_ITEM_INVALID"
    )
    parse_attempt = _require_integer(
        item.get("weknora_parse_attempt"), "REVISION_SET_ITEM_INVALID"
    )
    parts = [
        "weknora.chunk_manifest\n",
        "v1\n",
        knowledge_id,
        "\n",
        str(parse_attempt),
        "\n",
        str(len(entries)),
        "\n",
    ]
    previous = -1
    for value in entries:
        if type(value) is not dict or frozenset(value) != _CHUNK_KEYS:
            _reject("REVISION_SET_PARSE_MANIFEST_INVALID")
        entry = cast(dict[str, object], value)
        index = _require_integer(
            entry.get("chunk_index"),
            "REVISION_SET_PARSE_MANIFEST_INVALID",
            minimum=0,
        )
        chunk_id = _require_string(
            entry.get("chunk_id"), "REVISION_SET_PARSE_MANIFEST_INVALID"
        )
        content_sha256 = entry.get("content_sha256")
        if index <= previous or not _is_sha256(content_sha256):
            _reject("REVISION_SET_PARSE_MANIFEST_INVALID")
        previous = index
        parts.extend(
            (str(index), ":", chunk_id, ":", cast(str, content_sha256), "\n")
        )
    return _sha256("".join(parts).encode("utf-8"))


def _compiler_source_revision_id(item: dict[str, object]) -> str:
    fields = (
        str(_require_integer(item.get("tenant_id"), "REVISION_SET_ITEM_INVALID")),
        _require_string(item.get("knowledge_id"), "REVISION_SET_ITEM_INVALID"),
        str(
            _require_integer(
                item.get("weknora_parse_attempt"), "REVISION_SET_ITEM_INVALID"
            )
        ),
        _require_string(item.get("resource_id"), "REVISION_SET_ITEM_INVALID"),
        _require_string(item.get("file_sha256"), "REVISION_SET_ITEM_INVALID"),
        str(_require_integer(item.get("file_size"), "REVISION_SET_ITEM_INVALID")),
        _require_string(item.get("mime_type"), "REVISION_SET_ITEM_INVALID"),
    )
    pieces = ["knowledge-revision-source-id.v1", "\n", str(len(fields)), "\n"]
    for value in fields:
        pieces.extend((str(len(value.encode("utf-8"))), ":", value, "\n"))
    return _sha256("".join(pieces).encode("utf-8"))


def _validate_item_shape(
    item: dict[str, object],
    *,
    role: str,
    tenant_id: int,
    knowledge_base_id: str,
) -> None:
    parse_identity = item.get("parse_identity")
    if (
        frozenset(item) != _ITEM_KEYS
        or item.get("contract") != "weknora.ec.revision-item.v1"
        or item.get("role") != role
        or item.get("tenant_id") != tenant_id
        or item.get("knowledge_base_id") != knowledge_base_id
        or item.get("parse_status") != "completed"
        or item.get("parse_manifest_algorithm") != "weknora.chunk_manifest.v1"
        or item.get("mime_type") != "application/pdf"
        or item.get("resource_state") != "active"
        or item.get("resource_binding_count") != 1
        or type(parse_identity) is not dict
        or frozenset(parse_identity) != _PARSE_IDENTITY_KEYS
    ):
        _reject("REVISION_SET_ITEM_INVALID")
    for key in (
        "file_sha256",
        "manifest_self_sha256",
        "parse_manifest_sha256",
        "compiler_source_revision_id",
    ):
        if not _is_sha256(item.get(key)):
            _reject("REVISION_SET_ITEM_INVALID")


def _result_payload_without_hash(
    *,
    rows: tuple[RevisionSetItemValidation815V1, ...],
    revision_set_external_sha256: str,
    revision_set_sha256: str,
) -> dict[str, object]:
    return {
        "contract": _VALIDATION_CONTRACT,
        "materials_reopened": 3,
        "ordered_roles": list(_ROLES),
        "parse_manifests_recomputed": 3,
        "provider_calls": 0,
        "revision_set_external_sha256": revision_set_external_sha256,
        "revision_set_sha256": revision_set_sha256,
        "rows": [row.to_wire() for row in rows],
        "source_revision_ids_recomputed": 3,
        "status": "PASS",
    }


def _validation_row_from_wire(value: object) -> RevisionSetItemValidation815V1:
    if type(value) is not dict or frozenset(value) != _VALIDATION_ROW_KEYS:
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    row = cast(dict[str, object], value)
    for key in (
        "file_size_match",
        "file_sha256_match",
        "page_count_match",
        "parse_manifest_sha256_match",
        "compiler_source_revision_id_match",
    ):
        if type(row.get(key)) is not bool:
            _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    return RevisionSetItemValidation815V1(
        role=_require_string(
            row.get("role"), "REVISION_SET_VALIDATION_OUTPUT_INVALID"
        ),
        knowledge_id=_require_string(
            row.get("knowledge_id"), "REVISION_SET_VALIDATION_OUTPUT_INVALID"
        ),
        weknora_parse_attempt=_require_integer(
            row.get("weknora_parse_attempt"),
            "REVISION_SET_VALIDATION_OUTPUT_INVALID",
        ),
        file_size=_require_integer(
            row.get("file_size"), "REVISION_SET_VALIDATION_OUTPUT_INVALID"
        ),
        file_sha256=_require_string(
            row.get("file_sha256"), "REVISION_SET_VALIDATION_OUTPUT_INVALID"
        ),
        page_count=_require_integer(
            row.get("page_count"), "REVISION_SET_VALIDATION_OUTPUT_INVALID"
        ),
        parse_manifest_sha256=_require_string(
            row.get("parse_manifest_sha256"),
            "REVISION_SET_VALIDATION_OUTPUT_INVALID",
        ),
        compiler_source_revision_id=_require_string(
            row.get("compiler_source_revision_id"),
            "REVISION_SET_VALIDATION_OUTPUT_INVALID",
        ),
        file_size_match=cast(bool, row["file_size_match"]),
        file_sha256_match=cast(bool, row["file_sha256_match"]),
        page_count_match=cast(bool, row["page_count_match"]),
        parse_manifest_sha256_match=cast(
            bool, row["parse_manifest_sha256_match"]
        ),
        compiler_source_revision_id_match=cast(
            bool, row["compiler_source_revision_id_match"]
        ),
    )


def validate_revision_set_manifest_815(
    manifest_path: Path,
) -> RevisionSetValidation815V1:
    """Fresh-open and deterministically validate the frozen exact-three RevisionSet."""
    if not isinstance(manifest_path, Path) or manifest_path.name != "revision-set.json":
        _reject("REVISION_SET_PATH_INVALID")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    try:
        root_fd = os.open(manifest_path.parent, flags)
    except OSError:
        _reject("REVISION_SET_ROOT_NOT_READY")
    try:
        root_stat = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_IMODE(root_stat.st_mode) != 0o700
            or root_stat.st_uid != os.geteuid()
        ):
            _reject("REVISION_SET_ROOT_METADATA_INVALID")
        set_bytes = _read_exact_file(root_fd, "revision-set.json")
        revision_set = _decode_canonical_json(
            set_bytes, "REVISION_SET_MANIFEST_INVALID"
        )
        ordered_roles = revision_set.get("ordered_roles")
        items = revision_set.get("items")
        canonicalization = revision_set.get("canonicalization")
        source_effects = revision_set.get("source_effects")
        tenant_id = _require_integer(
            revision_set.get("tenant_id"), "REVISION_SET_MANIFEST_INVALID"
        )
        knowledge_base_id = _require_string(
            revision_set.get("knowledge_base_id"), "REVISION_SET_MANIFEST_INVALID"
        )
        if (
            frozenset(revision_set) != _SET_KEYS
            or revision_set.get("contract") != "weknora.ec.revision-set.v1"
            or ordered_roles != list(_ROLES)
            or type(items) is not list
            or len(items) != 3
            or canonicalization
            != {
                "digest_domain": "weknora.ec.revision-set.v1\\0",
                "encoding": "UTF-8",
                "json": "sort_keys=true,separators=(',',':'),ensure_ascii=false",
            }
            or source_effects
            != {"database_writes": 0, "provider_calls": 0, "runtime_writes": 0}
        ):
            _reject("REVISION_SET_MANIFEST_INVALID")
        revision_set_sha256 = revision_set.get("revision_set_sha256")
        if (
            not _is_sha256(revision_set_sha256)
            or revision_set_sha256
            != _domain_hash(
                "weknora.ec.revision-set.v1",
                revision_set,
                "revision_set_sha256",
            )
        ):
            _reject("REVISION_SET_SELF_HASH_INVALID")

        rows: list[RevisionSetItemValidation815V1] = []
        for role, summary_value in zip(_ROLES, items, strict=True):
            if type(summary_value) is not dict:
                _reject("REVISION_SET_SUMMARY_INVALID")
            summary = cast(dict[str, object], summary_value)
            manifest_name, material_name = _FILES[role]
            if (
                frozenset(summary) != _SUMMARY_KEYS
                or summary.get("role") != role
                or summary.get("manifest_file") != manifest_name
                or summary.get("material_file") != material_name
            ):
                _reject("REVISION_SET_SUMMARY_INVALID")
            manifest_bytes = _read_exact_file(root_fd, manifest_name)
            if _sha256(manifest_bytes) != summary.get("manifest_file_sha256"):
                _reject("REVISION_SET_MANIFEST_FILE_HASH_INVALID")
            item = _decode_canonical_json(
                manifest_bytes, "REVISION_SET_ITEM_INVALID"
            )
            _validate_item_shape(
                item,
                role=role,
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base_id,
            )
            if item.get("material_file") != material_name:
                _reject("REVISION_SET_ITEM_INVALID")
            item_self_hash = _domain_hash(
                "weknora.ec.revision-item.v1", item, "manifest_self_sha256"
            )
            if (
                item_self_hash != item.get("manifest_self_sha256")
                or item_self_hash != summary.get("manifest_self_sha256")
            ):
                _reject("REVISION_SET_ITEM_SELF_HASH_INVALID")

            pdf_bytes = _read_exact_file(root_fd, material_name)
            file_size = len(pdf_bytes)
            file_sha256 = _sha256(pdf_bytes)
            page_count = _pdf_page_count(pdf_bytes)
            parse_manifest_sha256 = _parse_manifest_sha256(item)
            compiler_source_revision_id = _compiler_source_revision_id(item)
            expected_file_size = _require_integer(
                item.get("file_size"), "REVISION_SET_ITEM_INVALID"
            )
            expected_page_count = _require_integer(
                item.get("page_count"), "REVISION_SET_ITEM_INVALID"
            )
            expected_file_sha256 = _require_string(
                item.get("file_sha256"), "REVISION_SET_ITEM_INVALID"
            )
            expected_parse_manifest_sha256 = _require_string(
                item.get("parse_manifest_sha256"), "REVISION_SET_ITEM_INVALID"
            )
            expected_source_revision_id = _require_string(
                item.get("compiler_source_revision_id"),
                "REVISION_SET_ITEM_INVALID",
            )
            matches = (
                file_size == expected_file_size,
                file_sha256
                == expected_file_sha256
                == summary.get("material_file_sha256"),
                page_count == expected_page_count,
                parse_manifest_sha256 == expected_parse_manifest_sha256,
                compiler_source_revision_id == expected_source_revision_id,
            )
            if not all(matches):
                _reject("REVISION_SET_EXACT_READ_MISMATCH")
            rows.append(
                RevisionSetItemValidation815V1(
                    role=role,
                    knowledge_id=_require_string(
                        item.get("knowledge_id"), "REVISION_SET_ITEM_INVALID"
                    ),
                    weknora_parse_attempt=_require_integer(
                        item.get("weknora_parse_attempt"),
                        "REVISION_SET_ITEM_INVALID",
                    ),
                    file_size=file_size,
                    file_sha256=file_sha256,
                    page_count=page_count,
                    parse_manifest_sha256=parse_manifest_sha256,
                    compiler_source_revision_id=compiler_source_revision_id,
                    file_size_match=matches[0],
                    file_sha256_match=matches[1],
                    page_count_match=matches[2],
                    parse_manifest_sha256_match=matches[3],
                    compiler_source_revision_id_match=matches[4],
                )
            )
    finally:
        os.close(root_fd)

    exact_rows = tuple(rows)
    external_sha256 = _sha256(set_bytes)
    logical_sha256 = revision_set_sha256
    unsigned_result = _result_payload_without_hash(
        rows=exact_rows,
        revision_set_external_sha256=external_sha256,
        revision_set_sha256=logical_sha256,
    )
    validation_sha256 = _domain_hash(
        _VALIDATION_CONTRACT, unsigned_result, "validation_sha256"
    )
    return RevisionSetValidation815V1(
        contract="revision-set-validation.815.v1",
        status="PASS",
        ordered_roles=_ROLES,
        rows=exact_rows,
        materials_reopened=3,
        parse_manifests_recomputed=3,
        source_revision_ids_recomputed=3,
        revision_set_external_sha256=external_sha256,
        revision_set_sha256=logical_sha256,
        provider_calls=0,
        validation_sha256=validation_sha256,
    )


def freeze_revision_set_validation_815(
    result: RevisionSetValidation815V1,
    output_path: Path,
) -> None:
    """Write one canonical machine result without replacing an existing file."""
    if type(result) is not RevisionSetValidation815V1 or not isinstance(
        output_path, Path
    ):
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    require_revision_set_validation_value_815(result)
    payload = _canonical_bytes(result.to_wire()) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(output_path, flags, 0o600)
    except OSError:
        _reject("REVISION_SET_VALIDATION_OUTPUT_NOT_READY")
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def require_revision_set_validation_value_815(
    result: RevisionSetValidation815V1,
) -> None:
    """Freshly replay the deterministic machine-result hash and exact PASS shape."""
    if (
        type(result) is not RevisionSetValidation815V1
        or result.contract != _VALIDATION_CONTRACT
        or result.status != "PASS"
        or result.ordered_roles != _ROLES
        or len(result.rows) != 3
        or tuple(row.role for row in result.rows) != _ROLES
        or result.materials_reopened != 3
        or result.parse_manifests_recomputed != 3
        or result.source_revision_ids_recomputed != 3
        or result.provider_calls != 0
        or not _is_sha256(result.revision_set_external_sha256)
        or not _is_sha256(result.revision_set_sha256)
        or not all(
            row.file_size_match
            and row.file_sha256_match
            and row.page_count_match
            and row.parse_manifest_sha256_match
            and row.compiler_source_revision_id_match
            for row in result.rows
        )
    ):
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    unsigned = _result_payload_without_hash(
        rows=result.rows,
        revision_set_external_sha256=result.revision_set_external_sha256,
        revision_set_sha256=result.revision_set_sha256,
    )
    if result.validation_sha256 != _domain_hash(
        _VALIDATION_CONTRACT, unsigned, "validation_sha256"
    ):
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")


def require_revision_set_validation_815(
    output_path: Path,
) -> RevisionSetValidation815V1:
    """Fresh-open and replay a frozen machine-result file."""
    if not isinstance(output_path, Path):
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    parent_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    parent_flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_fd = os.open(output_path.parent, parent_flags)
    except OSError:
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    try:
        payload = _read_exact_file(parent_fd, output_path.name)
    finally:
        os.close(parent_fd)
    value = _decode_canonical_json(
        payload, "REVISION_SET_VALIDATION_OUTPUT_INVALID"
    )
    if frozenset(value) != frozenset(
        {
            "contract",
            "materials_reopened",
            "ordered_roles",
            "parse_manifests_recomputed",
            "provider_calls",
            "revision_set_external_sha256",
            "revision_set_sha256",
            "rows",
            "source_revision_ids_recomputed",
            "status",
            "validation_sha256",
        }
    ):
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    row_values = value.get("rows")
    if type(row_values) is not list:
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    try:
        rows = tuple(_validation_row_from_wire(row) for row in row_values)
        result = RevisionSetValidation815V1(
            contract=cast(Literal["revision-set-validation.815.v1"], value["contract"]),
            status=cast(Literal["PASS"], value["status"]),
            ordered_roles=tuple(cast(list[str], value["ordered_roles"])),
            rows=rows,
            materials_reopened=cast(int, value["materials_reopened"]),
            parse_manifests_recomputed=cast(
                int, value["parse_manifests_recomputed"]
            ),
            source_revision_ids_recomputed=cast(
                int, value["source_revision_ids_recomputed"]
            ),
            revision_set_external_sha256=cast(
                str, value["revision_set_external_sha256"]
            ),
            revision_set_sha256=cast(str, value["revision_set_sha256"]),
            provider_calls=cast(Literal[0], value["provider_calls"]),
            validation_sha256=cast(str, value["validation_sha256"]),
        )
    except (KeyError, TypeError, ValueError):
        _reject("REVISION_SET_VALIDATION_OUTPUT_INVALID")
    require_revision_set_validation_value_815(result)
    return result


__all__ = [
    "RevisionSetItemValidation815V1",
    "RevisionSetValidation815V1",
    "RevisionSetValidationError",
    "freeze_revision_set_validation_815",
    "require_revision_set_validation_815",
    "validate_revision_set_manifest_815",
]
