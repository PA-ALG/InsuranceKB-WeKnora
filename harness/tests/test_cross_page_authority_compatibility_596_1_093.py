from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler.cross_page_authority_compatibility_596_1 import (
    CURRENT_INTERFACE_REPLAY_VECTOR_SHA256,
    CURRENT_INTERFACE_REPLAY_VECTOR_V1,
    CompatibilityMatrixRowV1,
    CompatibilityReplayResultV1,
    verify_cross_page_authority_compatibility_596_1,
)


def _payload() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(CURRENT_INTERFACE_REPLAY_VECTOR_V1))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _go_domain_hash(domain: str, value: object) -> str:
    preimage = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode(
        "ascii"
    )
    return hashlib.sha256(domain.encode("ascii") + b"\0" + preimage).hexdigest()


def _seal_marker(source: dict[str, Any]) -> None:
    marker = source["marker_provenance_089"]["markers"][0]
    marker_preimage = {
        "contract": source["marker_provenance_089"]["contract"],
        "source_sha256": source["source_sha256"],
        "parser_model": source["marker_provenance_089"]["parser_model"],
        "mineru_version": source["marker_provenance_089"]["mineru_version"],
        "native_member_sha256": source["marker_provenance_089"]["native_member_sha256"],
        "marker_kind": marker["marker_kind"],
        "page_index": marker["page_index"],
        "structural_path_sha256": marker["structural_path_sha256"],
        "node_type": marker["node_type"],
        "local_index": marker["local_index"],
    }
    marker["marker_sha256"] = _go_domain_hash(
        "mineru-cross-page-marker-evidence.v1", marker_preimage
    )
    provenance = source["marker_provenance_089"]
    ordered_marker = {
        "marker_kind": marker["marker_kind"],
        "page_index": marker["page_index"],
        "structural_path_sha256": marker["structural_path_sha256"],
        "node_type": marker["node_type"],
        "local_index": marker["local_index"],
        "marker_sha256": marker["marker_sha256"],
    }
    replay_preimage = {
        "contract": provenance["contract"],
        "source_sha256": provenance["source_sha256"],
        "parser_model": provenance["parser_model"],
        "mineru_version": provenance["mineru_version"],
        "raw_zip_sha256": provenance["raw_zip_sha256"],
        "native_member_sha256": provenance["native_member_sha256"],
        "marker_count": provenance["marker_count"],
        "markers": [ordered_marker],
    }
    provenance["replay_digest_sha256"] = _go_domain_hash(
        "mineru-cross-page-marker-provenance-replay.v1", replay_preimage
    )


def _seal_binding(source: dict[str, Any]) -> None:
    binding = source["binding_086"]
    binding["replay_digest_sha256"] = canonical_hash(
        "cross-page-relation-binding.v1",
        {key: value for key, value in binding.items() if key != "replay_digest_sha256"},
    )


def _seal_injection(source: dict[str, Any]) -> None:
    injection = source["injection_090"]
    injection["binding_hash"] = canonical_hash(
        "cross-page-relation-binding.v1",
        {key: value for key, value in injection.items() if key != "binding_hash"},
    )


def _seal_vector(value: dict[str, Any]) -> bytes:
    value["vector_sha256"] = canonical_hash(
        "cross-page-authority-compatibility-replay.v1",
        {key: item for key, item in value.items() if key != "vector_sha256"},
    )
    return _canonical_bytes(value)


def _row(
    result: CompatibilityReplayResultV1,
    role: str,
    boundary: str,
) -> CompatibilityMatrixRowV1:
    return next(
        item
        for item in result.matrix
        if item.role == role and item.boundary == boundary
    )


