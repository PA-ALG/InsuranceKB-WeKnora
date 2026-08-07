from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, cast

import pytest
from pydantic import ValidationError

from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    CaptureIntakeError,
    intake_mineru_capture_bundle_596_1,
)

TERMS_SHA = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
BROCHURE_SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
RATE_SHA = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
MARKER_CONTRACT = "mineru-native-cross-page-marker-provenance.v1"


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _domain(domain: str, value: object) -> str:
    return _sha(domain.encode() + b"\0" + _compact(value))


def _parser() -> dict[str, object]:
    parser: dict[str, object] = {
        "engine": "mineru_cloud",
        "implementation": "NewMinerUCloudReader",
        "native_structure_schema": "mineru-native-structure.v1",
        "model": "pipeline",
        "formula": True,
        "table": True,
        "ocr": True,
        "language": "ch",
        "config_sha256": "",
    }
    parser["config_sha256"] = _sha(b"mineru-capture-config.v1\0" + _compact(parser))
    return parser


def _cross_page(source_sha: str, capability: str) -> dict[str, object]:
    members = [{"category": "middle_json", "size": 17, "sha256": "3" * 64}]
    facts: dict[str, object] = {
        "contract": "mineru-native-cross-page-facts.v1",
        "status": "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS",
        "required_capability": capability,
        "source_sha256": source_sha,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": "2" * 64,
        "member_inventory_sha256": _sha(_compact(members)),
        "projection_sha256": "",
        "relation_count": 0,
        "ambiguous_marker_count": 2,
        "ambiguous_observation_hashes": ["6" * 64, "7" * 64],
        "members": members,
        "relations": [],
    }
    projection = {
        key: facts[key]
        for key in (
            "contract",
            "status",
            "required_capability",
            "source_sha256",
            "parser_model",
            "mineru_version",
            "relation_count",
            "ambiguous_marker_count",
            "ambiguous_observation_hashes",
            "relations",
        )
    }
    facts["projection_sha256"] = _sha(_compact(projection))
    return facts


def _reseal_marker(value: dict[str, object]) -> None:
    markers = cast(list[dict[str, object]], value["markers"])
    for marker in markers:
        preimage = {
            "contract": MARKER_CONTRACT,
            "source_sha256": value["source_sha256"],
            "parser_model": value["parser_model"],
            "mineru_version": value["mineru_version"],
            "native_member_sha256": value["native_member_sha256"],
            "marker_kind": marker["marker_kind"],
            "page_index": marker["page_index"],
            "structural_path_sha256": marker["structural_path_sha256"],
            "node_type": marker["node_type"],
            "local_index": marker["local_index"],
        }
        marker["marker_sha256"] = _domain(
            "mineru-cross-page-marker-evidence.v1", preimage
        )
    value["marker_count"] = len(markers)
    replay = {
        "contract": value["contract"],
        "source_sha256": value["source_sha256"],
        "parser_model": value["parser_model"],
        "mineru_version": value["mineru_version"],
        "raw_zip_sha256": value["raw_zip_sha256"],
        "native_member_sha256": value["native_member_sha256"],
        "marker_count": value["marker_count"],
        "markers": markers,
    }
    value["replay_digest_sha256"] = _domain(
        "mineru-cross-page-marker-provenance-replay.v1", replay
    )


def _marker(source_sha: str, facts: dict[str, object]) -> dict[str, object]:
    marker: dict[str, object] = {
        "contract": MARKER_CONTRACT,
        "source_sha256": source_sha,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": facts["raw_zip_sha256"],
        "native_member_sha256": facts["native_member_sha256"],
        "marker_count": 0,
        "markers": [
            {
                "marker_kind": "cross_page",
                "page_index": 0,
                "structural_path_sha256": "5" * 64,
                "node_type": "table",
                "local_index": 1,
                "marker_sha256": "",
            },
            {
                "marker_kind": "lines_deleted",
                "page_index": 0,
                "structural_path_sha256": "5" * 64,
                "node_type": "table",
                "local_index": 1,
                "marker_sha256": "",
            },
        ],
        "replay_digest_sha256": "",
    }
    _reseal_marker(marker)
    return marker


