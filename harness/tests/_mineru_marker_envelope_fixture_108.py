"""Canonical 091 marker-envelope fixtures for frozen 086/092 tests only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast

MARKER_CONTRACT = "mineru-native-cross-page-marker-provenance.v1"
MARKER_PATH_DOMAIN = "mineru-cross-page-marker-path.v1"
MARKER_EVIDENCE_DOMAIN = "mineru-cross-page-marker-evidence.v1"
MARKER_REPLAY_DOMAIN = "mineru-cross-page-marker-provenance-replay.v1"


@dataclass(frozen=True)
class MarkerFixtureV1:
    marker_kind: str
    page_index: int
    structural_path: str
    node_type: str
    local_index: int


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _go_domain(domain: str, value: object | str) -> str:
    material = value if isinstance(value, str) else _compact(value).decode()
    return _sha(domain + "\0" + material)


def attach_marker_envelope_108(
    payload: dict[str, object],
    *,
    markers: tuple[MarkerFixtureV1, ...],
) -> bytes:
    """Attach a complete canonical marker envelope and reseal capture custody."""

    source = cast(str, payload["source_sha256"])
    parser = cast(dict[str, object], payload["parser"])
    facts = cast(dict[str, object], payload["cross_page_facts"])
    native_member = cast(str, facts["native_member_sha256"])
    items: list[dict[str, object]] = []
    for marker in markers:
        path_sha = _go_domain(
            MARKER_PATH_DOMAIN,
            source + "\0" + native_member + "\0" + marker.structural_path,
        )
        preimage: dict[str, object] = {
            "contract": MARKER_CONTRACT,
            "source_sha256": source,
            "parser_model": facts["parser_model"],
            "mineru_version": facts["mineru_version"],
            "native_member_sha256": native_member,
            "marker_kind": marker.marker_kind,
            "page_index": marker.page_index,
            "structural_path_sha256": path_sha,
            "node_type": marker.node_type,
            "local_index": marker.local_index,
        }
        items.append(
            {
                "marker_kind": marker.marker_kind,
                "page_index": marker.page_index,
                "structural_path": marker.structural_path,
                "structural_path_sha256": path_sha,
                "node_type": marker.node_type,
                "local_index": marker.local_index,
                "marker_sha256": _go_domain(MARKER_EVIDENCE_DOMAIN, preimage),
            }
        )
    items.sort(
        key=lambda item: (
            cast(int, item["page_index"]),
            cast(str, item["structural_path_sha256"]),
            cast(str, item["marker_kind"]),
        )
    )

    expected_status = (
        "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
        if items
        else "NATIVE_CROSS_PAGE_FACT_ABSENT"
    )
    if (
        facts["status"] != expected_status
        or facts["ambiguous_marker_count"] != len(items)
        or len(cast(list[object], facts["ambiguous_observation_hashes"])) != len(items)
    ):
        raise AssertionError("fixture cross-page facts do not match explicit markers")
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

    provenance: dict[str, object] = {
        "contract": MARKER_CONTRACT,
        "source_sha256": source,
        "parser_model": facts["parser_model"],
        "mineru_version": facts["mineru_version"],
        "raw_zip_sha256": facts["raw_zip_sha256"],
        "native_member_sha256": native_member,
        "marker_count": len(items),
        "markers": items,
        "replay_digest_sha256": "",
    }
    replay = {
        key: provenance[key]
        for key in (
            "contract",
            "source_sha256",
            "parser_model",
            "mineru_version",
            "raw_zip_sha256",
            "native_member_sha256",
            "marker_count",
            "markers",
        )
    }
    provenance["replay_digest_sha256"] = _go_domain(MARKER_REPLAY_DOMAIN, replay)
    payload["cross_page_marker_provenance"] = provenance

    identity = {
        "contract": payload["contract"],
        "source_sha256": source,
        "attempt": payload["attempt"],
        "parser_config_sha256": parser["config_sha256"],
        "raw_structure_sha256": payload["raw_structure_sha256"],
        "sanitized_structure_sha256": payload["sanitized_structure_sha256"],
        "content_snapshot_sha256": payload["content_snapshot_sha256"],
        "cross_page_projection_sha256": facts["projection_sha256"],
        "marker_provenance_replay_sha256": provenance["replay_digest_sha256"],
    }
    payload["capture_identity_sha256"] = _sha(_compact(identity))
    return _compact(payload) + b"\n"