def test_current_frozen_interfaces_report_both_exact_compatibility_blockers() -> None:
    result = verify_cross_page_authority_compatibility_596_1(
        CURRENT_INTERFACE_REPLAY_VECTOR_V1
    )

    assert result.status == "BLOCKED"
    assert tuple(
        (row.role, row.boundary, row.status, row.reason_code)
        for row in result.matrix
    ) == (
        (
            "terms",
            "089_TO_086",
            "BLOCKED",
            "MARKER_ENDPOINT_AUTHORITY_NOT_EXPOSED",
        ),
        (
            "terms",
            "086_TO_090",
            "BLOCKED",
            "INJECTION_CONTEXT_NOT_BOUND",
        ),
        (
            "rate_table",
            "089_TO_086",
            "BLOCKED",
            "MARKER_ENDPOINT_AUTHORITY_NOT_EXPOSED",
        ),
        (
            "rate_table",
            "086_TO_090",
            "BLOCKED",
            "INJECTION_CONTEXT_NOT_BOUND",
        ),
    )
    assert all(row.correction_owner == "086" for row in result.matrix)
    assert all(
        row.correction_path
        == "harness/src/insurance_harness/knowledge_compiler/"
        "mineru_cross_page_binding_596_1.py"
        for row in result.matrix
    )
    assert "ADMIT" not in repr(result)
    assert "READY" not in repr(result)


def test_fixed_cross_language_vector_has_exact_roles_and_replay_hash() -> None:
    payload = _payload()

    assert CURRENT_INTERFACE_REPLAY_VECTOR_SHA256 == (
        "11acd865df279fb999b31d4980689012714afbcab27b1b9cc92e63349ca4fbec"
    )
    assert hashlib.sha256(CURRENT_INTERFACE_REPLAY_VECTOR_V1).hexdigest() == (
        CURRENT_INTERFACE_REPLAY_VECTOR_SHA256
    )
    assert [item["role"] for item in payload["sources"]] == [
        "terms",
        "rate_table",
    ]
    assert [item["relation_kind_086"] for item in payload["sources"]] == [
        "section",
        "table",
    ]
    assert [item["relation_kind_090"] for item in payload["sources"]] == [
        "section_continuation",
        "table_continuation",
    ]
    assert _seal_vector(copy.deepcopy(payload)) == CURRENT_INTERFACE_REPLAY_VECTOR_V1
    result = verify_cross_page_authority_compatibility_596_1(
        CURRENT_INTERFACE_REPLAY_VECTOR_V1
    )
    assert result.result_sha256 == (
        "6f45bdfbdc9268e00b88450d81d8cc37c33d9bc7351281f8bee75b30b87adbe6"
    )


@pytest.mark.parametrize(
    ("mutation", "expected_boundary", "expected_reason"),
    [
        ("role", "VECTOR", "SOURCE_ROLE_INVALID"),
        ("source", "VECTOR", "SOURCE_IDENTITY_DRIFT"),
        ("marker-kind", "089_TO_086", "MARKER_KIND_DRIFT"),
        ("marker-page", "089_TO_086", "MARKER_PAGE_DRIFT"),
        ("parser-version", "089_TO_086", "MARKER_PARSER_IDENTITY_DRIFT"),
        ("marker-hash", "089_TO_086", "MARKER_HASH_DRIFT"),
        ("binding-kind", "086_TO_090", "BINDING_RELATION_KIND_DRIFT"),
        ("endpoint-page", "086_TO_090", "BINDING_ENDPOINT_DRIFT"),
        ("policy", "086_TO_090", "BINDING_POLICY_IDENTITY_DRIFT"),
        ("injection-source", "086_TO_090", "INJECTION_CONTEXT_DRIFT"),
    ],
)
def test_fully_recomputed_identity_and_semantic_drifts_name_the_boundary(
    mutation: str,
    expected_boundary: str,
    expected_reason: str,
) -> None:
    payload = _payload()
    source = payload["sources"][1]
    if mutation == "role":
        source["role"] = "rate"
    elif mutation == "source":
        source["source_sha256"] = "f" * 64
        source["marker_provenance_089"]["source_sha256"] = "f" * 64
        source["binding_086"]["source_sha256"] = "f" * 64
        source["injection_090"]["source_sha256"] = "f" * 64
        _seal_marker(source)
        _seal_binding(source)
        _seal_injection(source)
    elif mutation == "marker-kind":
        source["marker_provenance_089"]["markers"][0]["marker_kind"] = "lines_deleted"
        _seal_marker(source)
    elif mutation == "marker-page":
        source["marker_provenance_089"]["markers"][0]["page_index"] = 1
        _seal_marker(source)
    elif mutation == "parser-version":
        source["marker_provenance_089"]["mineru_version"] = "3.4.5"
        _seal_marker(source)
    elif mutation == "marker-hash":
        source["marker_provenance_089"]["markers"][0]["marker_sha256"] = "e" * 64
        provenance = source["marker_provenance_089"]
        provenance["replay_digest_sha256"] = _go_domain_hash(
            "mineru-cross-page-marker-provenance-replay.v1",
            {
                "contract": provenance["contract"],
                "source_sha256": provenance["source_sha256"],
                "parser_model": provenance["parser_model"],
                "mineru_version": provenance["mineru_version"],
                "raw_zip_sha256": provenance["raw_zip_sha256"],
                "native_member_sha256": provenance["native_member_sha256"],
                "marker_count": provenance["marker_count"],
                "markers": [
                    {
                        "marker_kind": provenance["markers"][0]["marker_kind"],
                        "page_index": provenance["markers"][0]["page_index"],
                        "structural_path_sha256": provenance["markers"][0][
                            "structural_path_sha256"
                        ],
                        "node_type": provenance["markers"][0]["node_type"],
                        "local_index": provenance["markers"][0]["local_index"],
                        "marker_sha256": provenance["markers"][0]["marker_sha256"],
                    }
                ],
            },
        )
    elif mutation == "binding-kind":
        source["binding_086"]["relation_kind"] = "section"
        _seal_binding(source)
    elif mutation == "endpoint-page":
        source["binding_086"]["target_endpoint"]["page_number"] = 3
        _seal_binding(source)
    elif mutation == "policy":
        source["binding_086"]["policy_sha256"] = "d" * 64
        _seal_binding(source)
    elif mutation == "injection-source":
        source["injection_090"]["source_sha256"] = "c" * 64
        _seal_injection(source)
    result = verify_cross_page_authority_compatibility_596_1(_seal_vector(payload))

    assert result.status == "BLOCKED"
    assert result.blocked_boundary == expected_boundary
    assert result.reason_code == expected_reason
    assert "ADMIT" not in repr(result) and "READY" not in repr(result)