def _reseal_capture_identity(capture: dict[str, object]) -> None:
    parser = cast(dict[str, object], capture["parser"])
    preimage: dict[str, object] = {
        "contract": capture["contract"],
        "source_sha256": capture["source_sha256"],
        "attempt": capture["attempt"],
        "parser_config_sha256": parser["config_sha256"],
        "raw_structure_sha256": capture["raw_structure_sha256"],
        "sanitized_structure_sha256": capture["sanitized_structure_sha256"],
        "content_snapshot_sha256": capture["content_snapshot_sha256"],
    }
    if "cross_page_facts" in capture:
        facts = cast(dict[str, object], capture["cross_page_facts"])
        marker = cast(dict[str, object], capture["cross_page_marker_provenance"])
        preimage["cross_page_projection_sha256"] = facts["projection_sha256"]
        preimage["marker_provenance_replay_sha256"] = marker[
            "replay_digest_sha256"
        ]
    capture["capture_identity_sha256"] = _sha(_compact(preimage))


def _capture(
    source_sha: str,
    *,
    structure: object | None = None,
    content: str = "safe policy snapshot",
) -> dict[str, object]:
    structure = structure or {"pages": [{"page_index": 0, "blocks": []}]}
    parser = _parser()
    capture: dict[str, object] = {
        "contract": "mineru-semantic-content-custody.v2",
        "source_sha256": source_sha,
        "attempt": {
            "attempt_number": 2,
            "attempt_role": "bounded_upgrade",
            "generation": 0,
        },
        "raw_structure_sha256": "4" * 64,
        "sanitized_structure_sha256": _sha(_compact(structure)),
        "sanitized_structure": structure,
        "content_snapshot_sha256": _sha(content),
        "content_snapshot": content,
        "capture_identity_sha256": "",
        "parser": parser,
        "calls": {"allocation_post": 1, "upload_put": 1, "status_get": 3, "zip_get": 1},
        "latency_milliseconds": 25,
        "status": "completed",
    }
    if source_sha == TERMS_SHA:
        capture["cross_page_facts"] = _cross_page(source_sha, "cross_page_sections")
    elif source_sha == RATE_SHA:
        capture["cross_page_facts"] = _cross_page(source_sha, "cross_page_tables")
    if source_sha in {TERMS_SHA, RATE_SHA}:
        facts = cast(dict[str, object], capture["cross_page_facts"])
        capture["cross_page_marker_provenance"] = _marker(source_sha, facts)
    _reseal_capture_identity(capture)
    return capture


def _bytes(payload: dict[str, object]) -> bytes:
    return _compact(payload) + b"\n"


def _inputs() -> tuple[bytes, bytes, bytes]:
    return tuple(_bytes(_capture(value)) for value in (TERMS_SHA, BROCHURE_SHA, RATE_SHA))  # type: ignore[return-value]


def _mutate(index: int, edit: Callable[[dict[str, Any]], None]) -> tuple[bytes, bytes, bytes]:
    payloads = [json.loads(value) for value in _inputs()]
    edit(payloads[index])
    return tuple(_bytes(value) for value in payloads)  # type: ignore[return-value]


def test_exact_three_bundle_is_deterministic_immutable_and_privacy_safe() -> None:
    first = intake_mineru_capture_bundle_596_1(_inputs())
    second = intake_mineru_capture_bundle_596_1(_inputs())

    assert [item.role for item in first.sources] == ["terms", "brochure", "rate"]
    assert [item.source_sha256 for item in first.sources] == [TERMS_SHA, BROCHURE_SHA, RATE_SHA]
    assert first.bundle_digest_sha256 == second.bundle_digest_sha256
    assert first.sources[0].evidence.cross_page_marker_provenance is not None
    assert first.sources[2].evidence.cross_page_marker_provenance is not None
    assert first.sources[1].evidence.cross_page_marker_provenance is None
    terms_markers = first.sources[0].evidence.cross_page_marker_provenance.markers
    assert terms_markers[0].marker_sha256 != terms_markers[1].marker_sha256
    assert "content_snapshot" not in first.model_dump()
    assert "sanitized_structure" not in first.model_dump()
    assert "safe policy snapshot" not in repr(first)
    with pytest.raises(ValidationError):
        first.sources[0].role = "rate"


