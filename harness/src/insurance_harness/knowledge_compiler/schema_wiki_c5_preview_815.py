"""Closed-world C5 projection of the frozen EC-01 Formal Candidate."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, NoReturn, cast

from pydantic import ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    MEDICAL_ENTITY_ID,
    MEDICAL_VERSION_ID,
    make_medical_schema_pack_596_1,
)
from insurance_harness.knowledge_compiler.revision_set_manifest_815 import (
    validate_revision_set_manifest_815,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
    APPROVED_PRODUCT_VERSION_ID,
    approved_schema_rows,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
    Schema67CandidateEvidenceAuthorityV1,
    _require_factory_authority,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256

_PREVIEW_CONTRACT: Final[str] = "schema-wiki-formal-candidate-preview.815.v1"
_MANIFEST_CONTRACT: Final[str] = (
    "schema-wiki-formal-candidate-preview-bundle.815.v1"
)
_HASH_DOMAIN: Final[bytes] = b"weknora.schema-wiki-c5.815.v1\0"
_PRODUCT_DISPLAY_NAME: Final[str] = "平安e生保（尊享版）医疗保险"
_TENANT_ID: Final[int] = 10003
_WIKI_KB_ID: Final[str] = "b1f1764c-443d-46b8-98e3-d5aa5e55eb42"
_C3_MEMBER_NAMES: Final[tuple[str, ...]] = (
    "formal-candidate.json",
    "coordinate-evidence-companion.json",
    "terminal.json",
    "field-attempt-manifest.json",
    "formal-derivation-validation.json",
    "result-manifest.json",
)
_REVISION_MEMBER_NAMES: Final[tuple[str, ...]] = (
    "revision-set.json",
    "terms.manifest.json",
    "terms.pdf",
    "brochure.manifest.json",
    "brochure.pdf",
    "rate_table.manifest.json",
    "rate_table.pdf",
)
_MEMBER_NAMES: Final[tuple[str, ...]] = (
    "preview.json",
    *_C3_MEMBER_NAMES,
    *_REVISION_MEMBER_NAMES,
)
_EVIDENCE_AUTHORITY_MEMBER_NAME: Final[str] = "candidate-evidence-authority.json"
_EVIDENCE_AUTHORITY_MEMBER_NAMES: Final[tuple[str, ...]] = (
    "preview.json",
    "formal-candidate.json",
    "coordinate-evidence-companion.json",
    _EVIDENCE_AUTHORITY_MEMBER_NAME,
    "terminal.json",
    "field-attempt-manifest.json",
    "formal-derivation-validation.json",
    "result-manifest.json",
    *_REVISION_MEMBER_NAMES,
)
_PREVIEW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "contract",
        "experiment_id",
        "candidate_sha256",
        "companion_sha256",
        "terminal_sha256",
        "revision_set_sha256",
        "quality_status",
        "mvp_status",
        "publishing",
        "coordinate_source_roles",
        "source_roles_without_coordinate_selections",
        "product",
        "ordered_section_ids",
        "sections",
        "fields",
        "preview_sha256",
    }
)
_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "contract",
        "tenant_id",
        "wiki_kb_id",
        "experiment_id",
        "candidate_sha256",
        "candidate_file_sha256",
        "companion_sha256",
        "companion_file_sha256",
        "terminal_sha256",
        "terminal_file_sha256",
        "field_attempt_manifest_sha256",
        "formal_derivation_validation_sha256",
        "revision_set_sha256",
        "quality_status",
        "mvp_status",
        "publishing",
        "members",
        "manifest_sha256",
    }
)
_EVIDENCE_AUTHORITY_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    _MANIFEST_KEYS
    | {
        "candidate_evidence_authority_sha256",
        "candidate_evidence_authority_file_sha256",
    }
)
_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "artifacts",
        "authorization",
        "candidate",
        "contract",
        "cost",
        "counters",
        "effects",
        "failure_reason",
        "git",
        "identities",
        "latency_total_ms",
        "projection",
        "self_sha256",
        "status",
        "terminal",
        "usage",
    }
)
_HYDRATION_SUCCESSOR_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "artifacts",
        "candidate",
        "classification",
        "contract",
        "derivation",
        "external_effects",
        "identities",
        "raw_external_sha256s",
        "self_sha256",
        "source_artifact_root",
        "terminal",
    }
)
_HYDRATION_SUCCESSOR_MEMBER_NAMES: Final[dict[str, str]] = {
    "formal-candidate.json": "successor-formal-candidate.json",
    "coordinate-evidence-companion.json": (
        "successor-coordinate-evidence-companion.json"
    ),
    "terminal.json": "successor-terminal.json",
    "field-attempt-manifest.json": "successor-field-attempt-manifest.json",
    "formal-derivation-validation.json": (
        "successor-formal-derivation-validation.json"
    ),
    "result-manifest.json": "successor-result.json",
}
_HYDRATION_SUCCESSOR_REPORT_NAMES: Final[tuple[str, ...]] = (
    "before-after-exact67.json",
    "classification-exact16.json",
)
_PRODUCT_KEYS: Final[frozenset[str]] = frozenset(
    {"entity_id", "entity_version_id", "product_version_id", "display_name"}
)
_SECTION_KEYS: Final[frozenset[str]] = frozenset(
    {"section_id", "display_name", "ordered_field_ids"}
)
_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_order",
        "section_id",
        "field_id",
        "display_name",
        "state",
        "value_snapshot",
        "typed_reason",
        "source_selections",
    }
)
_SOURCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "selection_id",
        "field_id",
        "source_role",
        "source_revision_id",
        "original_file_sha256",
        "parse_manifest_sha256",
        "page_number",
        "coordinate_space",
        "page_width_points",
        "page_height_points",
        "bbox",
        "rects",
        "block_id",
        "span_id",
        "table_id",
        "table_slice_id",
        "cell_ids",
        "quote",
        "quote_sha256",
        "page_text_char_start",
        "page_text_char_end",
    }
)
_MEMBER_KEYS: Final[frozenset[str]] = frozenset(
    {"name", "sha256", "size_bytes"}
)
_COMPANION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "candidate_sha256",
        "companion_sha256",
        "contract",
        "coordinate_rows",
        "parse_manifest_sha256s",
        "provider_visible_field_ids",
        "selection_catalog_sha256",
    }
)
_COORDINATE_KEYS: Final[frozenset[str]] = frozenset(
    _SOURCE_KEYS
    | {
        "page_text_char_end",
        "page_text_char_start",
        "selection_type",
    }
)
_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SHA1_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_DECIMAL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"
)
_PAGE_TEXT_LINE_SEPARATOR: Final[str] = "\N{LINE SEPARATOR}"
_SOURCE_DOCUMENT_IDENTITY_KEYS: Final[tuple[str, ...]] = (
    "field_id",
    "selection_id",
    "source_role",
    "source_revision_id",
    "original_file_sha256",
    "parse_manifest_sha256",
    "coordinate_space",
    "selection_type",
)
_SOURCE_PAGE_IDENTITY_KEYS: Final[tuple[str, ...]] = (
    *_SOURCE_DOCUMENT_IDENTITY_KEYS,
    "page_number",
    "page_width_points",
    "page_height_points",
)


def _reject(reason: str) -> NoReturn:
    raise ValueError(reason)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _object_hash(object_type: str, value: dict[str, object]) -> str:
    return _sha256(
        _HASH_DOMAIN
        + object_type.encode("ascii")
        + b"\0"
        + _canonical_bytes(value)
    )


def _legacy_domain_hash(object_type: str, value: dict[str, object]) -> str:
    return _sha256(object_type.encode("ascii") + b"\0" + _canonical_bytes(value))


def _as_object(value: object, reason: str) -> dict[str, object]:
    if type(value) is not dict:
        _reject(reason)
    return cast(dict[str, object], value)


def _as_objects(value: object, reason: str) -> list[dict[str, object]]:
    if type(value) is not list:
        _reject(reason)
    return [_as_object(item, reason) for item in cast(list[object], value)]


def _as_strings(value: object, reason: str) -> list[str]:
    if type(value) is not list:
        _reject(reason)
    items = cast(list[object], value)
    if any(type(item) is not str for item in items):
        _reject(reason)
    return cast(list[str], items)


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_PATTERN.fullmatch(value) is not None


def _read_regular_file(root: Path, name: str) -> bytes:
    path = root / name
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            _reject("C5_INPUT_MEMBER_INVALID")
        return path.read_bytes()
    except OSError:
        _reject("C5_INPUT_MEMBER_INVALID")


def _path_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        _reject("C5_INPUT_MEMBER_INVALID")
    return True


def _read_c3_members(
    root: Path,
    *,
    require_successor_reports: bool,
) -> tuple[dict[str, bytes], dict[str, bytes] | None]:
    has_legacy = _path_entry_exists(root / "result-manifest.json")
    has_successor = _path_entry_exists(root / "successor-result.json")
    if has_legacy == has_successor:
        _reject("C5_INPUT_MEMBER_INVALID")
    if has_legacy:
        c3_bytes = {name: _read_regular_file(root, name) for name in _C3_MEMBER_NAMES}
        result = _decode_json(c3_bytes["result-manifest.json"], "C5_RESULT_INVALID")
        if result.get("contract") != "ec01-c3-hydration-successor-result.815.v1":
            return c3_bytes, None
        if require_successor_reports:
            _reject("C5_INPUT_MEMBER_INVALID")
        return (
            c3_bytes,
            {
                source_name: c3_bytes[bundle_name]
                for bundle_name, source_name in _HYDRATION_SUCCESSOR_MEMBER_NAMES.items()
            },
        )
    successor_bytes = {
        name: _read_regular_file(root, name)
        for name in (
            *_HYDRATION_SUCCESSOR_MEMBER_NAMES.values(),
            *_HYDRATION_SUCCESSOR_REPORT_NAMES,
        )
    }
    return (
        {
            bundle_name: successor_bytes[source_name]
            for bundle_name, source_name in _HYDRATION_SUCCESSOR_MEMBER_NAMES.items()
        },
        successor_bytes,
    )


def _decode_json(payload: bytes, reason: str) -> dict[str, object]:
    try:
        return _as_object(json.loads(payload.decode("utf-8")), reason)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _reject(reason)


def _without(value: dict[str, object], *keys: str) -> dict[str, object]:
    return {key: item for key, item in value.items() if key not in keys}


def _require_canonical_text(value: object, *, allow_edge_space: bool = False) -> str:
    if type(value) is not str or not value:
        _reject("C5_STRING_INVALID")
    if not unicodedata.is_normalized("NFC", value):
        _reject("C5_STRING_INVALID")
    if any(unicodedata.category(character) == "Cc" for character in value):
        _reject("C5_STRING_INVALID")
    if not allow_edge_space and value != value.strip():
        _reject("C5_STRING_INVALID")
    return value


def _require_sha(value: object) -> str:
    if not _is_sha256(value):
        _reject("C5_SHA256_INVALID")
    return cast(str, value)


def _require_sha1(value: object) -> str:
    if type(value) is not str or _SHA1_PATTERN.fullmatch(value) is None:
        _reject("C5_GIT_IDENTITY_INVALID")
    return value


def _require_uuid(value: object) -> str:
    if type(value) is not str:
        _reject("C5_EXPERIMENT_ID_INVALID")
    try:
        if str(uuid.UUID(value)) != value:
            _reject("C5_EXPERIMENT_ID_INVALID")
    except ValueError:
        _reject("C5_EXPERIMENT_ID_INVALID")
    return value


def _require_decimal(value: object, *, positive: bool) -> str:
    if type(value) is not str or _DECIMAL_PATTERN.fullmatch(value) is None:
        _reject("C5_COORDINATE_INVALID")
    try:
        number = Decimal(value)
    except InvalidOperation:
        _reject("C5_COORDINATE_INVALID")
    if (positive and number <= 0) or (not positive and number < 0):
        _reject("C5_COORDINATE_INVALID")
    return value


def _require_bbox(value: object) -> list[str]:
    values = _as_strings(value, "C5_COORDINATE_INVALID")
    if len(values) != 4:
        _reject("C5_COORDINATE_INVALID")
    for item in values:
        _require_decimal(item, positive=False)
    if Decimal(values[0]) >= Decimal(values[2]) or Decimal(values[1]) >= Decimal(values[3]):
        _reject("C5_COORDINATE_INVALID")
    return values


def _validate_field_attempt_manifest(value: dict[str, object]) -> None:
    if value.get("contract") != "schema67-field-attempt-manifest.815.v1":
        _reject("C5_FIELD_ATTEMPT_INVALID")
    manifest_hash = _require_sha(value.get("manifest_sha256"))
    derivation_hash = _require_sha(value.get("formal_candidate_derivation_sha256"))
    unsigned = _without(value, "manifest_sha256", "formal_candidate_derivation_sha256")
    if manifest_hash != canonical_hash("schema67-field-attempt-manifest.815.v1", unsigned):
        _reject("C5_FIELD_ATTEMPT_INVALID")
    rows = _as_objects(value.get("rows"), "C5_FIELD_ATTEMPT_INVALID")
    if (
        len(rows) != 67
        or [row.get("field_id") for row in rows] != list(APPROVED_ORDERED_FIELD_IDS)
        or [row.get("schema_order") for row in rows] != list(range(1, 68))
    ):
        _reject("C5_FIELD_ATTEMPT_INVALID")
    for row in rows:
        row_hash = _require_sha(row.get("row_sha256"))
        if row_hash != canonical_hash(
            "schema67-field-attempt.815.v1", _without(row, "row_sha256")
        ):
            _reject("C5_FIELD_ATTEMPT_INVALID")
    derivation_value: dict[str, object] = {
        "attempt_id": value.get("attempt_id"),
        "candidate_evidence_sha256": value.get("candidate_evidence_sha256"),
        "candidate_fields_sha256": value.get("candidate_fields_sha256"),
        "derivation_source": value.get("derivation_source"),
        "execution_identity_sha256": value.get("execution_identity_sha256"),
        "experiment_id": value.get("experiment_id"),
        "field_attempt_manifest_sha256": manifest_hash,
        "integration_head": value.get("integration_head"),
        "integration_tree": value.get("integration_tree"),
        "receipt_id": value.get("receipt_id"),
        "request_manifest_sha256": value.get("request_manifest_sha256"),
        "revision_set_sha256": value.get("revision_set_sha256"),
        "revision_validation_sha256": value.get("revision_validation_sha256"),
        "run_derivation_sha256": value.get("run_derivation_sha256"),
        "run_id": value.get("run_id"),
        "schema_rows_sha256": value.get("schema_rows_sha256"),
        "terminal_sha256": value.get("terminal_sha256"),
    }
    if derivation_hash != canonical_hash(
        "schema67-formal-candidate-derivation.815.v1", derivation_value
    ):
        _reject("C5_FIELD_ATTEMPT_INVALID")


def _validate_companion(
    value: dict[str, object],
    *,
    candidate_sha256: str,
) -> str:
    companion_sha256 = _require_sha(value.get("companion_sha256"))
    if (
        set(value) != _COMPANION_KEYS
        or value.get("contract")
        != "schema67-coordinate-evidence-companion.815.v1"
        or value.get("candidate_sha256") != candidate_sha256
        or companion_sha256
        != canonical_hash(
            "schema67-coordinate-evidence-companion.815.v1",
            _without(value, "companion_sha256"),
        )
        or not _is_sha256(value.get("selection_catalog_sha256"))
    ):
        _reject("C5_COMPANION_INVALID")
    field_ids = _as_strings(
        value.get("provider_visible_field_ids"), "C5_COMPANION_INVALID"
    )
    parse_hashes = _as_strings(
        value.get("parse_manifest_sha256s"), "C5_COMPANION_INVALID"
    )
    rows = _as_objects(value.get("coordinate_rows"), "C5_COMPANION_INVALID")
    if (
        not field_ids
        or len(field_ids) != len(set(field_ids))
        or len(parse_hashes) != 3
        or len(parse_hashes) != len(set(parse_hashes))
        or any(not _is_sha256(item) for item in parse_hashes)
    ):
        _reject("C5_COMPANION_INVALID")
    order = {field_id: ordinal for ordinal, field_id in enumerate(field_ids)}
    ordinals: list[int] = []
    for row in rows:
        field_id = row.get("field_id")
        if (
            set(row) != _COORDINATE_KEYS
            or type(field_id) is not str
            or field_id not in order
            or row.get("parse_manifest_sha256") not in parse_hashes
            or row.get("source_role") not in {"terms", "brochure", "rate_table"}
            or row.get("coordinate_space") != "PDF_POINTS_TOP_LEFT_V1"
            or type(row.get("page_number")) is not int
            or cast(int, row["page_number"]) <= 0
        ):
            _reject("C5_COMPANION_INVALID")
        ordinals.append(order[field_id])
        quote = _require_canonical_text(row.get("quote"), allow_edge_space=True)
        if _require_sha(row.get("quote_sha256")) != _sha256(quote.encode("utf-8")):
            _reject("C5_COMPANION_INVALID")
        _require_bbox(row.get("bbox"))
        rect_values = row.get("rects")
        if type(rect_values) is not list or not rect_values:
            _reject("C5_COMPANION_INVALID")
        for rect in cast(list[object], rect_values):
            _require_bbox(rect)
    if ordinals != sorted(ordinals):
        _reject("C5_COMPANION_INVALID")
    return companion_sha256


def _artifact_sha(result: dict[str, object], name: str) -> str:
    matches = [
        row
        for row in _as_objects(result.get("artifacts"), "C5_RESULT_INVALID")
        if row.get("name") == name
    ]
    if len(matches) != 1:
        _reject("C5_RESULT_INVALID")
    return _require_sha(matches[0].get("sha256"))


def _validate_hydration_successor_result(
    *,
    result: dict[str, object],
    successor_bytes: dict[str, bytes],
    candidate_sha256: str,
    candidate_file_sha256: str,
    companion_file_sha256: str,
    terminal_sha256: str,
    terminal_file_sha256: str,
    field_attempt_file_sha256: str,
    validation_file_sha256: str,
    revision_set_sha256: str,
    state_distribution: dict[str, int],
    field_attempt: dict[str, object],
    terminal: dict[str, object],
    validation: dict[str, object],
    require_successor_reports: bool,
) -> tuple[str, str, str]:
    if (
        set(result) != _HYDRATION_SUCCESSOR_RESULT_KEYS
        or result.get("contract") != "ec01-c3-hydration-successor-result.815.v1"
        or _require_sha(result.get("self_sha256"))
        != _sha256(_canonical_bytes(_without(result, "self_sha256")))
    ):
        _reject("C5_RESULT_INVALID")

    source_root = result.get("source_artifact_root")
    if (
        type(source_root) is not str
        or not Path(source_root).is_absolute()
        or any(part.lower() in {"current", "latest"} for part in Path(source_root).parts)
    ):
        _reject("C5_RESULT_INVALID")

    identities = _as_object(result.get("identities"), "C5_RESULT_INVALID")
    if set(identities) != {
        "attempt_id",
        "execution_identity_sha256",
        "experiment_id",
        "integration_head",
        "integration_tree",
        "receipt_id",
        "revision_set_sha256",
        "run_id",
    }:
        _reject("C5_RESULT_INVALID")
    identity_ids = [
        _require_uuid(identities.get(key))
        for key in ("experiment_id", "run_id", "attempt_id", "receipt_id")
    ]
    if len(set(identity_ids)) != 4 or any(uuid.UUID(value).version != 4 for value in identity_ids):
        _reject("C5_RESULT_INVALID")
    experiment_id = identity_ids[0]
    integration_head = _require_sha1(identities.get("integration_head"))
    integration_tree = _require_sha1(identities.get("integration_tree"))
    if (
        _require_sha(identities.get("execution_identity_sha256"))
        != field_attempt.get("execution_identity_sha256")
        or identities.get("revision_set_sha256") != revision_set_sha256
        or any(
            identities.get(key) != field_attempt.get(key)
            for key in ("experiment_id", "run_id", "attempt_id", "receipt_id")
        )
    ):
        _reject("C5_RESULT_INVALID")

    candidate_result = _as_object(result.get("candidate"), "C5_RESULT_INVALID")
    state_counts = _as_object(candidate_result.get("state_counts"), "C5_RESULT_INVALID")
    if (
        set(candidate_result) != {"candidate_sha256", "kind", "state_counts"}
        or set(state_counts) != {"present", "absent_explicitly", "unknown"}
        or candidate_result.get("candidate_sha256") != candidate_sha256
        or candidate_result.get("kind") != "FORMAL"
        or state_counts != state_distribution
    ):
        _reject("C5_RESULT_INVALID")

    terminal_result = _as_object(result.get("terminal"), "C5_RESULT_INVALID")
    raw_external_sha256s = _as_strings(
        result.get("raw_external_sha256s"), "C5_RESULT_INVALID"
    )
    if (
        set(terminal_result)
        != {"raw_count", "raw_index_sha256", "status", "terminal_sha256"}
        or terminal_result.get("status") != "SUCCEEDED"
        or terminal_result.get("terminal_sha256") != terminal_sha256
        or terminal_result.get("raw_count") != terminal.get("raw_count")
        or terminal_result.get("raw_index_sha256") != terminal.get("raw_index_sha256")
        or raw_external_sha256s != field_attempt.get("raw_response_sha256s")
        or len(raw_external_sha256s) != terminal_result.get("raw_count")
        or any(not _is_sha256(value) for value in raw_external_sha256s)
    ):
        _reject("C5_RESULT_INVALID")

    derivation = _as_object(result.get("derivation"), "C5_RESULT_INVALID")
    if (
        set(derivation)
        != {
            "formal_candidate_derivation_sha256",
            "manifest_sha256",
            "run_derivation_sha256",
            "status",
        }
        or derivation.get("status") != "PASS"
        or derivation.get("formal_candidate_derivation_sha256")
        != field_attempt.get("formal_candidate_derivation_sha256")
        or derivation.get("formal_candidate_derivation_sha256")
        != validation.get("formal_candidate_derivation_sha256")
        or derivation.get("manifest_sha256") != field_attempt.get("manifest_sha256")
        or derivation.get("manifest_sha256") != validation.get("manifest_sha256")
        or derivation.get("run_derivation_sha256")
        != field_attempt.get("run_derivation_sha256")
    ):
        _reject("C5_RESULT_INVALID")

    external_effects = _as_object(result.get("external_effects"), "C5_RESULT_INVALID")
    if external_effects != {
        "credential_reads": 0,
        "network_calls": 0,
        "provider_calls": 0,
    }:
        _reject("C5_RESULT_INVALID")

    classification = _as_object(result.get("classification"), "C5_RESULT_INVALID")
    if set(classification) != {"blocker", "class_a", "class_b", "restored"}:
        _reject("C5_RESULT_INVALID")
    _require_canonical_text(classification.get("blocker"))
    classified_field_ids = [
        field_id
        for key in ("class_a", "class_b", "restored")
        for field_id in _as_strings(classification.get(key), "C5_RESULT_INVALID")
    ]
    if (
        len(classified_field_ids) != 16
        or len(set(classified_field_ids)) != 16
        or any(field_id not in APPROVED_ORDERED_FIELD_IDS for field_id in classified_field_ids)
    ):
        _reject("C5_RESULT_INVALID")

    expected_artifact_names = [
        "successor-formal-candidate.json",
        "successor-coordinate-evidence-companion.json",
        "successor-terminal.json",
        "successor-field-attempt-manifest.json",
        "successor-formal-derivation-validation.json",
        *_HYDRATION_SUCCESSOR_REPORT_NAMES,
    ]
    artifacts = _as_objects(result.get("artifacts"), "C5_RESULT_INVALID")
    if [artifact.get("name") for artifact in artifacts] != expected_artifact_names:
        _reject("C5_RESULT_INVALID")
    expected_external_hashes = {
        "successor-formal-candidate.json": candidate_file_sha256,
        "successor-coordinate-evidence-companion.json": companion_file_sha256,
        "successor-terminal.json": terminal_file_sha256,
        "successor-field-attempt-manifest.json": field_attempt_file_sha256,
        "successor-formal-derivation-validation.json": validation_file_sha256,
    }
    expected_external_hashes.update(
        {
            name: _sha256(successor_bytes[name])
            for name in _HYDRATION_SUCCESSOR_REPORT_NAMES
            if name in successor_bytes
        }
    )
    for artifact in artifacts:
        name = artifact.get("name")
        if type(name) is not str or name not in expected_artifact_names:
            _reject("C5_RESULT_INVALID")
        artifact_bytes = successor_bytes.get(name)
        if artifact_bytes is None:
            if (
                require_successor_reports
                or name not in _HYDRATION_SUCCESSOR_REPORT_NAMES
                or type(artifact.get("bytes")) is not int
                or cast(int, artifact["bytes"]) <= 0
                or not _is_sha256(artifact.get("external_sha256"))
            ):
                _reject("C5_RESULT_INVALID")
            continue
        if (
            set(artifact) != {"bytes", "external_sha256", "name"}
            or artifact.get("bytes") != len(artifact_bytes)
            or artifact.get("external_sha256") != expected_external_hashes[name]
        ):
            _reject("C5_RESULT_INVALID")
    return experiment_id, integration_head, integration_tree


def _validate_frozen_inputs(
    *,
    c3_root: Path,
    revision_root: Path,
    require_successor_reports: bool,
) -> tuple[
    dict[str, bytes],
    dict[str, bytes],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, str],
]:
    if not c3_root.is_absolute() or not revision_root.is_absolute():
        _reject("C5_INPUT_ROOT_INVALID")
    c3_bytes, successor_bytes = _read_c3_members(
        c3_root,
        require_successor_reports=require_successor_reports,
    )
    revision_bytes = {
        name: _read_regular_file(revision_root, name) for name in _REVISION_MEMBER_NAMES
    }
    candidate = _decode_json(c3_bytes["formal-candidate.json"], "C5_CANDIDATE_INVALID")
    companion = _decode_json(
        c3_bytes["coordinate-evidence-companion.json"], "C5_COMPANION_INVALID"
    )
    terminal = _decode_json(c3_bytes["terminal.json"], "C5_TERMINAL_INVALID")
    field_attempt = _decode_json(
        c3_bytes["field-attempt-manifest.json"], "C5_FIELD_ATTEMPT_INVALID"
    )
    validation = _decode_json(
        c3_bytes["formal-derivation-validation.json"], "C5_DERIVATION_INVALID"
    )
    result = _decode_json(c3_bytes["result-manifest.json"], "C5_RESULT_INVALID")
    revision_set = _decode_json(
        revision_bytes["revision-set.json"], "C5_REVISION_SET_INVALID"
    )

    candidate_file_sha256 = _sha256(c3_bytes["formal-candidate.json"])
    companion_file_sha256 = _sha256(c3_bytes["coordinate-evidence-companion.json"])
    terminal_file_sha256 = _sha256(c3_bytes["terminal.json"])
    field_attempt_file_sha256 = _sha256(c3_bytes["field-attempt-manifest.json"])
    validation_file_sha256 = _sha256(c3_bytes["formal-derivation-validation.json"])
    candidate_sha256 = _require_sha(candidate.get("candidate_sha256"))
    if candidate_sha256 != canonical_hash(
        "schema67-candidate.v2", _without(candidate, "candidate_sha256")
    ):
        _reject("C5_FROZEN_INTERNAL_IDENTITY_INVALID")
    companion_sha256 = _validate_companion(
        companion,
        candidate_sha256=candidate_sha256,
    )
    terminal_sha256 = _require_sha(terminal.get("terminal_sha256"))
    if terminal_sha256 != _legacy_domain_hash(
        "ec01-formal-candidate-terminal.815.v1", _without(terminal, "terminal_sha256")
    ):
        _reject("C5_FROZEN_INTERNAL_IDENTITY_INVALID")
    _validate_field_attempt_manifest(field_attempt)

    revision_validation = validate_revision_set_manifest_815(
        revision_root / "revision-set.json"
    )
    revision_set_sha256 = revision_validation.revision_set_sha256
    if (
        revision_set.get("revision_set_sha256") != revision_set_sha256
        or revision_set.get("tenant_id") != _TENANT_ID
        or revision_set.get("knowledge_base_id") != _WIKI_KB_ID
    ):
        _reject("C5_REVISION_SET_INVALID")

    candidate_fields = _as_objects(candidate.get("fields"), "C5_CANDIDATE_INVALID")
    if (
        candidate.get("contract") != "schema67-candidate.v2"
        or candidate.get("ordered_field_ids") != list(APPROVED_ORDERED_FIELD_IDS)
        or len(candidate_fields) != 67
        or [field.get("field_id") for field in candidate_fields]
        != list(APPROVED_ORDERED_FIELD_IDS)
    ):
        _reject("C5_CANDIDATE_INVALID")
    state_distribution: dict[str, int] = {}
    for field in candidate_fields:
        state = field.get("state")
        if state not in {"present", "absent_explicitly", "unknown"}:
            _reject("C5_CANDIDATE_INVALID")
        state_key = state
        state_distribution[state_key] = state_distribution.get(state_key, 0) + 1
    attempted_field_count = field_attempt.get("attempted_field_count")
    provider_visible_count = field_attempt.get("provider_visible_count")
    real_model_output_count = field_attempt.get("real_model_output_count")
    code_deferred_count = field_attempt.get("code_deferred_count")
    dispositioned_count = field_attempt.get("dispositioned_count")
    if result.get("contract") == "ec01-native-pdf-selection-result.815.v1":
        candidate_result = _as_object(result.get("candidate"), "C5_RESULT_INVALID")
        terminal_result = _as_object(result.get("terminal"), "C5_RESULT_INVALID")
        identities = _as_object(result.get("identities"), "C5_RESULT_INVALID")
        git = _as_object(result.get("git"), "C5_RESULT_INVALID")
        effects = _as_object(result.get("effects"), "C5_RESULT_INVALID")
        result_self_hash = _require_sha(result.get("self_sha256"))
        experiment_id = _require_uuid(identities.get("experiment_id"))
        integration_head = _require_sha1(git.get("head"))
        integration_tree = _require_sha1(git.get("tree"))
        _require_sha1(git.get("parent"))
        if (
            successor_bytes is not None
            or set(result) != _RESULT_KEYS
            or result.get("status") != "SUCCEEDED"
            or result.get("failure_reason") is not None
            or result_self_hash
            != _sha256(_canonical_bytes(_without(result, "self_sha256")))
            or candidate_result.get("kind") != "FORMAL"
            or candidate_result.get("present") is not True
            or candidate_result.get("deterministic_replay_status") != "PASS"
            or candidate_result.get("candidate_internal_sha256") != candidate_sha256
            or candidate_result.get("candidate_external_sha256")
            != candidate_file_sha256
            or candidate_result.get("coordinate_companion_internal_sha256")
            != companion_sha256
            or candidate_result.get("coordinate_companion_external_sha256")
            != companion_file_sha256
            or candidate_result.get("field_attempt_manifest_external_sha256")
            != field_attempt_file_sha256
            or candidate_result.get("derivation_validation_external_sha256")
            != validation_file_sha256
            or candidate_result.get("ordered_field_count") != 67
            or candidate_result.get("state_distribution") != state_distribution
            or candidate_result.get("attempted_field_count") != attempted_field_count
            or candidate_result.get("provider_visible_field_count")
            != provider_visible_count
            or candidate_result.get("real_model_output_count")
            != real_model_output_count
            or candidate_result.get("code_deferred_field_count") != code_deferred_count
            or candidate_result.get("dispositioned_field_count") != dispositioned_count
            or terminal_result
            != {
                "internal_sha256": terminal_sha256,
                "present": True,
                "status": "SUCCEEDED",
            }
            or any(
                effects.get(key) != expected
                for key, expected in {
                    "database_writes": 0,
                    "draft_review_publish_active_writes": 0,
                    "git_writes": 0,
                    "golden_c4_c5_p1_started": False,
                    "knowledge_base_writes": 0,
                    "migration_writes": 0,
                }.items()
            )
        ):
            _reject("C5_RESULT_INVALID")
        if (
            _artifact_sha(result, "formal-candidate.json") != candidate_file_sha256
            or _artifact_sha(result, "coordinate-evidence-companion.json")
            != companion_file_sha256
            or _artifact_sha(result, "terminal.json") != terminal_file_sha256
            or _artifact_sha(result, "field-attempt-manifest.json")
            != field_attempt_file_sha256
            or _artifact_sha(result, "formal-derivation-validation.json")
            != validation_file_sha256
        ):
            _reject("C5_RESULT_INVALID")
    elif result.get("contract") == "ec01-c3-hydration-successor-result.815.v1":
        if successor_bytes is None:
            _reject("C5_RESULT_INVALID")
        experiment_id, integration_head, integration_tree = (
            _validate_hydration_successor_result(
                result=result,
                successor_bytes=successor_bytes,
                candidate_sha256=candidate_sha256,
                candidate_file_sha256=candidate_file_sha256,
                companion_file_sha256=companion_file_sha256,
                terminal_sha256=terminal_sha256,
                terminal_file_sha256=terminal_file_sha256,
                field_attempt_file_sha256=field_attempt_file_sha256,
                validation_file_sha256=validation_file_sha256,
                revision_set_sha256=revision_set_sha256,
                state_distribution=state_distribution,
                field_attempt=field_attempt,
                terminal=terminal,
                validation=validation,
                require_successor_reports=require_successor_reports,
            )
        )
    else:
        _reject("C5_RESULT_INVALID")

    if (
        terminal.get("contract") != "ec01-formal-candidate-terminal.815.v1"
        or terminal.get("status") != "SUCCEEDED"
        or terminal.get("failure_reason") is not None
        or terminal.get("experiment_id") != experiment_id
        or terminal.get("integration_head") != integration_head
        or terminal.get("integration_tree") != integration_tree
        or terminal.get("revision_set_sha256") != revision_set_sha256
        or terminal.get("coordinate_evidence_companion_sha256") != companion_sha256
        or terminal.get("terminal_sha256") != terminal_sha256
        or terminal.get("attempted_field_count") != attempted_field_count
        or terminal.get("provider_visible_field_count") != provider_visible_count
        or terminal.get("real_model_output_count") != real_model_output_count
        or terminal.get("code_deferred_field_count") != code_deferred_count
        or terminal.get("dispositioned_field_count") != dispositioned_count
    ):
        _reject("C5_TERMINAL_INVALID")
    if (
        field_attempt.get("experiment_id") != experiment_id
        or field_attempt.get("integration_head") != integration_head
        or field_attempt.get("integration_tree") != integration_tree
        or field_attempt.get("revision_set_sha256") != revision_set_sha256
        or field_attempt.get("terminal_sha256") != terminal_sha256
        or field_attempt.get("coordinate_evidence_companion_sha256")
        != companion_sha256
        or dispositioned_count != 67
    ):
        _reject("C5_FIELD_ATTEMPT_INVALID")
    if (
        set(validation)
        != {
            "attempted_field_count",
            "candidate_evidence_sha256",
            "candidate_fields_sha256",
            "contract",
            "derivation_source",
            "formal_candidate_derivation_sha256",
            "manifest_sha256",
            "ordered_field_count",
            "provider_calls",
            "raw_response_count",
            "request_count",
            "status",
            "terminal_sha256",
        }
        or validation.get("contract")
        != "schema67-formal-candidate-validation.815.v1"
        or validation.get("status") != "PASS"
        or validation.get("provider_calls") != 0
        or validation.get("ordered_field_count") != 67
        or validation.get("attempted_field_count") != attempted_field_count
        or validation.get("manifest_sha256") != field_attempt.get("manifest_sha256")
        or validation.get("terminal_sha256") != terminal_sha256
        or validation.get("candidate_fields_sha256")
        != field_attempt.get("candidate_fields_sha256")
        or validation.get("candidate_evidence_sha256")
        != field_attempt.get("candidate_evidence_sha256")
        or validation.get("formal_candidate_derivation_sha256")
        != field_attempt.get("formal_candidate_derivation_sha256")
    ):
        _reject("C5_DERIVATION_INVALID")
    frozen_identity = {
        "experiment_id": experiment_id,
        "candidate_sha256": candidate_sha256,
        "candidate_file_sha256": candidate_file_sha256,
        "companion_sha256": companion_sha256,
        "companion_file_sha256": companion_file_sha256,
        "terminal_sha256": terminal_sha256,
        "terminal_file_sha256": terminal_file_sha256,
        "field_attempt_manifest_sha256": field_attempt_file_sha256,
        "formal_derivation_validation_sha256": validation_file_sha256,
        "revision_set_sha256": revision_set_sha256,
    }
    return (
        c3_bytes,
        revision_bytes,
        candidate,
        companion,
        terminal,
        field_attempt,
        frozen_identity,
    )


def _source_projection(value: dict[str, object]) -> dict[str, object]:
    return {key: value[key] for key in _SOURCE_KEYS}


def _union_source_rects(rows: list[dict[str, object]]) -> tuple[list[list[str]], list[str]]:
    rects: list[list[str]] = []
    for row in rows:
        values = row.get("rects")
        if type(values) is not list or not values:
            _reject("C5_SOURCE_SELECTION_UNREPLAYABLE")
        rects.extend(_require_bbox(value) for value in cast(list[object], values))
    return (
        rects,
        [
            min(rects, key=lambda rect: Decimal(rect[0]))[0],
            min(rects, key=lambda rect: Decimal(rect[1]))[1],
            max(rects, key=lambda rect: Decimal(rect[2]))[2],
            max(rects, key=lambda rect: Decimal(rect[3]))[3],
        ],
    )


def _merge_source_run(
    rows: list[dict[str, object]],
    *,
    separators: list[str],
) -> dict[str, object]:
    first = rows[0]
    rects, bbox = _union_source_rects(rows)
    quotes = [_require_canonical_text(row.get("quote"), allow_edge_space=True) for row in rows]
    quote_parts = [quotes[0]]
    for separator, quote in zip(separators, quotes[1:], strict=True):
        quote_parts.extend((separator, quote))
    quote = "".join(quote_parts)
    merged = _source_projection(first)
    merged.update(
        {
            "bbox": bbox,
            "rects": rects,
            "quote": quote,
            "quote_sha256": _sha256(quote.encode("utf-8")),
        }
    )
    return merged


def _fold_text_source_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    runs: list[list[dict[str, object]]] = []
    separators: list[list[str]] = []
    for row in rows:
        if (
            row.get("table_id") is not None
            or row.get("table_slice_id") is not None
            or row.get("cell_ids") != []
            or type(row.get("page_text_char_start")) is not int
            or type(row.get("page_text_char_end")) is not int
            or cast(int, row["page_text_char_start"])
            >= cast(int, row["page_text_char_end"])
        ):
            _reject("C5_SOURCE_SELECTION_UNREPLAYABLE")
        if not runs:
            runs.append([row])
            separators.append([])
            continue
        previous = runs[-1][-1]
        gap = cast(int, row["page_text_char_start"]) - cast(
            int, previous["page_text_char_end"]
        )
        if gap < 0:
            _reject("C5_SOURCE_SELECTION_UNREPLAYABLE")
        if gap <= 1:
            runs[-1].append(row)
            separators[-1].append("" if gap == 0 else _PAGE_TEXT_LINE_SEPARATOR)
        else:
            runs.append([row])
            separators.append([])
    folded: list[dict[str, object]] = []
    for run, run_separators in zip(runs, separators, strict=True):
        merged = _merge_source_run(run, separators=run_separators)
        merged["page_text_char_start"] = run[0]["page_text_char_start"]
        merged["page_text_char_end"] = run[-1]["page_text_char_end"]
        folded.append(merged)
    return folded


def _fold_table_source_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    first = rows[0]
    if any(
        row.get("table_id") != first.get("table_id")
        or row.get("table_slice_id") != first.get("table_slice_id")
        or row.get("page_text_char_start") is not None
        or row.get("page_text_char_end") is not None
        for row in rows
    ):
        _reject("C5_SOURCE_SELECTION_IDENTITY_MISMATCH")
    merged = _merge_source_run(
        rows,
        separators=[_PAGE_TEXT_LINE_SEPARATOR] * (len(rows) - 1),
    )
    cell_ids: list[str] = []
    for row in rows:
        for cell_id in _as_strings(row.get("cell_ids"), "C5_SOURCE_SELECTION_UNREPLAYABLE"):
            if cell_id not in cell_ids:
                cell_ids.append(cell_id)
    merged["cell_ids"] = cell_ids
    merged["page_text_char_start"] = None
    merged["page_text_char_end"] = None
    return [merged]


def _fold_source_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Fold replayable rows without changing their original source identity."""

    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        selection_id = _require_canonical_text(row.get("selection_id"))
        grouped.setdefault(selection_id, []).append(row)
    folded: list[dict[str, object]] = []
    for selection_rows in grouped.values():
        first = selection_rows[0]
        if any(
            any(row.get(key) != first.get(key) for key in _SOURCE_DOCUMENT_IDENTITY_KEYS)
            for row in selection_rows[1:]
        ):
            _reject("C5_SOURCE_SELECTION_IDENTITY_MISMATCH")
        page_groups: dict[int, list[dict[str, object]]] = {}
        for row in selection_rows:
            page_number = row.get("page_number")
            if type(page_number) is not int or page_number <= 0:
                _reject("C5_SOURCE_SELECTION_UNREPLAYABLE")
            page_groups.setdefault(page_number, []).append(row)
        for page_rows in page_groups.values():
            page_first = page_rows[0]
            if any(
                any(row.get(key) != page_first.get(key) for key in _SOURCE_PAGE_IDENTITY_KEYS)
                for row in page_rows[1:]
            ):
                _reject("C5_SOURCE_SELECTION_IDENTITY_MISMATCH")
            selection_type = first.get("selection_type")
            if selection_type == "TEXT_SPAN":
                folded.extend(_fold_text_source_rows(page_rows))
            elif selection_type == "TABLE_SLICE":
                folded.extend(_fold_table_source_rows(page_rows))
            else:
                _reject("C5_SOURCE_SELECTION_UNREPLAYABLE")
    return folded