def test_json_order_encoding_missing_and_extra_fields_fail_closed() -> None:
    payload = _payload()
    noncanonical = json.dumps(payload, indent=2).encode()
    assert verify_cross_page_authority_compatibility_596_1(
        noncanonical
    ).reason_code == "VECTOR_BYTES_NOT_CANONICAL"

    missing = _payload()
    del missing["sources"][0]["marker_provenance_089"]["markers"]
    assert verify_cross_page_authority_compatibility_596_1(
        _seal_vector(missing)
    ).reason_code == "VECTOR_SHAPE_INVALID"

    extra = _payload()
    extra["sources"][0]["unknown"] = "forbidden"
    assert verify_cross_page_authority_compatibility_596_1(
        _seal_vector(extra)
    ).reason_code == "VECTOR_SHAPE_INVALID"

    wrong_hash_algorithm = _payload()
    vector_preimage = {
        key: value
        for key, value in wrong_hash_algorithm.items()
        if key != "vector_sha256"
    }
    wrong_hash_algorithm["vector_sha256"] = hashlib.sha256(
        _canonical_bytes(vector_preimage)
    ).hexdigest()
    assert verify_cross_page_authority_compatibility_596_1(
        _canonical_bytes(wrong_hash_algorithm)
    ).reason_code == "VECTOR_HASH_DRIFT"


def test_matrix_is_the_minimal_091_092_handoff_and_never_builds_authority() -> None:
    result = verify_cross_page_authority_compatibility_596_1(
        CURRENT_INTERFACE_REPLAY_VECTOR_V1
    )
    marker = _row(result, "terms", "089_TO_086")
    injection = _row(result, "rate_table", "086_TO_090")

    assert marker.missing_fields == (
        "marker_structural_path",
        "relation_kind",
        "source_endpoint_id",
        "source_page_number",
        "target_endpoint_id",
        "target_page_number",
    )
    assert "relation_kind" in injection.incompatible_fields
    assert injection.missing_fields == (
        "parser_id",
        "parser_build_id",
        "material_profile_binding_hash",
        "policy_context_hash",
        "replay_context_hash",
    )
    assert not hasattr(result, "binding")
    assert not hasattr(result, "admission")