@pytest.mark.parametrize(
    ("index", "edit"),
    [
        (0, lambda value: value.__setitem__("source_sha256", RATE_SHA)),
        (0, lambda value: value["attempt"].__setitem__("attempt_number", 1)),
        (0, lambda value: value["attempt"].__setitem__("attempt_role", "initial")),
        (0, lambda value: value["attempt"].__setitem__("generation", 1)),
        (0, lambda value: value["parser"].__setitem__("engine", "builtin")),
        (0, lambda value: value["parser"].__setitem__("implementation", "other")),
        (0, lambda value: value["parser"].__setitem__("native_structure_schema", "v2")),
        (0, lambda value: value["parser"].__setitem__("model", "other")),
        (0, lambda value: value["parser"].__setitem__("formula", False)),
        (0, lambda value: value["parser"].__setitem__("table", False)),
        (0, lambda value: value["parser"].__setitem__("ocr", False)),
        (0, lambda value: value["parser"].__setitem__("language", "en")),
        (0, lambda value: value["parser"].__setitem__("config_sha256", "0" * 64)),
        (0, lambda value: value["calls"].__setitem__("allocation_post", 0)),
        (0, lambda value: value["calls"].__setitem__("upload_put", 2)),
        (0, lambda value: value["calls"].__setitem__("status_get", 0)),
        (0, lambda value: value["calls"].__setitem__("status_get", 191)),
        (0, lambda value: value["calls"].__setitem__("zip_get", 0)),
        (0, lambda value: value.__setitem__("status", "failed")),
        (0, lambda value: value.__setitem__("raw_structure_sha256", "x" * 64)),
        (0, lambda value: value.__setitem__("sanitized_structure_sha256", "0" * 64)),
        (0, lambda value: value.__setitem__("content_snapshot_sha256", "0" * 64)),
        (0, lambda value: value.__setitem__("capture_identity_sha256", "0" * 64)),
    ],
)
def test_identity_hash_call_and_status_mutations_fail_closed(
    index: int, edit: Callable[[dict[str, Any]], None]
) -> None:
    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(index, edit))


@pytest.mark.parametrize(
    "edit",
    [
        lambda value: value.__setitem__("extra", True),
        lambda value: value["parser"].__setitem__("extra", True),
        lambda value: value["calls"].__setitem__("extra", 1),
        lambda value: value.pop("status"),
    ],
)
def test_closed_shape_rejects_missing_or_extra_members(
    edit: Callable[[dict[str, Any]], None],
) -> None:
    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(0, edit))


def test_bytes_only_duplicate_keys_float_and_trailing_data_are_rejected() -> None:
    good = _inputs()
    malformed = (
        good[0].replace(b'"status":"completed"', b'"status":"completed","status":"completed"'),
        good[1],
        good[2],
    )
    floating = (
        good[0].replace(b'"latency_milliseconds":25', b'"latency_milliseconds":25.0'),
        good[1],
        good[2],
    )
    for bad in (malformed, floating, (good[0][:-1] + b"{}\n", good[1], good[2])):
        with pytest.raises(CaptureIntakeError):
            intake_mineru_capture_bundle_596_1(bad)
    with pytest.raises((CaptureIntakeError, TypeError)):
        intake_mineru_capture_bundle_596_1((good[0].decode(), good[1], good[2]))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "edit",
    [
        lambda value: value["cross_page_facts"].__setitem__("source_sha256", RATE_SHA),
        lambda value: value["cross_page_facts"].__setitem__(
            "required_capability", "cross_page_tables"
        ),
        lambda value: value["cross_page_facts"].__setitem__("parser_model", "other"),
        lambda value: value["cross_page_facts"].__setitem__("mineru_version", "3.4.3"),
        lambda value: value["cross_page_facts"].pop("native_member_sha256"),
        lambda value: value["cross_page_facts"].__setitem__("member_inventory_sha256", "0" * 64),
        lambda value: value["cross_page_facts"].__setitem__("projection_sha256", "0" * 64),
        lambda value: value["cross_page_facts"].__setitem__("relation_count", 1),
        lambda value: value["cross_page_facts"].__setitem__("ambiguous_marker_count", 1),
        lambda value: value["cross_page_facts"].__setitem__("extra", True),
        lambda value: value.pop("cross_page_facts"),
    ],
)
def test_cross_page_envelope_and_hash_mutations_fail_closed(
    edit: Callable[[dict[str, Any]], None]
) -> None:
    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(0, edit))