def _make_preview(
    *,
    candidate: dict[str, object],
    companion: dict[str, object],
    terminal: dict[str, object],
    field_attempt: dict[str, object],
    revision_set: dict[str, object],
) -> dict[str, object]:
    pack = make_medical_schema_pack_596_1()
    rows = approved_schema_rows()
    candidate_fields = _as_objects(candidate.get("fields"), "C5_CANDIDATE_INVALID")
    attempt_rows = _as_objects(field_attempt.get("rows"), "C5_FIELD_ATTEMPT_INVALID")
    coordinate_rows = _as_objects(companion.get("coordinate_rows"), "C5_COMPANION_INVALID")
    ordered_roles = _as_strings(
        revision_set.get("ordered_roles"), "C5_REVISION_SET_INVALID"
    )
    if (
        candidate.get("contract") != "schema67-candidate.v2"
        or candidate.get("product_version_id") != APPROVED_PRODUCT_VERSION_ID
        or candidate.get("ordered_field_ids") != list(APPROVED_ORDERED_FIELD_IDS)
        or len(candidate_fields) != 67
        or [field.get("field_id") for field in candidate_fields]
        != list(APPROVED_ORDERED_FIELD_IDS)
        or len(attempt_rows) != 67
    ):
        _reject("C5_CANDIDATE_INVALID")
    attempts_by_field = {cast(str, row["field_id"]): row for row in attempt_rows}
    coordinates_by_field: dict[str, list[dict[str, object]]] = {
        field_id: [] for field_id in APPROVED_ORDERED_FIELD_IDS
    }
    for coordinate in coordinate_rows:
        field_id = coordinate.get("field_id")
        if type(field_id) is not str or field_id not in coordinates_by_field:
            _reject("C5_COMPANION_INVALID")
        coordinates_by_field[field_id].append(coordinate)

    field_to_section = {
        field_id: section.section_id
        for section in pack.sections
        for field_id in section.ordered_field_ids
    }
    materialized_fields: list[dict[str, object]] = []
    for row, candidate_field in zip(rows, candidate_fields, strict=True):
        field_id = row.field_id
        state = candidate_field.get("state")
        attempt = attempts_by_field.get(field_id)
        if attempt is None or attempt.get("final_state") != state:
            _reject("C5_FIELD_JOIN_INVALID")
        selections = coordinates_by_field[field_id]
        coordinate_hashes = [
            canonical_hash("schema67-coordinate-evidence.815.v1", source)
            for source in selections
        ]
        if attempt.get("coordinate_evidence_sha256s") != coordinate_hashes:
            _reject("C5_FIELD_JOIN_INVALID")
        if state == "present":
            value_snapshot = candidate_field.get("value_snapshot")
            if type(value_snapshot) is not str or not value_snapshot.strip() or not selections:
                _reject("C5_FIELD_STATE_INVALID")
            preview_state = "present"
            typed_reason: object = None
        elif state == "absent_explicitly":
            value_snapshot = candidate_field.get("value_snapshot")
            if (
                type(value_snapshot) is not str
                or not value_snapshot.strip()
                or not selections
            ):
                _reject("C5_FIELD_STATE_INVALID")
            preview_state = "absent"
            typed_reason = None
        elif state == "unknown":
            typed_reason = attempt.get("typed_reason")
            if (
                candidate_field.get("value_snapshot") is not None
                or type(typed_reason) is not str
                or not typed_reason
                or selections
            ):
                _reject("C5_FIELD_STATE_INVALID")
            preview_state = "unknown"
            value_snapshot = None
        else:
            _reject("C5_FIELD_STATE_INVALID")
        materialized_fields.append(
            {
                "schema_order": row.ordinal,
                "section_id": field_to_section[field_id],
                "field_id": field_id,
                "display_name": row.field_name,
                "state": preview_state,
                "value_snapshot": value_snapshot,
                "typed_reason": typed_reason,
                "source_selections": _fold_source_rows(selections),
            }
        )

    coordinate_role_set = {cast(str, row["source_role"]) for row in coordinate_rows}
    coordinate_roles = [role for role in ordered_roles if role in coordinate_role_set]
    missing_roles = [role for role in ordered_roles if role not in coordinate_role_set]
    preview: dict[str, object] = {
        "contract": _PREVIEW_CONTRACT,
        "experiment_id": _require_uuid(terminal.get("experiment_id")),
        "candidate_sha256": _require_sha(candidate.get("candidate_sha256")),
        "companion_sha256": _require_sha(companion.get("companion_sha256")),
        "terminal_sha256": _require_sha(terminal.get("terminal_sha256")),
        "revision_set_sha256": _require_sha(revision_set.get("revision_set_sha256")),
        "quality_status": "NOT_EVALUATED",
        "mvp_status": "NOT_ACCEPTED",
        "publishing": False,
        "coordinate_source_roles": coordinate_roles,
        "source_roles_without_coordinate_selections": missing_roles,
        "product": {
            "entity_id": MEDICAL_ENTITY_ID,
            "entity_version_id": MEDICAL_VERSION_ID,
            "product_version_id": APPROVED_PRODUCT_VERSION_ID,
            "display_name": _PRODUCT_DISPLAY_NAME,
        },
        "ordered_section_ids": [section.section_id for section in pack.sections],
        "sections": [
            {
                "section_id": section.section_id,
                "display_name": section.display_name,
                "ordered_field_ids": list(section.ordered_field_ids),
            }
            for section in pack.sections
        ],
        "fields": materialized_fields,
    }
    preview["preview_sha256"] = _object_hash(_PREVIEW_CONTRACT, preview)
    if terminal.get("terminal_sha256") != preview["terminal_sha256"]:
        _reject("C5_FIELD_JOIN_INVALID")
    return preview


