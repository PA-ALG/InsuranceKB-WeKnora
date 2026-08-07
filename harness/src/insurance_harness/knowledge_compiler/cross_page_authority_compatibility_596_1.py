"""596-1-only replay of the frozen 089 -> 086 -> 090 authority seams."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal, Never, cast

from insurance_harness.canonical import CanonicalEncodingError, canonical_hash

TERMS_SOURCE_SHA256: Final = (
    "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
)
RATE_TABLE_SOURCE_SHA256: Final = (
    "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
)
_CORRECTION_PATH: Final = (
    "harness/src/insurance_harness/knowledge_compiler/"
    "mineru_cross_page_binding_596_1.py"
)
_PARSER_ID: Final = "mineru-cloud-pipeline"
_PARSER_BUILD_ID: Final = "mineru-cloud:3.4.4:pipeline"
_PARSER_CONFIG_HASH: Final = hashlib.sha256(b"mineru-3.4.4-pipeline-config").hexdigest()
_POLICY_086: Final = {
    "contract": "mineru-derived-cross-page-policy.v1",
    "relation_kinds": ["section", "table"],
    "native_observation_count": 1,
    "typed_marker_authority": "future-089-typed-marker-replay",
    "marker_kind": "cross_page",
    "page_delta": 1,
    "column_count": "exact",
    "header_coverage": "complete-non-overlapping",
    "header_content_structure_span": "exact",
    "candidate_cardinality": 1,
    "section_endpoint_mapping": "typed-marker-exact-block-refs",
    "text_semantics": "forbidden",
}
_POLICY_SHA256_086: Final = canonical_hash(
    "mineru-derived-cross-page-policy.v1", _POLICY_086
)

_SOURCE_KEYS: Final = {
    "role",
    "source_sha256",
    "relation_kind_086",
    "relation_kind_090",
    "marker_provenance_089",
    "binding_086",
    "injection_090",
}
_MARKER_PROVENANCE_KEYS: Final = {
    "contract",
    "source_sha256",
    "parser_model",
    "mineru_version",
    "raw_zip_sha256",
    "native_member_sha256",
    "marker_count",
    "markers",
    "replay_digest_sha256",
}
_MARKER_KEYS: Final = {
    "marker_kind",
    "page_index",
    "structural_path_sha256",
    "node_type",
    "local_index",
    "marker_sha256",
}
_BINDING_KEYS: Final = {
    "contract",
    "status",
    "provenance",
    "relation_kind",
    "source_sha256",
    "parser_identity_sha256",
    "parser_config_sha256",
    "raw_structure_sha256",
    "artifact_sha256",
    "policy_sha256",
    "source_endpoint",
    "target_endpoint",
    "replay_digest_sha256",
}
_ENDPOINT_KEYS: Final = {"endpoint_kind", "endpoint_id", "page_number"}
_INJECTION_KEYS: Final = {
    "contract",
    "relation_id",
    "relation_kind",
    "source_sha256",
    "parser_id",
    "parser_build_id",
    "parser_config_hash",
    "raw_artifact_sha256",
    "sanitized_structure_sha256",
    "material_profile_binding_hash",
    "policy_context_hash",
    "replay_context_hash",
    "endpoint_ids",
    "binding_hash",
}


@dataclass(frozen=True)
class CompatibilityMatrixRowV1:
    role: Literal["terms", "rate_table"]
    boundary: Literal["089_TO_086", "086_TO_090"]
    status: Literal["COMPATIBLE", "BLOCKED"]
    reason_code: str
    compatible_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    incompatible_fields: tuple[str, ...]
    correction_owner: Literal["086"] = "086"
    correction_path: str = _CORRECTION_PATH


@dataclass(frozen=True)
class CompatibilityReplayResultV1:
    status: Literal["COMPATIBILITY_VERIFIED", "BLOCKED"]
    blocked_boundary: Literal["VECTOR", "089_TO_086", "086_TO_090"] | None
    reason_code: str | None
    matrix: tuple[CompatibilityMatrixRowV1, ...]
    vector_sha256: str | None
    result_sha256: str


class _VectorFailure(Exception):
    def __init__(
        self,
        boundary: Literal["VECTOR", "089_TO_086", "086_TO_090"],
        reason_code: str,
    ) -> None:
        self.boundary = boundary
        self.reason_code = reason_code
        super().__init__(reason_code)


def _fail(
    boundary: Literal["VECTOR", "089_TO_086", "086_TO_090"], reason: str
) -> Never:
    raise _VectorFailure(boundary, reason)


def _hash_label(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _is_hash(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _go_domain_hash(domain: str, value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode(
        "ascii"
    )
    return hashlib.sha256(domain.encode("ascii") + b"\0" + payload).hexdigest()


def _marker(role: str, source_sha256: str, node_type: str) -> dict[str, Any]:
    path_hash = _hash_label(f"{role}-structural-path")
    native_hash = _hash_label(f"{role}-native-member")
    preimage = {
        "contract": "mineru-native-cross-page-marker-provenance.v1",
        "source_sha256": source_sha256,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "native_member_sha256": native_hash,
        "marker_kind": "cross_page",
        "page_index": 0,
        "structural_path_sha256": path_hash,
        "node_type": node_type,
        "local_index": 0,
    }
    item = {
        "marker_kind": "cross_page",
        "page_index": 0,
        "structural_path_sha256": path_hash,
        "node_type": node_type,
        "local_index": 0,
        "marker_sha256": _go_domain_hash(
            "mineru-cross-page-marker-evidence.v1", preimage
        ),
    }
    result: dict[str, Any] = {
        "contract": "mineru-native-cross-page-marker-provenance.v1",
        "source_sha256": source_sha256,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": _hash_label(f"{role}-raw-zip"),
        "native_member_sha256": native_hash,
        "marker_count": 1,
        "markers": [item],
    }
    result["replay_digest_sha256"] = _go_domain_hash(
        "mineru-cross-page-marker-provenance-replay.v1", result
    )
    return result


def _binding(role: str, source_sha256: str, kind: str) -> dict[str, Any]:
    endpoint_kind = "block" if kind == "section" else "table"
    result: dict[str, Any] = {
        "contract": "cross-page-relation-binding.v1",
        "status": "DERIVED_STRUCTURAL_BINDING_VERIFIED",
        "provenance": "DERIVED_STRUCTURAL_RELATION",
        "relation_kind": kind,
        "source_sha256": source_sha256,
        "parser_identity_sha256": _hash_label(f"{role}-parser-identity"),
        "parser_config_sha256": _PARSER_CONFIG_HASH,
        "raw_structure_sha256": _hash_label(f"{role}-raw-structure"),
        "artifact_sha256": _hash_label(f"{role}-sanitized-structure"),
        "policy_sha256": _POLICY_SHA256_086,
        "source_endpoint": {
            "endpoint_kind": endpoint_kind,
            "endpoint_id": f"{endpoint_kind}-{role}-000000",
            "page_number": 1,
        },
        "target_endpoint": {
            "endpoint_kind": endpoint_kind,
            "endpoint_id": f"{endpoint_kind}-{role}-000001",
            "page_number": 2,
        },
        "replay_digest_sha256": "0" * 64,
    }
    result["replay_digest_sha256"] = canonical_hash(
        "cross-page-relation-binding.v1",
        {key: value for key, value in result.items() if key != "replay_digest_sha256"},
    )
    return result


def _injection(
    role: str, source_sha256: str, kind: str, binding: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract": "cross-page-relation-binding.v1",
        "relation_id": f"{kind}-{role}-093",
        "relation_kind": kind,
        "source_sha256": source_sha256,
        "parser_id": _PARSER_ID,
        "parser_build_id": _PARSER_BUILD_ID,
        "parser_config_hash": _PARSER_CONFIG_HASH,
        "raw_artifact_sha256": binding["raw_structure_sha256"],
        "sanitized_structure_sha256": binding["artifact_sha256"],
        "material_profile_binding_hash": _hash_label(f"{role}-material-profile"),
        "policy_context_hash": _hash_label(f"{role}-090-policy-context"),
        "replay_context_hash": _hash_label(f"{role}-090-replay-context"),
        "endpoint_ids": [
            binding["source_endpoint"]["endpoint_id"],
            binding["target_endpoint"]["endpoint_id"],
        ],
        "binding_hash": "0" * 64,
    }
    result["binding_hash"] = canonical_hash(
        "cross-page-relation-binding.v1",
        {key: value for key, value in result.items() if key != "binding_hash"},
    )
    return result


def _source(role: Literal["terms", "rate_table"], source_sha: str) -> dict[str, Any]:
    kind_086 = "section" if role == "terms" else "table"
    kind_090 = f"{kind_086}_continuation"
    binding = _binding(role, source_sha, kind_086)
    return {
        "role": role,
        "source_sha256": source_sha,
        "relation_kind_086": kind_086,
        "relation_kind_090": kind_090,
        "marker_provenance_089": _marker(
            role, source_sha, "text" if role == "terms" else "table"
        ),
        "binding_086": binding,
        "injection_090": _injection(role, source_sha, kind_090, binding),
    }


def _make_vector() -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract": "cross-page-authority-compatibility-replay.v1",
        "sources": [
            _source("terms", TERMS_SOURCE_SHA256),
            _source("rate_table", RATE_TABLE_SOURCE_SHA256),
        ],
    }
    result["vector_sha256"] = canonical_hash(
        "cross-page-authority-compatibility-replay.v1", result
    )
    return result


CURRENT_INTERFACE_REPLAY_VECTOR_V1: Final[bytes] = _canonical_bytes(_make_vector())
CURRENT_INTERFACE_REPLAY_VECTOR_SHA256: Final[str] = hashlib.sha256(
    CURRENT_INTERFACE_REPLAY_VECTOR_V1
).hexdigest()


def _matrix() -> tuple[CompatibilityMatrixRowV1, ...]:
    rows: list[CompatibilityMatrixRowV1] = []
    for role in ("terms", "rate_table"):
        rows.extend(
            (
                CompatibilityMatrixRowV1(
                    role=role,
                    boundary="089_TO_086",
                    status="BLOCKED",
                    reason_code="MARKER_ENDPOINT_AUTHORITY_NOT_EXPOSED",
                    compatible_fields=(
                        "source_sha256",
                        "parser_model",
                        "mineru_version",
                        "marker_kind",
                        "page_index",
                        "structural_path_sha256",
                    ),
                    missing_fields=(
                        "marker_structural_path",
                        "relation_kind",
                        "source_endpoint_id",
                        "source_page_number",
                        "target_endpoint_id",
                        "target_page_number",
                    ),
                    incompatible_fields=("marker_evidence_hash_preimage",),
                ),
                CompatibilityMatrixRowV1(
                    role=role,
                    boundary="086_TO_090",
                    status="BLOCKED",
                    reason_code="INJECTION_CONTEXT_NOT_BOUND",
                    compatible_fields=(
                        "contract",
                        "source_sha256",
                        "parser_config_hash",
                        "raw_artifact_sha256",
                        "sanitized_structure_sha256",
                        "endpoint_ids",
                    ),
                    missing_fields=(
                        "parser_id",
                        "parser_build_id",
                        "material_profile_binding_hash",
                        "policy_context_hash",
                        "replay_context_hash",
                    ),
                    incompatible_fields=(
                        "relation_kind",
                        "policy_hash_semantics",
                        "replay_hash_semantics",
                        "endpoint_shape",
                    ),
                ),
            )
        )
    return tuple(rows)


CURRENT_COMPATIBILITY_MATRIX_V1: Final = _matrix()


def _result(
    boundary: Literal["VECTOR", "089_TO_086", "086_TO_090"] | None,
    reason: str | None,
    vector_hash: str | None,
    matrix: tuple[CompatibilityMatrixRowV1, ...] = (),
) -> CompatibilityReplayResultV1:
    status: Literal["COMPATIBILITY_VERIFIED", "BLOCKED"] = (
        "COMPATIBILITY_VERIFIED"
        if boundary is None and all(row.status == "COMPATIBLE" for row in matrix)
        else "BLOCKED"
    )
    payload = {
        "status": status,
        "blocked_boundary": boundary,
        "reason_code": reason,
        "matrix": [asdict(row) for row in matrix],
        "vector_sha256": vector_hash,
    }
    return CompatibilityReplayResultV1(
        status=status,
        blocked_boundary=boundary,
        reason_code=reason,
        matrix=matrix,
        vector_sha256=vector_hash,
        result_sha256=canonical_hash(
            "cross-page-authority-compatibility-result.v1", payload
        ),
    )


def _strict_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        _fail("VECTOR", "VECTOR_SHAPE_INVALID")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                _fail("VECTOR", "VECTOR_SHAPE_INVALID")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, _VectorFailure):
        _fail("VECTOR", "VECTOR_SHAPE_INVALID")
    if type(value) is not dict or _canonical_bytes(value) != raw:
        _fail("VECTOR", "VECTOR_BYTES_NOT_CANONICAL")
    return cast(dict[str, Any], value)


def _keys(value: object, expected: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        _fail("VECTOR", "VECTOR_SHAPE_INVALID")
    return cast(dict[str, Any], value)


def _go_marker_hash(provenance: dict[str, Any], marker: dict[str, Any]) -> str:
    return _go_domain_hash(
        "mineru-cross-page-marker-evidence.v1",
        {
            "contract": provenance["contract"],
            "source_sha256": provenance["source_sha256"],
            "parser_model": provenance["parser_model"],
            "mineru_version": provenance["mineru_version"],
            "native_member_sha256": provenance["native_member_sha256"],
            "marker_kind": marker["marker_kind"],
            "page_index": marker["page_index"],
            "structural_path_sha256": marker["structural_path_sha256"],
            "node_type": marker["node_type"],
            "local_index": marker["local_index"],
        },
    )


def _go_marker_item(marker: dict[str, Any]) -> dict[str, Any]:
    return {
        "marker_kind": marker["marker_kind"],
        "page_index": marker["page_index"],
        "structural_path_sha256": marker["structural_path_sha256"],
        "node_type": marker["node_type"],
        "local_index": marker["local_index"],
        "marker_sha256": marker["marker_sha256"],
    }


def _validate_source(source: dict[str, Any], index: int) -> None:  # noqa: C901
    source = _keys(source, _SOURCE_KEYS)
    role = "terms" if index == 0 else "rate_table"
    source_sha = TERMS_SOURCE_SHA256 if index == 0 else RATE_TABLE_SOURCE_SHA256
    kind_086 = "section" if index == 0 else "table"
    kind_090 = f"{kind_086}_continuation"
    if source["role"] != role:
        _fail("VECTOR", "SOURCE_ROLE_INVALID")
    if source["source_sha256"] != source_sha:
        _fail("VECTOR", "SOURCE_IDENTITY_DRIFT")
    if source["relation_kind_086"] != kind_086 or source["relation_kind_090"] != kind_090:
        _fail("VECTOR", "RELATION_KIND_DRIFT")

    provenance = _keys(source["marker_provenance_089"], _MARKER_PROVENANCE_KEYS)
    markers = provenance["markers"]
    if type(markers) is not list or len(markers) != 1 or provenance["marker_count"] != 1:
        _fail("089_TO_086", "MARKER_CARDINALITY_DRIFT")
    marker = _keys(markers[0], _MARKER_KEYS)
    if (
        provenance["contract"] != "mineru-native-cross-page-marker-provenance.v1"
        or provenance["source_sha256"] != source_sha
        or provenance["parser_model"] != "pipeline"
        or provenance["mineru_version"] != "3.4.4"
    ):
        _fail("089_TO_086", "MARKER_PARSER_IDENTITY_DRIFT")
    if marker["marker_kind"] != "cross_page":
        _fail("089_TO_086", "MARKER_KIND_DRIFT")
    if marker["page_index"] != 0:
        _fail("089_TO_086", "MARKER_PAGE_DRIFT")
    replay_preimage = {
        key: provenance[key]
        for key in (
            "contract",
            "source_sha256",
            "parser_model",
            "mineru_version",
            "raw_zip_sha256",
            "native_member_sha256",
            "marker_count",
        )
    }
    replay_preimage["markers"] = [_go_marker_item(marker)]
    if (
        marker["marker_sha256"] != _go_marker_hash(provenance, marker)
        or provenance["replay_digest_sha256"]
        != _go_domain_hash(
            "mineru-cross-page-marker-provenance-replay.v1", replay_preimage
        )
    ):
        _fail("089_TO_086", "MARKER_HASH_DRIFT")

    binding = _keys(source["binding_086"], _BINDING_KEYS)
    source_endpoint = _keys(binding["source_endpoint"], _ENDPOINT_KEYS)
    target_endpoint = _keys(binding["target_endpoint"], _ENDPOINT_KEYS)
    endpoint_kind = "block" if index == 0 else "table"
    endpoint_ids = (
        f"{endpoint_kind}-{role}-000000",
        f"{endpoint_kind}-{role}-000001",
    )
    if binding["source_sha256"] != source_sha:
        _fail("086_TO_090", "BINDING_SOURCE_IDENTITY_DRIFT")
    if binding["relation_kind"] != kind_086:
        _fail("086_TO_090", "BINDING_RELATION_KIND_DRIFT")
    if (
        source_endpoint["endpoint_kind"] != endpoint_kind
        or target_endpoint["endpoint_kind"] != endpoint_kind
        or (source_endpoint["endpoint_id"], target_endpoint["endpoint_id"])
        != endpoint_ids
        or source_endpoint["page_number"] != 1
        or target_endpoint["page_number"] != 2
    ):
        _fail("086_TO_090", "BINDING_ENDPOINT_DRIFT")
    if binding["policy_sha256"] != _POLICY_SHA256_086:
        _fail("086_TO_090", "BINDING_POLICY_IDENTITY_DRIFT")
    if binding["replay_digest_sha256"] != canonical_hash(
        "cross-page-relation-binding.v1",
        {key: value for key, value in binding.items() if key != "replay_digest_sha256"},
    ):
        _fail("086_TO_090", "BINDING_HASH_DRIFT")

    injection = _keys(source["injection_090"], _INJECTION_KEYS)
    if (
        injection["source_sha256"] != source_sha
        or injection["relation_kind"] != kind_090
        or injection["parser_id"] != _PARSER_ID
        or injection["parser_build_id"] != _PARSER_BUILD_ID
        or injection["parser_config_hash"] != binding["parser_config_sha256"]
        or injection["raw_artifact_sha256"] != binding["raw_structure_sha256"]
        or injection["sanitized_structure_sha256"] != binding["artifact_sha256"]
        or tuple(injection["endpoint_ids"]) != endpoint_ids
    ):
        _fail("086_TO_090", "INJECTION_CONTEXT_DRIFT")
    if any(
        not _is_hash(injection[key])
        for key in (
            "material_profile_binding_hash",
            "policy_context_hash",
            "replay_context_hash",
        )
    ):
        _fail("086_TO_090", "INJECTION_CONTEXT_DRIFT")
    if injection["binding_hash"] != canonical_hash(
        "cross-page-relation-binding.v1",
        {key: value for key, value in injection.items() if key != "binding_hash"},
    ):
        _fail("086_TO_090", "INJECTION_HASH_DRIFT")


def verify_cross_page_authority_compatibility_596_1(
    replay_vector: bytes,
) -> CompatibilityReplayResultV1:
    """Recompute the fixed vector and locate incompatibility without making authority."""

    try:
        vector = _strict_json(replay_vector)
        if set(vector) != {"contract", "sources", "vector_sha256"}:
            _fail("VECTOR", "VECTOR_SHAPE_INVALID")
        sources = vector["sources"]
        if (
            vector["contract"] != "cross-page-authority-compatibility-replay.v1"
            or type(sources) is not list
            or len(sources) != 2
            or not _is_hash(vector["vector_sha256"])
        ):
            _fail("VECTOR", "VECTOR_SHAPE_INVALID")
        if vector["vector_sha256"] != canonical_hash(
            "cross-page-authority-compatibility-replay.v1",
            {key: value for key, value in vector.items() if key != "vector_sha256"},
        ):
            _fail("VECTOR", "VECTOR_HASH_DRIFT")
        for index, source in enumerate(sources):
            _validate_source(cast(dict[str, Any], source), index)
    except _VectorFailure as failure:
        return _result(
            failure.boundary,
            failure.reason_code,
            hashlib.sha256(replay_vector).hexdigest()
            if type(replay_vector) is bytes
            else None,
        )
    except (CanonicalEncodingError, TypeError, ValueError):
        return _result(
            "VECTOR",
            "VECTOR_SHAPE_INVALID",
            hashlib.sha256(replay_vector).hexdigest()
            if type(replay_vector) is bytes
            else None,
        )
    matrix = CURRENT_COMPATIBILITY_MATRIX_V1
    return _result(
        matrix[0].boundary,
        matrix[0].reason_code,
        cast(str, vector["vector_sha256"]),
        matrix,
    )


__all__ = [
    "CURRENT_COMPATIBILITY_MATRIX_V1",
    "CURRENT_INTERFACE_REPLAY_VECTOR_SHA256",
    "CURRENT_INTERFACE_REPLAY_VECTOR_V1",
    "CompatibilityMatrixRowV1",
    "CompatibilityReplayResultV1",
    "verify_cross_page_authority_compatibility_596_1",
]