@pytest.mark.parametrize(
    "edit",
    [
        lambda value: value.pop("cross_page_marker_provenance"),
        lambda value: value["cross_page_marker_provenance"].__setitem__(
            "marker_count", 99
        ),
        lambda value: value["cross_page_marker_provenance"].__setitem__(
            "mineru_version", "3.4.5"
        ),
        lambda value: value["cross_page_marker_provenance"].__setitem__(
            "raw_zip_sha256", "8" * 64
        ),
        lambda value: value["cross_page_marker_provenance"].__setitem__(
            "native_member_sha256", "8" * 64
        ),
        lambda value: value["cross_page_marker_provenance"]["markers"][0].__setitem__(
            "marker_kind", "unknown"
        ),
        lambda value: value["cross_page_marker_provenance"]["markers"][0].__setitem__(
            "page_index", 1
        ),
        lambda value: value["cross_page_marker_provenance"]["markers"][0].__setitem__(
            "local_index", -1
        ),
        lambda value: value["cross_page_marker_provenance"]["markers"][0].__setitem__(
            "structural_path_sha256", "8" * 64
        ),
        lambda value: value["cross_page_marker_provenance"]["markers"][0].__setitem__(
            "marker_sha256", "8" * 64
        ),
        lambda value: value["cross_page_marker_provenance"].__setitem__(
            "replay_digest_sha256", "8" * 64
        ),
        lambda value: value["cross_page_marker_provenance"].__setitem__("extra", True),
    ],
)
def test_marker_envelope_mutations_fail_closed(edit: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(0, edit))


def test_self_consistent_marker_and_facts_drift_still_fails_closed() -> None:
    def drift(value: dict[str, Any]) -> None:
        marker = cast(dict[str, object], value["cross_page_marker_provenance"])
        marker["source_sha256"] = RATE_SHA
        _reseal_marker(marker)

    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(0, drift))


def test_self_consistent_marker_membership_count_drift_fails_closed() -> None:
    def drift(value: dict[str, Any]) -> None:
        marker = cast(dict[str, object], value["cross_page_marker_provenance"])
        markers = cast(list[dict[str, object]], marker["markers"])
        markers.pop()
        _reseal_marker(marker)
        _reseal_capture_identity(value)

    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(0, drift))


def test_self_consistent_private_marker_node_type_fails_closed() -> None:
    def drift(value: dict[str, Any]) -> None:
        marker = cast(dict[str, object], value["cross_page_marker_provenance"])
        markers = cast(list[dict[str, object]], marker["markers"])
        markers[0]["node_type"] = "secret_token"
        _reseal_marker(marker)
        _reseal_capture_identity(value)

    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(0, drift))


def test_duplicate_marker_membership_and_old_targeted_artifact_fail_closed() -> None:
    def duplicate(value: dict[str, Any]) -> None:
        marker = cast(dict[str, object], value["cross_page_marker_provenance"])
        markers = cast(list[dict[str, object]], marker["markers"])
        markers.append(dict(markers[0]))
        _reseal_marker(marker)

    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(0, duplicate))
    with pytest.raises(CaptureIntakeError) as caught:
        intake_mineru_capture_bundle_596_1(
            _mutate(0, lambda value: value.pop("cross_page_marker_provenance"))
        )
    assert caught.value.reason_code == "CAPTURE_MARKER_ENVELOPE_INVALID"