def _write_member(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _rename_no_replace(source: Path, target: Path) -> None:
    if sys.platform == "darwin":
        library = ctypes.CDLL(None, use_errno=True)
        renamex_np = library.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(os.fsencode(source), os.fsencode(target), 0x00000004)
    elif sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = library.renameat2
        except AttributeError:
            raise OSError(
                errno.ENOTSUP,
                "atomic no-replace rename is unavailable",
                target,
            ) from None
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(target),
            0x00000001,
        )
    else:
        raise OSError(
            errno.ENOTSUP,
            "atomic no-replace rename is unavailable",
            target,
        )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(target)
        raise OSError(error_number, os.strerror(error_number), target)


def _validate_source(
    source: dict[str, object],
    *,
    owning_field_id: str,
    revision_rows: dict[str, tuple[str, str, str]],
) -> None:
    if set(source) != _SOURCE_KEYS or source.get("field_id") != owning_field_id:
        _reject("C5_SOURCE_SELECTION_INVALID")
    for key in ("selection_id", "field_id", "source_role"):
        _require_canonical_text(source.get(key))
    role = cast(str, source["source_role"])
    if role not in revision_rows:
        _reject("C5_SOURCE_SELECTION_INVALID")
    source_revision_id, original_file_sha256, _revision_parse_manifest_sha256 = (
        revision_rows[role]
    )
    if (
        _require_sha(source.get("source_revision_id")) != source_revision_id
        or _require_sha(source.get("original_file_sha256")) != original_file_sha256
        or not _is_sha256(source.get("parse_manifest_sha256"))
        or type(source.get("page_number")) is not int
        or cast(int, source["page_number"]) <= 0
        or source.get("coordinate_space") != "PDF_POINTS_TOP_LEFT_V1"
    ):
        _reject("C5_SOURCE_SELECTION_INVALID")
    _require_decimal(source.get("page_width_points"), positive=True)
    _require_decimal(source.get("page_height_points"), positive=True)
    bbox = _require_bbox(source.get("bbox"))
    rect_values = source.get("rects")
    if type(rect_values) is not list or not rect_values:
        _reject("C5_SOURCE_SELECTION_INVALID")
    rects = [_require_bbox(item) for item in cast(list[object], rect_values)]
    if (
        Decimal(bbox[0]) != min(Decimal(rect[0]) for rect in rects)
        or Decimal(bbox[1]) != min(Decimal(rect[1]) for rect in rects)
        or Decimal(bbox[2]) != max(Decimal(rect[2]) for rect in rects)
        or Decimal(bbox[3]) != max(Decimal(rect[3]) for rect in rects)
    ):
        _reject("C5_SOURCE_SELECTION_INVALID")
    for key in ("block_id", "span_id", "table_id", "table_slice_id"):
        if source.get(key) is not None:
            _require_canonical_text(source.get(key))
    cell_ids = _as_strings(source.get("cell_ids"), "C5_SOURCE_SELECTION_INVALID")
    if len(cell_ids) != len(set(cell_ids)):
        _reject("C5_SOURCE_SELECTION_INVALID")
    for cell_id in cell_ids:
        _require_canonical_text(cell_id)
    quote = _require_canonical_text(source.get("quote"), allow_edge_space=True)
    if _require_sha(source.get("quote_sha256")) != _sha256(quote.encode("utf-8")):
        _reject("C5_SOURCE_SELECTION_INVALID")
    page_text_char_start = source.get("page_text_char_start")
    page_text_char_end = source.get("page_text_char_end")
    if page_text_char_start is None or page_text_char_end is None:
        if page_text_char_start is not None or page_text_char_end is not None:
            _reject("C5_SOURCE_SELECTION_INVALID")
    elif (
        type(page_text_char_start) is not int
        or type(page_text_char_end) is not int
        or page_text_char_start < 0
        or page_text_char_start >= page_text_char_end
    ):
        _reject("C5_SOURCE_SELECTION_INVALID")


