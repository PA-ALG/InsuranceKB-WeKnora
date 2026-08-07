from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler.marker_authority_envelope_596_1 import (
    MarkerAuthorityExportError,
    export_marker_authority_envelope_596_1,
    recompute_marker_authority_envelope_sha256,
)

TERMS_SHA = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
BROCHURE_SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
RATE_SHA = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
MARKER_CONTRACT = "mineru-native-cross-page-marker-provenance.v1"


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _go_domain(domain: str, value: object | str) -> str:
    material = value if isinstance(value, str) else _compact(value).decode()
    return _sha(domain + "\0" + material)


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
    parser["config_sha256"] = _sha(
        b"mineru-capture-config.v1\0" + _compact(parser)
    )
    return parser


def _structure(markers: tuple[tuple[str, int, str], ...]) -> dict[str, object]:
    blocks: list[dict[str, object]] = []
    for marker_kind, local_index, node_type in markers:
        while len(blocks) <= local_index:
            blocks.append({"type": "text", "lines": []})
        blocks[local_index] = {"type": node_type, marker_kind: True, "lines": []}
    return {
        "_backend": "pipeline",
        "_version_name": "3.4.4",
        "pdf_info": [{"page_idx": 0, "para_blocks": blocks}],
    }


def _marker_items(
    source_sha: str,
    member_sha: str,
    markers: tuple[tuple[str, int, str], ...],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for marker_kind, local_index, node_type in markers:
        path = f"p0/b{local_index}"
        path_sha = _go_domain(
            "mineru-cross-page-marker-path.v1",
            source_sha + "\0" + member_sha + "\0" + path,
        )
        preimage = {
            "contract": MARKER_CONTRACT,
            "source_sha256": source_sha,
            "parser_model": "pipeline",
            "mineru_version": "3.4.4",
            "native_member_sha256": member_sha,
            "marker_kind": marker_kind,
            "page_index": 0,
            "structural_path_sha256": path_sha,
            "node_type": node_type,
            "local_index": local_index,
        }
        result.append(
            {
                "marker_kind": preimage["marker_kind"],
                "page_index": preimage["page_index"],
                "structural_path": path,
                "structural_path_sha256": preimage["structural_path_sha256"],
                "node_type": preimage["node_type"],
                "local_index": preimage["local_index"],
                "marker_sha256": _go_domain(
                    "mineru-cross-page-marker-evidence.v1", preimage
                ),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            cast(int, item["page_index"]),
            cast(str, item["structural_path_sha256"]),
            cast(str, item["marker_kind"]),
        ),
    )


def _cross_page(
    source_sha: str,
    capability: str,
    member_sha: str,
    marker_items: list[dict[str, object]],
) -> dict[str, object]:
    members = [{"category": "middle_json", "size": 17, "sha256": member_sha}]
    facts: dict[str, object] = {
        "contract": "mineru-native-cross-page-facts.v1",
        "status": "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS",
        "required_capability": capability,
        "source_sha256": source_sha,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": member_sha,
        "member_inventory_sha256": _sha(_compact(members)),
        "projection_sha256": "",
        "relation_count": 0,
        "ambiguous_marker_count": len(marker_items),
        "ambiguous_observation_hashes": sorted(
            cast(str, item["marker_sha256"]) for item in marker_items
        ),
        "members": members,
        "relations": [],
    }
    projection = {
        key: facts[key]
        for key in (
            "contract", "status", "required_capability", "source_sha256",
            "parser_model", "mineru_version", "relation_count",
            "ambiguous_marker_count", "ambiguous_observation_hashes", "relations",
        )
    }
    facts["projection_sha256"] = _sha(_compact(projection))
    return facts


def _hierarchy(
    source_sha: str,
    member_sha: str,
    structure: dict[str, object],
) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    pages = cast(list[dict[str, Any]], structure["pdf_info"])
    for page_index, page in enumerate(pages):
        blocks = cast(list[dict[str, Any]], page["para_blocks"])
        for local_index, block in enumerate(blocks):
            structural_path = f"p{page_index}/b{local_index}"
            structural_path_sha = _go_domain(
                "mineru-cross-page-marker-path.v1",
                source_sha + "\0" + member_sha + "\0" + structural_path,
            )
            node: dict[str, object] = {
                "page_index": page_index,
                "node_type": block["type"],
                "local_index": local_index,
                "reading_order": len(nodes),
                "structural_path": structural_path,
                "structural_path_sha256": structural_path_sha,
                "bbox_present": False,
                "bbox_sha256": _go_domain("mineru-native-hierarchy-bbox.v1", "null"),
                "text_level": block.get("text_level"),
            }
            node_preimage = {
                "contract": "mineru-native-hierarchy-provenance.v1.node",
                "source_sha256": source_sha,
                "parser_model": "pipeline",
                "mineru_version": "3.4.4",
                "raw_zip_sha256": "1" * 64,
                "native_member_sha256": member_sha,
                **node,
            }
            node["node_preimage_sha256"] = _go_domain(
                "mineru-native-hierarchy-node.v1", node_preimage
            )
            nodes.append(node)
    hierarchy: dict[str, object] = {
        "contract": "mineru-native-hierarchy-provenance.v1",
        "status": "HIERARCHY_PROVENANCE_NOT_CAPTURED",
        "source_sha256": source_sha,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": member_sha,
        "native_member_category": "middle_json",
        "node_count": len(nodes),
        "hierarchy_field_count": 0,
        "nodes": nodes,
    }
    hierarchy["replay_digest_sha256"] = _go_domain(
        "mineru-native-hierarchy-provenance-replay.v1", hierarchy
    )
    return hierarchy


def _capture(
    source_sha: str,
    markers: tuple[tuple[str, int, str], ...] = (),
) -> dict[str, object]:
    native_structure = _structure(markers)
    structure = {
        "contract": "mineru-native-structure.v1",
        "pages": [],
        "unsupported": [],
    }
    parser = _parser()
    capture: dict[str, object] = {
        "contract": "mineru-semantic-content-custody.v2",
        "source_sha256": source_sha,
        "attempt": {"attempt_number": 2, "attempt_role": "bounded_upgrade", "generation": 0},
        "raw_structure_sha256": "4" * 64,
        "sanitized_structure_sha256": _sha(_compact(structure)),
        "sanitized_structure": structure,
        "content_snapshot_sha256": _sha("safe snapshot"),
        "content_snapshot": "safe snapshot",
        "capture_identity_sha256": "",
        "parser": parser,
        "calls": {"allocation_post": 1, "upload_put": 1, "status_get": 3, "zip_get": 1},
        "latency_milliseconds": 25,
        "status": "completed",
    }
    if source_sha in {TERMS_SHA, RATE_SHA}:
        member_sha = "2" * 64
        items = _marker_items(source_sha, member_sha, markers)
        capability = "cross_page_sections" if source_sha == TERMS_SHA else "cross_page_tables"
        facts = _cross_page(source_sha, capability, member_sha, items)
        marker = {
            "contract": MARKER_CONTRACT,
            "source_sha256": source_sha,
            "parser_model": "pipeline",
            "mineru_version": "3.4.4",
            "raw_zip_sha256": facts["raw_zip_sha256"],
            "native_member_sha256": member_sha,
            "marker_count": len(items),
            "markers": items,
            "native_hierarchy_provenance": _hierarchy(
                source_sha, member_sha, native_structure
            ),
            "replay_digest_sha256": "",
        }
        replay = {key: marker[key] for key in (
            "contract", "source_sha256", "parser_model", "mineru_version",
            "raw_zip_sha256", "native_member_sha256", "marker_count", "markers",
        )}
        replay["native_hierarchy_replay_sha256"] = cast(
            dict[str, object], marker["native_hierarchy_provenance"]
        )["replay_digest_sha256"]
        marker["replay_digest_sha256"] = _go_domain(
            "mineru-cross-page-marker-provenance-replay.v1", replay
        )
        capture["cross_page_facts"] = facts
        capture["cross_page_marker_provenance"] = marker
    _reseal_capture_identity(capture)
    return capture


def _reseal_capture_identity(capture: dict[str, object]) -> None:
    parser = cast(dict[str, object], capture["parser"])
    identity: dict[str, object] = {
        "contract": capture["contract"],
        "source_sha256": capture["source_sha256"],
        "attempt": capture["attempt"],
        "parser_config_sha256": parser["config_sha256"],
        "raw_structure_sha256": capture["raw_structure_sha256"],
        "sanitized_structure_sha256": capture["sanitized_structure_sha256"],
        "content_snapshot_sha256": capture["content_snapshot_sha256"],
    }
    if capture["source_sha256"] in {TERMS_SHA, RATE_SHA}:
        facts = cast(dict[str, object], capture["cross_page_facts"])
        provenance = cast(dict[str, object], capture["cross_page_marker_provenance"])
        identity["cross_page_projection_sha256"] = facts["projection_sha256"]
        identity["marker_provenance_replay_sha256"] = provenance["replay_digest_sha256"]
    capture["capture_identity_sha256"] = _sha(_compact(identity))


def _write_inputs(
    root: Path,
    *,
    terms: tuple[tuple[str, int, str], ...] = (("cross_page", 0, "text"),),
    rate: tuple[tuple[str, int, str], ...] = (("cross_page", 0, "table"),),
) -> tuple[Path, Path, Path]:
    root.mkdir(mode=0o700)
    paths = tuple(root / name for name in ("terms.json", "brochure.json", "rate.json"))
    payloads = (
        _capture(TERMS_SHA, terms),
        _capture(BROCHURE_SHA),
        _capture(RATE_SHA, rate),
    )
    for path, payload in zip(paths, payloads, strict=True):
        path.write_bytes(_compact(payload) + b"\n")
        path.chmod(0o600)
    return (paths[0], paths[1], paths[2])


def test_current_single_endpoint_custody_exports_unbound_recomputable_authority(
    tmp_path: Path,
) -> None:
    envelope = export_marker_authority_envelope_596_1(
        _write_inputs(tmp_path / "private")
    )

    assert envelope.contract == "mineru-marker-authority-envelope-596-1.v1"
    assert envelope.source_order == ("terms", "brochure", "rate")
    assert [source.role for source in envelope.marker_sources] == ["terms", "rate"]
    assert [len(source.markers) for source in envelope.marker_sources] == [1, 1]
    assert envelope.relation_authority == "UNBOUND"
    assert all(source.relation_authority == "UNBOUND" for source in envelope.marker_sources)
    assert envelope.envelope_sha256 == recompute_marker_authority_envelope_sha256(envelope)
    marker = envelope.marker_sources[0].markers[0]
    assert marker.structural_path_preimage.structural_path == "p0/b0"
    assert marker.structural_path_sha256 == _go_domain(
        "mineru-cross-page-marker-path.v1",
        TERMS_SHA + "\0" + "2" * 64 + "\0p0/b0",
    )
    assert marker.node_identity_sha256 == canonical_hash(
        "mineru-marker-canonical-node.v1",
        marker.node_identity_preimage.model_dump(mode="json"),
    )
    for source in envelope.marker_sources:
        for binding in (
            source.cross_page_facts_custody,
            source.marker_provenance_custody,
            source.intake_custody,
        ):
            assert binding.sha256 == canonical_hash(
                binding.object_type, json.loads(binding.canonical_preimage_json)
            )


def test_nested_marker_path_is_preserved_without_top_level_path_invention(
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path / "private")
    raw = json.loads(paths[0].read_bytes())
    provenance = cast(dict[str, Any], raw["cross_page_marker_provenance"])
    marker = cast(list[dict[str, Any]], provenance["markers"])[0]
    structural_path = "p0/b0/lines/2/spans/0"
    marker["structural_path"] = structural_path
    marker["structural_path_sha256"] = _go_domain(
        "mineru-cross-page-marker-path.v1",
        TERMS_SHA + "\0" + cast(str, provenance["native_member_sha256"]) +
        "\0" + structural_path,
    )
    marker_preimage = {
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
    }
    marker["marker_sha256"] = _go_domain(
        "mineru-cross-page-marker-evidence.v1", marker_preimage
    )
    replay = {
        key: provenance[key]
        for key in (
            "contract", "source_sha256", "parser_model", "mineru_version",
            "raw_zip_sha256", "native_member_sha256", "marker_count", "markers",
        )
    }
    replay["native_hierarchy_replay_sha256"] = cast(
        dict[str, Any], provenance["native_hierarchy_provenance"]
    )["replay_digest_sha256"]
    provenance["replay_digest_sha256"] = _go_domain(
        "mineru-cross-page-marker-provenance-replay.v1", replay
    )
    _reseal_capture_identity(raw)
    paths[0].write_bytes(_compact(raw) + b"\n")
    paths[0].chmod(0o600)

    envelope = export_marker_authority_envelope_596_1(paths)

    assert (
        envelope.marker_sources[0].markers[0]
        .structural_path_preimage.structural_path
        == structural_path
    )


def test_future_multiple_marker_fixture_stays_unbound_and_canonical(
    tmp_path: Path,
) -> None:
    envelope = export_marker_authority_envelope_596_1(
        _write_inputs(
            tmp_path / "private",
            terms=(("cross_page", 1, "text"), ("lines_deleted", 0, "title")),
            rate=(("cross_page", 1, "table"), ("lines_deleted", 0, "table")),
        )
    )

    assert [len(source.markers) for source in envelope.marker_sources] == [2, 2]
    assert envelope.relation_authority == "UNBOUND"
    assert all(
        source.markers == tuple(sorted(
            source.markers,
            key=lambda item: (
                item.page_index, item.structural_path_sha256, item.marker_kind
            ),
        ))
        for source in envelope.marker_sources
    )


@pytest.mark.parametrize("mode", [0o644, 0o400, 0o000])
def test_unsafe_file_mode_fails_closed(tmp_path: Path, mode: int) -> None:
    paths = _write_inputs(tmp_path / "private")
    paths[0].chmod(mode)

    with pytest.raises(MarkerAuthorityExportError, match="CUSTODY_FILE_UNSAFE"):
        export_marker_authority_envelope_596_1(paths)


def test_reordered_source_paths_and_symlink_fail_closed(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path / "private")
    with pytest.raises(MarkerAuthorityExportError, match="SOURCE_ORDER_INVALID"):
        export_marker_authority_envelope_596_1((paths[2], paths[1], paths[0]))

    link = tmp_path / "private" / "terms-link.json"
    link.symlink_to(paths[0])
    with pytest.raises(MarkerAuthorityExportError, match="CUSTODY_FILE_UNSAFE"):
        export_marker_authority_envelope_596_1((link, paths[1], paths[2]))


def test_noncanonical_json_and_path_preimage_drift_fail_closed(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path / "private")
    raw = json.loads(paths[0].read_bytes())
    paths[0].write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    paths[0].chmod(0o600)
    with pytest.raises(MarkerAuthorityExportError, match="CUSTODY_JSON_NONCANONICAL"):
        export_marker_authority_envelope_596_1(paths)


def test_go_encoding_json_html_escaping_is_canonical_custody(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path / "private")
    raw = json.loads(paths[0].read_bytes())
    raw["content_snapshot"] = "<table>&</table>"
    raw["content_snapshot_sha256"] = _sha(raw["content_snapshot"])
    _reseal_capture_identity(raw)
    encoded = _compact(raw)
    go_encoded = (
        encoded.replace(b"&", b"\\u0026")
        .replace(b"<", b"\\u003c")
        .replace(b">", b"\\u003e")
    )
    paths[0].write_bytes(go_encoded + b"\n")
    paths[0].chmod(0o600)

    envelope = export_marker_authority_envelope_596_1(paths)

    assert envelope.marker_sources[0].source_sha256 == TERMS_SHA

    paths = _write_inputs(tmp_path / "other")
    raw = json.loads(paths[0].read_bytes())
    provenance = cast(dict[str, Any], raw["cross_page_marker_provenance"])
    hierarchy = cast(dict[str, Any], provenance["native_hierarchy_provenance"])
    nodes = cast(list[dict[str, Any]], hierarchy["nodes"])
    nodes[0]["structural_path"] = "p0/b9"
    _reseal_capture_identity(raw)
    paths[0].write_bytes(_compact(raw) + b"\n")
    paths[0].chmod(0o600)
    with pytest.raises(MarkerAuthorityExportError, match="CUSTODY_AUTHORITY_INVALID"):
        export_marker_authority_envelope_596_1(paths)


def test_path_replacement_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_inputs(tmp_path / "private")
    original_read = os.read
    replaced = False

    def replacing_read(fd: int, size: int) -> bytes:
        nonlocal replaced
        result = original_read(fd, size)
        if not replaced and result:
            replaced = True
            replacement = tmp_path / "private" / "replacement.json"
            replacement.write_bytes(paths[0].read_bytes())
            replacement.chmod(0o600)
            replacement.replace(paths[0])
        return result

    monkeypatch.setattr(os, "read", replacing_read)
    with pytest.raises(MarkerAuthorityExportError, match="CUSTODY_SNAPSHOT_DRIFT"):
        export_marker_authority_envelope_596_1(paths)


def test_errors_and_envelope_never_expose_private_material(tmp_path: Path) -> None:
    secret = "api_key=must-not-survive"
    body = "private insurance body"
    absolute = str(tmp_path / "private")
    paths = _write_inputs(Path(absolute))
    raw = json.loads(paths[0].read_bytes())
    raw["content_snapshot"] = secret + body + absolute
    paths[0].write_bytes(_compact(raw) + b"\n")
    paths[0].chmod(0o600)

    with pytest.raises(MarkerAuthorityExportError) as caught:
        export_marker_authority_envelope_596_1(paths)
    rendered = repr(caught.value) + str(caught.value)
    assert secret not in rendered
    assert body not in rendered
    assert absolute not in rendered
    assert caught.value.__cause__ is None


def test_missing_marker_authority_returns_zero_output(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path / "private")
    raw = json.loads(paths[0].read_bytes())
    raw.pop("cross_page_marker_provenance")
    paths[0].write_bytes(_compact(raw) + b"\n")
    paths[0].chmod(0o600)

    with pytest.raises(MarkerAuthorityExportError, match="MARKER_AUTHORITY_UNAVAILABLE"):
        export_marker_authority_envelope_596_1(paths)