def test_marker_public_shape_is_privacy_safe_and_non_authoritative() -> None:
    bundle = intake_mineru_capture_bundle_596_1(_inputs())
    marker = bundle.sources[0].evidence.cross_page_marker_provenance
    assert marker is not None
    dumped = json.dumps(marker.model_dump(mode="json"), sort_keys=True)
    for forbidden in (
        "content_snapshot",
        "sanitized_structure",
        "source_page",
        "target_page",
        "endpoint",
        "relation",
        "ADMIT",
        "http://",
        "https://",
    ):
        assert forbidden not in dumped


def test_brochure_must_omit_cross_page_envelope_and_order_is_fixed() -> None:
    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(_mutate(1, lambda value: value.__setitem__(
            "cross_page_facts", _cross_page(BROCHURE_SHA, "cross_page_sections")
        )))
    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1(
            _mutate(
                1,
                lambda value: value.__setitem__(
                    "cross_page_marker_provenance",
                    _marker(
                        BROCHURE_SHA,
                        _cross_page(BROCHURE_SHA, "cross_page_sections"),
                    ),
                ),
            )
        )
    terms, brochure, rate = _inputs()
    with pytest.raises(CaptureIntakeError):
        intake_mineru_capture_bundle_596_1((rate, brochure, terms))


def test_unreplayable_raw_cross_page_hashes_are_bound_into_bundle_identity() -> None:
    original = intake_mineru_capture_bundle_596_1(_inputs())

    def drift_container(value: dict[str, Any]) -> None:
        facts = cast(dict[str, object], value["cross_page_facts"])
        marker = cast(dict[str, object], value["cross_page_marker_provenance"])
        facts["raw_zip_sha256"] = "9" * 64
        marker["raw_zip_sha256"] = "9" * 64
        _reseal_marker(marker)
        _reseal_capture_identity(value)

    changed = intake_mineru_capture_bundle_596_1(
        _mutate(0, drift_container)
    )
    assert changed.sources[0].cross_page_facts_digest_sha256 != (
        original.sources[0].cross_page_facts_digest_sha256
    )
    assert changed.sources[0].intake_digest_sha256 != original.sources[0].intake_digest_sha256
    assert changed.bundle_digest_sha256 != original.bundle_digest_sha256


def test_native_structure_may_retain_json_coordinates_without_weakening_typed_counters() -> None:
    payload = _capture(
        TERMS_SHA,
        structure={"pages": [{"page_index": 0, "bbox": [1.25, 2.5, 3.75, 4.0]}]},
    )
    result = intake_mineru_capture_bundle_596_1(
        (_bytes(payload), _inputs()[1], _inputs()[2])
    )
    assert result.sources[0].evidence.sanitized_structure.startswith(b'{"pages"')


@pytest.mark.parametrize(
    "private_value",
    [
        "/home/alice/private.pdf",
        "/Volumes/customer/secret.pdf",
        r"C:\\Users\\alice\\private.pdf",
        r"\\server\share\private.pdf",
        "Bearer sk-live-sensitive-value",
    ],
)
def test_private_material_is_rejected_without_echo(private_value: str) -> None:
    payload = _capture(TERMS_SHA, structure={"pages": [{"label": private_value}]})
    payload["sanitized_structure_sha256"] = _sha(_compact(payload["sanitized_structure"]))
    _reseal_capture_identity(payload)
    bad = (_bytes(payload), _inputs()[1], _inputs()[2])
    with pytest.raises(CaptureIntakeError) as caught:
        intake_mineru_capture_bundle_596_1(bad)
    assert private_value not in str(caught.value)
    assert private_value not in repr(caught.value)


def test_content_snapshot_privacy_gate_is_recomputed_and_non_echoing() -> None:
    secret = "token=super-secret-customer-value"
    payload = _capture(TERMS_SHA, content=secret)
    bad = (_bytes(payload), _inputs()[1], _inputs()[2])
    with pytest.raises(CaptureIntakeError) as caught:
        intake_mineru_capture_bundle_596_1(bad)
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