def _validate_preview(
    preview: dict[str, object],
    *,
    revision_rows: dict[str, tuple[str, str, str]],
    companion_coordinate_rows: list[dict[str, object]],
) -> None:
    if set(preview) != _PREVIEW_KEYS:
        _reject("C5_PREVIEW_INVALID")
    preview_hash = _require_sha(preview.get("preview_sha256"))
    if (
        preview.get("contract") != _PREVIEW_CONTRACT
        or preview_hash
        != _object_hash(_PREVIEW_CONTRACT, _without(preview, "preview_sha256"))
        or preview.get("quality_status") != "NOT_EVALUATED"
        or preview.get("mvp_status") != "NOT_ACCEPTED"
        or preview.get("publishing") is not False
    ):
        _reject("C5_PREVIEW_INVALID")
    _require_uuid(preview.get("experiment_id"))
    for key in (
        "candidate_sha256",
        "companion_sha256",
        "terminal_sha256",
        "revision_set_sha256",
    ):
        _require_sha(preview.get(key))
    product = _as_object(preview.get("product"), "C5_PREVIEW_INVALID")
    if set(product) != _PRODUCT_KEYS or product != {
        "entity_id": MEDICAL_ENTITY_ID,
        "entity_version_id": MEDICAL_VERSION_ID,
        "product_version_id": APPROVED_PRODUCT_VERSION_ID,
        "display_name": _PRODUCT_DISPLAY_NAME,
    }:
        _reject("C5_PREVIEW_INVALID")
    pack = make_medical_schema_pack_596_1()
    sections = _as_objects(preview.get("sections"), "C5_PREVIEW_INVALID")
    fields = _as_objects(preview.get("fields"), "C5_PREVIEW_INVALID")
    expected_section_ids = [section.section_id for section in pack.sections]
    if (
        preview.get("ordered_section_ids") != expected_section_ids
        or len(sections) != 7
        or len(fields) != 67
        or [field.get("field_id") for field in fields]
        != list(APPROVED_ORDERED_FIELD_IDS)
        or [field.get("schema_order") for field in fields] != list(range(1, 68))
    ):
        _reject("C5_PREVIEW_INVALID")
    field_to_section: dict[str, str] = {}
    for section, expected in zip(sections, pack.sections, strict=True):
        if set(section) != _SECTION_KEYS or section != {
            "section_id": expected.section_id,
            "display_name": expected.display_name,
            "ordered_field_ids": list(expected.ordered_field_ids),
        }:
            _reject("C5_PREVIEW_INVALID")
        field_to_section.update(
            {field_id: expected.section_id for field_id in expected.ordered_field_ids}
        )
    source_roles = _as_strings(
        preview.get("coordinate_source_roles"), "C5_PREVIEW_INVALID"
    )
    missing_roles = _as_strings(
        preview.get("source_roles_without_coordinate_selections"),
        "C5_PREVIEW_INVALID",
    )
    ordered_roles = list(revision_rows)
    if (
        len(source_roles) != len(set(source_roles))
        or len(missing_roles) != len(set(missing_roles))
        or [role for role in ordered_roles if role in source_roles] != source_roles
        or [role for role in ordered_roles if role not in source_roles] != missing_roles
        or set(source_roles).intersection(missing_roles)
        or set(source_roles).union(missing_roles) != set(ordered_roles)
    ):
        _reject("C5_PREVIEW_INVALID")
    display_names = {row.field_id: row.field_name for row in approved_schema_rows()}
    coordinates_by_selection_id: dict[str, dict[str, object]] = {}
    for coordinate in companion_coordinate_rows:
        selection_id = coordinate.get("selection_id")
        if type(selection_id) is not str or selection_id in coordinates_by_selection_id:
            _reject("C5_SOURCE_SELECTION_INVALID")
        coordinates_by_selection_id[selection_id] = coordinate
    selected_roles: list[str] = []
    for field in fields:
        if set(field) != _FIELD_KEYS:
            _reject("C5_FIELD_INVALID")
        field_id = field.get("field_id")
        if type(field_id) is not str or (
            field.get("section_id") != field_to_section[field_id]
            or field.get("display_name") != display_names[field_id]
        ):
            _reject("C5_FIELD_INVALID")
        sources = _as_objects(field.get("source_selections"), "C5_FIELD_INVALID")
        for source in sources:
            _validate_source(source, owning_field_id=field_id, revision_rows=revision_rows)
            matching_coordinate = coordinates_by_selection_id.get(
                cast(str, source["selection_id"])
            )
            if matching_coordinate is None:
                _reject("C5_SOURCE_SELECTION_INVALID")
            if source != _source_projection(matching_coordinate):
                _reject("C5_SOURCE_SELECTION_INVALID")
            selection_type = matching_coordinate.get("selection_type")
            char_start = source.get("page_text_char_start")
            char_end = source.get("page_text_char_end")
            if selection_type == "TEXT_SPAN":
                if (
                    type(char_start) is not int
                    or type(char_end) is not int
                    or char_start < 0
                    or char_start >= char_end
                ):
                    _reject("C5_SOURCE_SELECTION_INVALID")
            elif selection_type == "TABLE_SLICE":
                if char_start is not None or char_end is not None:
                    _reject("C5_SOURCE_SELECTION_INVALID")
            else:
                _reject("C5_SOURCE_SELECTION_INVALID")
            selected_roles.append(cast(str, source["source_role"]))
        state = field.get("state")
        if state == "present":
            if (
                type(field.get("value_snapshot")) is not str
                or not cast(str, field["value_snapshot"]).strip()
                or field.get("typed_reason") is not None
                or not sources
            ):
                _reject("C5_FIELD_INVALID")
            _require_canonical_text(field.get("value_snapshot"))
        elif state == "absent":
            if (
                type(field.get("value_snapshot")) is not str
                or not cast(str, field["value_snapshot"]).strip()
                or field.get("typed_reason") is not None
                or not sources
            ):
                _reject("C5_FIELD_INVALID")
            _require_canonical_text(field.get("value_snapshot"))
        elif state == "unknown":
            if (
                field.get("value_snapshot") is not None
                or type(field.get("typed_reason")) is not str
                or sources
            ):
                _reject("C5_FIELD_INVALID")
            _require_canonical_text(field.get("typed_reason"))
        else:
            _reject("C5_FIELD_INVALID")
    if [role for role in ordered_roles if role in set(selected_roles)] != source_roles:
        _reject("C5_PREVIEW_INVALID")


def _revision_rows(
    revision_set: dict[str, object],
    *,
    bundle_root: Path,
) -> dict[str, tuple[str, str, str]]:
    rows: dict[str, tuple[str, str, str]] = {}
    ordered_roles = _as_strings(
        revision_set.get("ordered_roles"), "C5_REVISION_SET_INVALID"
    )
    for role, item in zip(
        ordered_roles,
        _as_objects(revision_set.get("items"), "C5_REVISION_SET_INVALID"),
        strict=True,
    ):
        manifest_name = item.get("manifest_file")
        if item.get("role") != role or type(manifest_name) is not str:
            _reject("C5_REVISION_SET_INVALID")
        item_manifest = _decode_json(
            _read_regular_file(bundle_root, manifest_name),
            "C5_REVISION_SET_INVALID",
        )
        rows[role] = (
            _require_sha(item_manifest.get("compiler_source_revision_id")),
            _require_sha(item.get("material_file_sha256")),
            _require_sha(item_manifest.get("parse_manifest_sha256")),
        )
    return rows


def _make_go_compatible_result_manifest(
    *,
    successor_result: dict[str, object],
    candidate: dict[str, object],
    companion: dict[str, object],
    terminal: dict[str, object],
    field_attempt: dict[str, object],
    c3_bytes: dict[str, bytes],
    frozen_identity: dict[str, str],
) -> bytes:
    source_root = Path(
        _require_canonical_text(successor_result.get("source_artifact_root"))
    )
    source_bytes = _read_regular_file(source_root, "result-manifest.json")
    source_result = _decode_json(source_bytes, "C5_RESULT_INVALID")
    source_identities = _as_object(
        source_result.get("identities"), "C5_RESULT_INVALID"
    )
    successor_identities = _as_object(
        successor_result.get("identities"), "C5_RESULT_INVALID"
    )
    source_git = _as_object(source_result.get("git"), "C5_RESULT_INVALID")
    source_candidate = _as_object(
        source_result.get("candidate"), "C5_RESULT_INVALID"
    )
    source_projection = _as_object(
        source_result.get("projection"), "C5_RESULT_INVALID"
    )
    source_effects = _as_object(source_result.get("effects"), "C5_RESULT_INVALID")
    source_counters = _as_object(
        source_result.get("counters"), "C5_RESULT_INVALID"
    )
    source_artifacts = _as_objects(
        source_result.get("artifacts"), "C5_RESULT_INVALID"
    )
    successor_raws = _as_strings(
        successor_result.get("raw_external_sha256s"), "C5_RESULT_INVALID"
    )
    source_raws = [
        _require_sha(artifact.get("sha256"))
        for artifact in source_artifacts
        if type(artifact.get("name")) is str
        and cast(str, artifact["name"]).startswith("raw-response-")
    ]
    if (
        set(source_result) != _RESULT_KEYS
        or source_result.get("contract")
        != "ec01-native-pdf-selection-result.815.v1"
        or source_result.get("status") != "SUCCEEDED"
        or source_result.get("failure_reason") is not None
        or _require_sha(source_result.get("self_sha256"))
        != _sha256(_canonical_bytes(_without(source_result, "self_sha256")))
        or any(
            source_identities.get(key) != successor_identities.get(key)
            for key in (
                "experiment_id",
                "execution_identity_sha256",
                "run_id",
                "attempt_id",
                "receipt_id",
            )
        )
        or source_git.get("head") != successor_identities.get("integration_head")
        or source_git.get("tree") != successor_identities.get("integration_tree")
        or source_candidate.get("attempted_field_count")
        != field_attempt.get("attempted_field_count")
        or source_candidate.get("provider_visible_field_count")
        != field_attempt.get("provider_visible_count")
        or source_candidate.get("real_model_output_count")
        != field_attempt.get("real_model_output_count")
        or source_candidate.get("code_deferred_field_count")
        != field_attempt.get("code_deferred_count")
        or source_candidate.get("dispositioned_field_count")
        != field_attempt.get("dispositioned_count")
        or source_projection.get("provider_visible_field_count")
        != field_attempt.get("provider_visible_count")
        or source_projection.get("code_deferred_field_count")
        != field_attempt.get("code_deferred_count")
        or source_projection.get("dispositioned_field_count")
        != field_attempt.get("dispositioned_count")
        or source_projection.get("selection_catalog_sha256")
        != companion.get("selection_catalog_sha256")
        or source_effects
        != {
            "database_writes": 0,
            "draft_review_publish_active_writes": 0,
            "git_writes": 0,
            "golden_c4_c5_p1_started": False,
            "knowledge_base_writes": 0,
            "migration_writes": 0,
        }
        or source_counters.get("initial_raw_count") != len(successor_raws)
        or source_counters.get("targeted_raw_count") != 0
        or source_raws != successor_raws
        or terminal.get("terminal_sha256") != frozen_identity["terminal_sha256"]
    ):
        _reject("C5_RESULT_INVALID")

    candidate_fields = _as_objects(candidate.get("fields"), "C5_CANDIDATE_INVALID")
    state_distribution: dict[str, int] = {}
    for field in candidate_fields:
        state = _require_canonical_text(field.get("state"))
        state_distribution[state] = state_distribution.get(state, 0) + 1

    result_candidate = _as_object(
        source_result.get("candidate"), "C5_RESULT_INVALID"
    )
    result_candidate.update(
        {
            "candidate_external_sha256": frozen_identity["candidate_file_sha256"],
            "candidate_internal_sha256": frozen_identity["candidate_sha256"],
            "coordinate_companion_external_sha256": frozen_identity[
                "companion_file_sha256"
            ],
            "coordinate_companion_internal_sha256": frozen_identity[
                "companion_sha256"
            ],
            "derivation_validation_external_sha256": frozen_identity[
                "formal_derivation_validation_sha256"
            ],
            "field_attempt_manifest_external_sha256": frozen_identity[
                "field_attempt_manifest_sha256"
            ],
            "state_distribution": state_distribution,
        }
    )
    result_terminal = _as_object(
        source_result.get("terminal"), "C5_RESULT_INVALID"
    )
    result_terminal.clear()
    result_terminal.update(
        {
            "internal_sha256": frozen_identity["terminal_sha256"],
            "present": True,
            "status": "SUCCEEDED",
        }
    )
    member_hashes = {
        "formal-candidate.json": frozen_identity["candidate_file_sha256"],
        "coordinate-evidence-companion.json": frozen_identity[
            "companion_file_sha256"
        ],
        "terminal.json": frozen_identity["terminal_file_sha256"],
        "field-attempt-manifest.json": frozen_identity[
            "field_attempt_manifest_sha256"
        ],
        "formal-derivation-validation.json": frozen_identity[
            "formal_derivation_validation_sha256"
        ],
    }
    matched_artifacts: set[str] = set()
    for artifact in source_artifacts:
        name = artifact.get("name")
        if type(name) is str and name in member_hashes:
            artifact["sha256"] = member_hashes[name]
            artifact["byte_size"] = len(c3_bytes[name])
            matched_artifacts.add(name)
    if matched_artifacts != set(member_hashes):
        _reject("C5_RESULT_INVALID")
    source_result.pop("self_sha256")
    source_result["self_sha256"] = _sha256(_canonical_bytes(source_result))
    return _canonical_bytes(source_result)


def _candidate_evidence_authority_member_bytes(
    *,
    candidate: dict[str, object],
    authority: Schema67CandidateEvidenceAuthorityV1,
) -> bytes:
    """Accept only the original factory-backed Candidate companion."""

    try:
        if type(authority) is not Schema67CandidateEvidenceAuthorityV1:
            raise TypeError
        _require_factory_authority(authority)
        exact = Schema67CandidateEvidenceAuthorityV1.model_validate(
            authority.model_dump(mode="python")
        )
    except Exception:
        _reject("C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    raw = _canonical_bytes(exact.model_dump(mode="json"))
    candidate_wire = _decode_json(
        _canonical_bytes(candidate), "C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID"
    )
    _validate_persisted_candidate_evidence_authority(raw=raw, candidate=candidate_wire)
    return raw


def _validate_persisted_candidate_evidence_authority(
    *,
    raw: bytes,
    candidate: dict[str, object],
) -> Schema67CandidateEvidenceAuthorityV1:
    """Replay persisted authority hashes and its exact Candidate evidence joins."""

    candidate = _decode_json(
        _canonical_bytes(candidate), "C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID"
    )
    try:
        exact = Schema67CandidateEvidenceAuthorityV1.model_validate_json(raw)
    except (TypeError, ValueError, ValidationError):
        _reject("C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    if raw != _canonical_bytes(exact.model_dump(mode="json")) or (
        exact.candidate_sha256 != candidate.get("candidate_sha256")
    ):
        _reject("C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    source_roles = _as_objects(
        candidate.get("source_roles"), "C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID"
    )
    if tuple(
        (item.source_role, item.source_sha256) for item in exact.source_authorities
    ) != tuple((row.get("role"), row.get("source_sha256")) for row in source_roles):
        _reject("C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    fields = _as_objects(
        candidate.get("fields"), "C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID"
    )
    receipts = _as_objects(
        candidate.get("evidence_receipts"),
        "C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID",
    )
    if len(fields) != len(receipts):
        _reject("C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    expected: list[tuple[object, ...]] = []
    for field, receipt in zip(fields, receipts, strict=True):
        if field.get("field_id") != receipt.get("field_id"):
            _reject("C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
        for evidence in _as_objects(
            field.get("evidence"), "C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID"
        ):
            locator = _as_object(
                evidence.get("locator"),
                "C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID",
            )
            expected.append(
                (
                    field.get("field_id"),
                    receipt.get("receipt_hash"),
                    evidence.get("source_sha256"),
                    evidence.get("parsed_document_hash"),
                    evidence.get("parse_manifest_hash"),
                    evidence.get("parse_attempt_id"),
                    locator.get("subject_ref"),
                    evidence.get("page_number"),
                    locator.get("content_snapshot_sha256"),
                    schema_wiki_sha256(
                        "schema-wiki-text.v1",
                        {"text": evidence.get("quote_snapshot")},
                    ),
                )
            )
    actual = [
        (
            item.field_id,
            item.evidence_receipt_sha256,
            item.source_sha256,
            item.parsed_document_sha256,
            item.parse_manifest_sha256,
            item.evidence_parse_attempt_id,
            item.locator_ref,
            item.page_number,
            item.locator_content_sha256,
            item.quote_sha256,
        )
        for item in exact.join_receipts
    ]
    if actual != expected:
        _reject("C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    return exact


def build_schema_wiki_c5_preview_bundle_815(
    *,
    c3_input_root: Path,
    revision_set_root: Path,
    output_directory: Path,
    candidate_evidence_authority: Schema67CandidateEvidenceAuthorityV1 | None = None,
) -> Path:
    """Freshly validate frozen C3 bytes and atomically persist one C5 version."""

    if (
        not isinstance(c3_input_root, Path)
        or not isinstance(revision_set_root, Path)
        or not isinstance(output_directory, Path)
        or not output_directory.is_absolute()
    ):
        _reject("C5_PATH_INVALID")
    if output_directory.exists() or output_directory.is_symlink():
        raise FileExistsError(output_directory)
    (
        c3_bytes,
        revision_bytes,
        candidate,
        companion,
        terminal,
        field_attempt,
        frozen_identity,
    ) = _validate_frozen_inputs(
        c3_root=c3_input_root,
        revision_root=revision_set_root,
        require_successor_reports=True,
    )
    revision_set = _decode_json(
        revision_bytes["revision-set.json"], "C5_REVISION_SET_INVALID"
    )
    preview = _make_preview(
        candidate=candidate,
        companion=companion,
        terminal=terminal,
        field_attempt=field_attempt,
        revision_set=revision_set,
    )
    preview_bytes = _canonical_bytes(preview)
    source_result = _decode_json(c3_bytes["result-manifest.json"], "C5_RESULT_INVALID")
    if source_result.get("contract") == "ec01-c3-hydration-successor-result.815.v1":
        c3_bytes = dict(c3_bytes)
        c3_bytes["result-manifest.json"] = _make_go_compatible_result_manifest(
            successor_result=source_result,
            candidate=candidate,
            companion=companion,
            terminal=terminal,
            field_attempt=field_attempt,
            c3_bytes=c3_bytes,
            frozen_identity=frozen_identity,
        )
    all_members = {
        "preview.json": preview_bytes,
        **c3_bytes,
        **revision_bytes,
    }
    member_names = _MEMBER_NAMES
    if candidate_evidence_authority is not None:
        all_members[_EVIDENCE_AUTHORITY_MEMBER_NAME] = (
            _candidate_evidence_authority_member_bytes(
                candidate=candidate,
                authority=candidate_evidence_authority,
            )
        )
        member_names = _EVIDENCE_AUTHORITY_MEMBER_NAMES
    members = [
        {
            "name": name,
            "sha256": _sha256(all_members[name]),
            "size_bytes": len(all_members[name]),
        }
        for name in member_names
    ]
    manifest: dict[str, object] = {
        "contract": _MANIFEST_CONTRACT,
        "tenant_id": _TENANT_ID,
        "wiki_kb_id": _WIKI_KB_ID,
        "experiment_id": frozen_identity["experiment_id"],
        "candidate_sha256": frozen_identity["candidate_sha256"],
        "candidate_file_sha256": frozen_identity["candidate_file_sha256"],
        "companion_sha256": frozen_identity["companion_sha256"],
        "companion_file_sha256": frozen_identity["companion_file_sha256"],
        "terminal_sha256": frozen_identity["terminal_sha256"],
        "terminal_file_sha256": frozen_identity["terminal_file_sha256"],
        "field_attempt_manifest_sha256": frozen_identity[
            "field_attempt_manifest_sha256"
        ],
        "formal_derivation_validation_sha256": frozen_identity[
            "formal_derivation_validation_sha256"
        ],
        "revision_set_sha256": frozen_identity["revision_set_sha256"],
        "quality_status": "NOT_EVALUATED",
        "mvp_status": "NOT_ACCEPTED",
        "publishing": False,
        "members": members,
    }
    if candidate_evidence_authority is not None:
        authority_bytes = all_members[_EVIDENCE_AUTHORITY_MEMBER_NAME]
        manifest["candidate_evidence_authority_sha256"] = (
            candidate_evidence_authority.authority_sha256
        )
        manifest["candidate_evidence_authority_file_sha256"] = _sha256(
            authority_bytes
        )
    manifest["manifest_sha256"] = _object_hash(_MANIFEST_CONTRACT, manifest)
    output_directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = output_directory.parent / f".{output_directory.name}.staging-{uuid.uuid4()}"
    try:
        staging.mkdir(mode=0o700)
        os.chmod(staging, 0o700)
        for name in member_names:
            _write_member(staging / name, all_members[name])
        _write_member(staging / "manifest.json", _canonical_bytes(manifest))
        directory_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        _rename_no_replace(staging, output_directory)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return output_directory / "manifest.json"


def validate_schema_wiki_c5_preview_bundle_815(
    manifest_path: Path,
) -> dict[str, object]:
    """Fresh-open one exact persisted bundle and replay all hashes and joins."""

    if (
        not isinstance(manifest_path, Path)
        or not manifest_path.is_absolute()
        or manifest_path.name != "manifest.json"
    ):
        _reject("C5_MANIFEST_PATH_INVALID")
    bundle_root = manifest_path.parent
    try:
        if (
            not stat.S_ISDIR(bundle_root.lstat().st_mode)
            or stat.S_IMODE(bundle_root.stat().st_mode) != 0o700
        ):
            _reject("C5_BUNDLE_METADATA_INVALID")
        names = sorted(path.name for path in bundle_root.iterdir())
    except OSError:
        _reject("C5_BUNDLE_NOT_READY")
    manifest_bytes = _read_regular_file(bundle_root, "manifest.json")
    manifest = _decode_json(manifest_bytes, "C5_MANIFEST_INVALID")
    manifest_keys = frozenset(manifest)
    if manifest_keys == _MANIFEST_KEYS:
        member_names = _MEMBER_NAMES
    elif manifest_keys == _EVIDENCE_AUTHORITY_MANIFEST_KEYS:
        member_names = _EVIDENCE_AUTHORITY_MEMBER_NAMES
    else:
        _reject("C5_MANIFEST_INVALID")
    if names != sorted((*member_names, "manifest.json")):
        _reject("C5_BUNDLE_MEMBER_SET_INVALID")
    for name in (*member_names, "manifest.json"):
        path = bundle_root / name
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            _reject("C5_BUNDLE_METADATA_INVALID")
    if manifest_bytes != _canonical_bytes(manifest):
        _reject("C5_MANIFEST_INVALID")
    manifest_hash = _require_sha(manifest.get("manifest_sha256"))
    members = _as_objects(manifest.get("members"), "C5_MANIFEST_INVALID")
    if (
        manifest.get("contract") != _MANIFEST_CONTRACT
        or manifest_hash
        != _object_hash(_MANIFEST_CONTRACT, _without(manifest, "manifest_sha256"))
        or manifest.get("tenant_id") != _TENANT_ID
        or manifest.get("wiki_kb_id") != _WIKI_KB_ID
        or manifest.get("quality_status") != "NOT_EVALUATED"
        or manifest.get("mvp_status") != "NOT_ACCEPTED"
        or manifest.get("publishing") is not False
        or len(members) != len(member_names)
        or [member.get("name") for member in members] != list(member_names)
    ):
        _reject("C5_MANIFEST_INVALID")
    for member, name in zip(members, member_names, strict=True):
        payload = _read_regular_file(bundle_root, name)
        if (
            set(member) != _MEMBER_KEYS
            or member.get("name") != name
            or not _is_sha256(member.get("sha256"))
            or member.get("sha256") != _sha256(payload)
            or type(member.get("size_bytes")) is not int
            or cast(int, member["size_bytes"]) <= 0
            or member.get("size_bytes") != len(payload)
        ):
            _reject("C5_MANIFEST_MEMBER_INVALID")

    (
        _,
        _,
        candidate,
        companion,
        terminal,
        field_attempt,
        frozen_identity,
    ) = _validate_frozen_inputs(
        c3_root=bundle_root,
        revision_root=bundle_root,
        require_successor_reports=False,
    )
    if any(
        manifest.get(key) != value for key, value in frozen_identity.items()
    ):
        _reject("C5_MANIFEST_INVALID")
    if member_names == _EVIDENCE_AUTHORITY_MEMBER_NAMES:
        authority_raw = _read_regular_file(
            bundle_root, _EVIDENCE_AUTHORITY_MEMBER_NAME
        )
        authority = _validate_persisted_candidate_evidence_authority(
            raw=authority_raw,
            candidate=candidate,
        )
        if (
            manifest.get("candidate_evidence_authority_sha256")
            != authority.authority_sha256
            or manifest.get("candidate_evidence_authority_file_sha256")
            != _sha256(authority_raw)
        ):
            _reject("C5_MANIFEST_INVALID")
    revision_set = _decode_json(
        _read_regular_file(bundle_root, "revision-set.json"), "C5_REVISION_SET_INVALID"
    )
    rows = _revision_rows(revision_set, bundle_root=bundle_root)
    preview_bytes = _read_regular_file(bundle_root, "preview.json")
    preview = _decode_json(preview_bytes, "C5_PREVIEW_INVALID")
    if preview_bytes != _canonical_bytes(preview):
        _reject("C5_PREVIEW_INVALID")
    _validate_preview(
        preview,
        revision_rows=rows,
        companion_coordinate_rows=_as_objects(
            companion.get("coordinate_rows"), "C5_COMPANION_INVALID"
        ),
    )
    if preview != _make_preview(
        candidate=candidate,
        companion=companion,
        terminal=terminal,
        field_attempt=field_attempt,
        revision_set=revision_set,
    ):
        _reject("C5_PREVIEW_PROJECTION_DRIFT")
    return manifest


__all__ = [
    "build_schema_wiki_c5_preview_bundle_815",
    "validate_schema_wiki_c5_preview_bundle_815",
]
