"""Pure bytes intake for the exact 596-1 MinerU capture custody contract."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Final, Literal, Never, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBytes,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SourceRole = Literal["terms", "brochure", "rate"]
CrossPageStatus = Literal[
    "NATIVE_CROSS_PAGE_FACT_PRESENT",
    "NATIVE_CROSS_PAGE_FACT_ABSENT",
    "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS",
    "NATIVE_CROSS_PAGE_FACT_NOT_AVAILABLE",
]
MarkerKind = Literal["cross_page", "lines_deleted"]
HierarchyStatus = Literal[
    "NATIVE_HIERARCHY_PROVENANCE_CAPTURED",
    "HIERARCHY_PROVENANCE_NOT_CAPTURED",
]

CAPTURE_CONTRACT: Final = "mineru-semantic-content-custody.v2"
BUNDLE_CONTRACT: Final = "mineru-capture-intake-596-1.v1"
CROSS_PAGE_CONTRACT: Final = "mineru-native-cross-page-facts.v1"
MARKER_PROVENANCE_CONTRACT: Final = "mineru-native-cross-page-marker-provenance.v1"
EXPECTED_SOURCES: Final[tuple[tuple[SourceRole, str], ...]] = (
    ("terms", "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"),
    ("brochure", "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"),
    ("rate", "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"),
)
_PRIVATE_PATH = re.compile(
    r"(?i)(?:^|[\s\"'(])(?:/(?!/)[^\s]+|[a-z]:[\\/]|\\\\[^\\/\s]+[\\/])"
)
_SECRET = re.compile(
    r"(?i)(?:\bbearer\s+[a-z0-9._-]+|\b(?:api[_-]?key|token|secret|authorization)\s*[:=])"
)
_SIGNED_URL = re.compile(r"(?i)https?://[^\s]+[?&](?:signature|sig|token|x-amz-|x-oss-)")


class CaptureIntakeError(ValueError):
    """Fixed-code failure that never echoes untrusted capture material."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)

    def __repr__(self) -> str:
        return f"CaptureIntakeError({self.reason_code!r})"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class CaptureAttemptV2(_FrozenModel):
    attempt_number: Literal[2]
    attempt_role: Literal["bounded_upgrade"]
    generation: Literal[0]


class CaptureParserV2(_FrozenModel):
    engine: Literal["mineru_cloud"]
    implementation: Literal["NewMinerUCloudReader"]
    native_structure_schema: Literal["mineru-native-structure.v1"]
    model: Literal["pipeline"]
    formula: Literal[True]
    table: Literal[True]
    ocr: Literal[True]
    language: Literal["ch"]
    config_sha256: Sha256Hex


class CaptureCallsV2(_FrozenModel):
    allocation_post: Literal[1]
    upload_put: Literal[1]
    status_get: Annotated[StrictInt, Field(ge=1, le=190)]
    zip_get: Literal[1]


class NativeMemberV1(_FrozenModel):
    category: Literal[
        "middle_json",
        "content_list_v2_json",
        "content_list_json",
        "model_json",
        "layout_pdf",
        "span_pdf",
        "origin_pdf",
        "markdown",
        "image",
    ]
    size: Annotated[StrictInt, Field(ge=0)]
    sha256: Sha256Hex


class NativeRelationV1(_FrozenModel):
    kind: Literal["section", "table"]
    source_page_index: Annotated[StrictInt, Field(ge=1)]
    target_page_index: Annotated[StrictInt, Field(ge=0)]
    source_id_hash: Sha256Hex
    target_id_hash: Sha256Hex

    @model_validator(mode="after")
    def _ordered_pages(self) -> Self:
        if self.source_page_index <= self.target_page_index:
            raise ValueError("relation pages are not cross-page ordered")
        return self


class NativeCrossPageFactsV1(_FrozenModel):
    contract: Literal["mineru-native-cross-page-facts.v1"]
    status: CrossPageStatus
    required_capability: Literal["cross_page_sections", "cross_page_tables"]
    source_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex | None = None
    member_inventory_sha256: Sha256Hex
    projection_sha256: Sha256Hex
    relation_count: Annotated[StrictInt, Field(ge=0)]
    ambiguous_marker_count: Annotated[StrictInt, Field(ge=0)]
    ambiguous_observation_hashes: tuple[Sha256Hex, ...]
    members: tuple[NativeMemberV1, ...]
    relations: tuple[NativeRelationV1, ...]


class NativeCrossPageMarkerEvidenceV1(_FrozenModel):
    marker_kind: MarkerKind
    page_index: Annotated[StrictInt, Field(ge=0)]
    structural_path: Annotated[
        StrictStr,
        StringConstraints(
            pattern=r"^p[0-9]+/b[0-9]+(?:/(?:blocks|lines|spans)/[0-9]+)*$"
        ),
    ] | None = None
    structural_path_sha256: Sha256Hex
    node_type: Annotated[
        StrictStr, StringConstraints(pattern=r"^[a-z0-9_-]{1,64}$")
    ]
    local_index: Annotated[StrictInt, Field(ge=0)]
    marker_sha256: Sha256Hex

    @model_validator(mode="after")
    def _privacy_safe_node_type(self) -> Self:
        if any(
            token in self.node_type
            for token in (
                "secret",
                "token",
                "api_key",
                "apikey",
                "bearer",
                "credential",
                "password",
                "url",
                "path",
            )
        ):
            raise ValueError("private marker node type")
        return self


class NativeHierarchyNodeV1(_FrozenModel):
    page_index: Annotated[StrictInt, Field(ge=0)]
    node_type: Annotated[StrictStr, StringConstraints(pattern=r"^[a-z0-9_-]{1,64}$")]
    local_index: Annotated[StrictInt, Field(ge=0)]
    reading_order: Annotated[StrictInt, Field(ge=0)]
    structural_path: Annotated[StrictStr, StringConstraints(pattern=r"^p[0-9]+/b[0-9]+$")]
    structural_path_sha256: Sha256Hex
    bbox_present: bool
    bbox_sha256: Sha256Hex
    text_level: Annotated[StrictInt, Field(ge=1, le=32)] | None = None
    node_preimage_sha256: Sha256Hex


class NativeHierarchyProvenanceV1(_FrozenModel):
    contract: Literal["mineru-native-hierarchy-provenance.v1"]
    status: HierarchyStatus
    source_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    native_member_category: Literal["middle_json"]
    node_count: Annotated[StrictInt, Field(gt=0)]
    hierarchy_field_count: Annotated[StrictInt, Field(ge=0)]
    nodes: tuple[NativeHierarchyNodeV1, ...] = Field(min_length=1)
    replay_digest_sha256: Sha256Hex


class NativeCrossPageMarkerProvenanceV1(_FrozenModel):
    contract: Literal["mineru-native-cross-page-marker-provenance.v1"]
    source_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    marker_count: Annotated[StrictInt, Field(ge=0)]
    markers: tuple[NativeCrossPageMarkerEvidenceV1, ...]
    native_hierarchy_provenance: NativeHierarchyProvenanceV1 | None = None
    replay_digest_sha256: Sha256Hex


class _CapturePayloadV2(_FrozenModel):
    contract: Literal["mineru-semantic-content-custody.v2"]
    source_sha256: Sha256Hex
    attempt: CaptureAttemptV2
    raw_structure_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    sanitized_structure: dict[str, Any]
    content_snapshot_sha256: Sha256Hex
    content_snapshot: StrictStr = Field(min_length=1)
    capture_identity_sha256: Sha256Hex
    parser: CaptureParserV2
    calls: CaptureCallsV2
    latency_milliseconds: Annotated[StrictInt, Field(ge=0)]
    status: Literal["completed"]
    cross_page_facts: NativeCrossPageFactsV1 | None = None
    cross_page_marker_provenance: NativeCrossPageMarkerProvenanceV1 | None = None


class MinerUCaptureEvidenceV2(_FrozenModel):
    contract: Literal["mineru-semantic-content-custody.v2"]
    source_sha256: Sha256Hex
    attempt: CaptureAttemptV2
    raw_structure_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    sanitized_structure: StrictBytes = Field(repr=False, exclude=True)
    content_snapshot_sha256: Sha256Hex
    content_snapshot: StrictStr = Field(min_length=1, repr=False, exclude=True)
    capture_identity_sha256: Sha256Hex
    parser: CaptureParserV2
    calls: CaptureCallsV2
    latency_milliseconds: Annotated[StrictInt, Field(ge=0)]
    status: Literal["completed"]
    cross_page_facts: NativeCrossPageFactsV1 | None = None
    cross_page_marker_provenance: NativeCrossPageMarkerProvenanceV1 | None = None


class MinerUCaptureIntakeItem5961V1(_FrozenModel):
    role: SourceRole
    source_sha256: Sha256Hex
    capture_identity_sha256: Sha256Hex
    cross_page_facts_digest_sha256: Sha256Hex | None
    marker_provenance_digest_sha256: Sha256Hex | None
    intake_digest_sha256: Sha256Hex
    evidence: MinerUCaptureEvidenceV2


class MinerUCaptureBundle5961V1(_FrozenModel):
    contract: Literal["mineru-capture-intake-596-1.v1"]
    sources: tuple[
        MinerUCaptureIntakeItem5961V1,
        MinerUCaptureIntakeItem5961V1,
        MinerUCaptureIntakeItem5961V1,
    ]
    bundle_digest_sha256: Sha256Hex


class _DuplicateKey(Exception):
    pass


def _fail(reason_code: str) -> Never:
    raise CaptureIntakeError(reason_code)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _go_domain_sha256(domain: str, value: object) -> str:
    return _sha256(domain.encode() + b"\0" + _compact(value))


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _reject_float(_: str) -> Never:
    raise ValueError


def _parse_payload(payload: StrictBytes) -> tuple[dict[str, object], bytes]:
    if type(payload) is not bytes or not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        _fail("CAPTURE_BYTES_INVALID")
    try:
        text = payload[:-1].decode("utf-8")
        if "\r" in text:
            _fail("CAPTURE_BYTES_INVALID")
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_reject_float,
        )
    except CaptureIntakeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, ValueError, TypeError):
        _fail("CAPTURE_JSON_INVALID")
    if not isinstance(value, dict):
        _fail("CAPTURE_JSON_INVALID")
    marker = '"sanitized_structure":'
    if text.count(marker) != 1:
        _fail("CAPTURE_STRUCTURE_BYTES_INVALID")
    start = text.index(marker) + len(marker)
    try:
        _, end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        _fail("CAPTURE_STRUCTURE_BYTES_INVALID")
    return value, text[start:end].encode()


def _walk_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, member in value.items():
            strings.extend((key, *_walk_strings(member)))
        return strings
    if isinstance(value, list | tuple):
        return [item for member in value for item in _walk_strings(member)]
    return []


def _privacy_check(structure: object, content: str) -> None:
    for value in _walk_strings(structure):
        if (
            _PRIVATE_PATH.search(value)
            or _SECRET.search(value)
            or _SIGNED_URL.search(value)
            or value.lower().startswith(("http://", "https://"))
        ):
            _fail("CAPTURE_PRIVATE_MATERIAL")
    if _PRIVATE_PATH.search(content) or _SECRET.search(content) or _SIGNED_URL.search(content):
        _fail("CAPTURE_PRIVATE_MATERIAL")


def _validate_parser(parser: CaptureParserV2) -> None:
    preimage = {
        "engine": parser.engine,
        "implementation": parser.implementation,
        "native_structure_schema": parser.native_structure_schema,
        "model": parser.model,
        "formula": parser.formula,
        "table": parser.table,
        "ocr": parser.ocr,
        "language": parser.language,
        "config_sha256": "",
    }
    expected = _sha256(b"mineru-capture-config.v1\0" + _compact(preimage))
    if parser.config_sha256 != expected:
        _fail("CAPTURE_PARSER_IDENTITY_INVALID")


def _validate_cross_page(
    facts: NativeCrossPageFactsV1,
    *,
    source_sha256: str,
    capability: str,
) -> None:
    if facts.source_sha256 != source_sha256 or facts.required_capability != capability:
        _fail("CAPTURE_CROSS_PAGE_IDENTITY_INVALID")
    if facts.status != "NATIVE_CROSS_PAGE_FACT_NOT_AVAILABLE" and (
        facts.native_member_sha256 is None
    ):
        _fail("CAPTURE_CROSS_PAGE_IDENTITY_INVALID")
    members = tuple(sorted(facts.members, key=lambda item: (item.category, item.sha256, item.size)))
    if facts.members != members:
        _fail("CAPTURE_CROSS_PAGE_ORDER_INVALID")
    inventory = [
        {"category": item.category, "size": item.size, "sha256": item.sha256}
        for item in facts.members
    ]
    if facts.member_inventory_sha256 != _sha256(_compact(inventory)):
        _fail("CAPTURE_CROSS_PAGE_HASH_INVALID")
    if facts.ambiguous_observation_hashes != tuple(sorted(facts.ambiguous_observation_hashes)):
        _fail("CAPTURE_CROSS_PAGE_ORDER_INVALID")
    relations = tuple(
        sorted(
            facts.relations,
            key=lambda item: (
                item.source_page_index,
                item.target_page_index,
                item.kind,
                item.source_id_hash,
                item.target_id_hash,
            ),
        )
    )
    if facts.relations != relations or facts.relation_count != len(facts.relations):
        _fail("CAPTURE_CROSS_PAGE_RELATION_INVALID")
    if any(
        relation.kind != ("section" if capability == "cross_page_sections" else "table")
        for relation in facts.relations
    ):
        _fail("CAPTURE_CROSS_PAGE_RELATION_INVALID")
    if facts.ambiguous_marker_count != len(facts.ambiguous_observation_hashes):
        _fail("CAPTURE_CROSS_PAGE_RELATION_INVALID")
    if facts.status == "NATIVE_CROSS_PAGE_FACT_PRESENT":
        valid_status = bool(facts.relations) and facts.ambiguous_marker_count == 0
    elif facts.status == "NATIVE_CROSS_PAGE_FACT_ABSENT":
        valid_status = not facts.relations and facts.ambiguous_marker_count == 0
    elif facts.status == "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS":
        valid_status = not facts.relations and facts.ambiguous_marker_count > 0
    else:
        valid_status = not facts.relations and facts.ambiguous_marker_count == 0
    if not valid_status:
        _fail("CAPTURE_CROSS_PAGE_STATUS_INVALID")
    projection = {
        "contract": facts.contract,
        "status": facts.status,
        "required_capability": facts.required_capability,
        "source_sha256": facts.source_sha256,
        "parser_model": facts.parser_model,
        "mineru_version": facts.mineru_version,
        "relation_count": facts.relation_count,
        "ambiguous_marker_count": facts.ambiguous_marker_count,
        "ambiguous_observation_hashes": list(facts.ambiguous_observation_hashes),
        "relations": [relation.model_dump(mode="json") for relation in facts.relations],
    }
    if facts.projection_sha256 != _sha256(_compact(projection)):
        _fail("CAPTURE_CROSS_PAGE_HASH_INVALID")


def _validate_marker_provenance(
    provenance: NativeCrossPageMarkerProvenanceV1,
    *,
    source_sha256: str,
    facts: NativeCrossPageFactsV1,
) -> None:
    if (
        provenance.source_sha256 != source_sha256
        or provenance.parser_model != facts.parser_model
        or provenance.mineru_version != facts.mineru_version
        or provenance.raw_zip_sha256 != facts.raw_zip_sha256
        or provenance.native_member_sha256 != facts.native_member_sha256
        or provenance.marker_count != len(provenance.markers)
        or provenance.marker_count != facts.ambiguous_marker_count
    ):
        _fail("CAPTURE_MARKER_IDENTITY_INVALID")
    hierarchy = provenance.native_hierarchy_provenance
    if hierarchy is not None:
        _validate_native_hierarchy(
            hierarchy,
            source_sha256=source_sha256,
            facts=facts,
        )
    expected_order = tuple(
        sorted(
            provenance.markers,
            key=lambda item: (
                item.page_index,
                item.structural_path_sha256,
                item.marker_kind,
            ),
        )
    )
    if provenance.markers != expected_order:
        _fail("CAPTURE_MARKER_ORDER_INVALID")
    seen: set[tuple[str, str]] = set()
    for marker in provenance.markers:
        identity = (marker.marker_kind, marker.structural_path_sha256)
        if identity in seen:
            _fail("CAPTURE_MARKER_MEMBERSHIP_INVALID")
        seen.add(identity)
        if marker.structural_path is not None:
            path_parts = marker.structural_path.split("/")
            if (
                path_parts[0] != f"p{marker.page_index}"
                or int(path_parts[-1].removeprefix("b")) != marker.local_index
                or marker.structural_path_sha256
                != _sha256(
                    (
                        "mineru-cross-page-marker-path.v1\0"
                        + provenance.source_sha256
                        + "\0"
                        + provenance.native_member_sha256
                        + "\0"
                        + marker.structural_path
                    ).encode()
                )
            ):
                _fail("CAPTURE_MARKER_PATH_INVALID")
        item_preimage = {
            "contract": MARKER_PROVENANCE_CONTRACT,
            "source_sha256": provenance.source_sha256,
            "parser_model": provenance.parser_model,
            "mineru_version": provenance.mineru_version,
            "native_member_sha256": provenance.native_member_sha256,
            "marker_kind": marker.marker_kind,
            "page_index": marker.page_index,
            "structural_path_sha256": marker.structural_path_sha256,
            "node_type": marker.node_type,
            "local_index": marker.local_index,
        }
        if marker.marker_sha256 != _go_domain_sha256(
            "mineru-cross-page-marker-evidence.v1", item_preimage
        ):
            _fail("CAPTURE_MARKER_HASH_INVALID")
    replay_preimage = {
        "contract": provenance.contract,
        "source_sha256": provenance.source_sha256,
        "parser_model": provenance.parser_model,
        "mineru_version": provenance.mineru_version,
        "raw_zip_sha256": provenance.raw_zip_sha256,
        "native_member_sha256": provenance.native_member_sha256,
        "marker_count": provenance.marker_count,
        "markers": [
            marker.model_dump(mode="json", exclude_none=True)
            for marker in provenance.markers
        ],
    }
    if hierarchy is not None:
        replay_preimage["native_hierarchy_replay_sha256"] = hierarchy.replay_digest_sha256
    if provenance.replay_digest_sha256 != _go_domain_sha256(
        "mineru-cross-page-marker-provenance-replay.v1", replay_preimage
    ):
        _fail("CAPTURE_MARKER_HASH_INVALID")


def marker_provenance_custody_preimage(
    provenance: NativeCrossPageMarkerProvenanceV1,
) -> dict[str, object]:
    """Return the body-free marker custody preimage used beyond intake."""

    value: dict[str, object] = {
        "contract": provenance.contract,
        "source_sha256": provenance.source_sha256,
        "parser_model": provenance.parser_model,
        "mineru_version": provenance.mineru_version,
        "raw_zip_sha256": provenance.raw_zip_sha256,
        "native_member_sha256": provenance.native_member_sha256,
        "marker_count": provenance.marker_count,
        "markers": [
            marker.model_dump(mode="json", exclude_none=True)
            for marker in provenance.markers
        ],
    }
    if provenance.native_hierarchy_provenance is not None:
        value["native_hierarchy_replay_sha256"] = (
            provenance.native_hierarchy_provenance.replay_digest_sha256
        )
    value["replay_digest_sha256"] = provenance.replay_digest_sha256
    return value


def _validate_native_hierarchy(
    hierarchy: NativeHierarchyProvenanceV1,
    *,
    source_sha256: str,
    facts: NativeCrossPageFactsV1,
) -> None:
    if (
        hierarchy.source_sha256 != source_sha256
        or hierarchy.parser_model != facts.parser_model
        or hierarchy.mineru_version != facts.mineru_version
        or hierarchy.raw_zip_sha256 != facts.raw_zip_sha256
        or hierarchy.native_member_sha256 != facts.native_member_sha256
        or hierarchy.node_count != len(hierarchy.nodes)
    ):
        _fail("CAPTURE_HIERARCHY_IDENTITY_INVALID")
    hierarchy_count = 0
    seen: set[str] = set()
    for index, node in enumerate(hierarchy.nodes):
        expected_path = f"p{node.page_index}/b{node.local_index}"
        expected_path_sha = _sha256(
            (
                "mineru-cross-page-marker-path.v1\0"
                + source_sha256
                + "\0"
                + hierarchy.native_member_sha256
                + "\0"
                + expected_path
            ).encode()
        )
        if (
            node.reading_order != index
            or node.structural_path != expected_path
            or node.structural_path_sha256 != expected_path_sha
            or node.structural_path_sha256 in seen
        ):
            _fail("CAPTURE_HIERARCHY_ORDER_INVALID")
        seen.add(node.structural_path_sha256)
        if node.text_level is not None:
            hierarchy_count += 1
        if not node.bbox_present and node.bbox_sha256 != _sha256(
            b"mineru-native-hierarchy-bbox.v1\0null"
        ):
            _fail("CAPTURE_HIERARCHY_HASH_INVALID")
        node_preimage = {
            "contract": "mineru-native-hierarchy-provenance.v1.node",
            "source_sha256": hierarchy.source_sha256,
            "parser_model": hierarchy.parser_model,
            "mineru_version": hierarchy.mineru_version,
            "raw_zip_sha256": hierarchy.raw_zip_sha256,
            "native_member_sha256": hierarchy.native_member_sha256,
            "page_index": node.page_index,
            "node_type": node.node_type,
            "local_index": node.local_index,
            "reading_order": node.reading_order,
            "structural_path": node.structural_path,
            "structural_path_sha256": node.structural_path_sha256,
            "bbox_present": node.bbox_present,
            "bbox_sha256": node.bbox_sha256,
            "text_level": node.text_level,
        }
        if node.node_preimage_sha256 != _go_domain_sha256(
            "mineru-native-hierarchy-node.v1", node_preimage
        ):
            _fail("CAPTURE_HIERARCHY_HASH_INVALID")
    if (
        hierarchy.hierarchy_field_count != hierarchy_count
        or (hierarchy.status == "NATIVE_HIERARCHY_PROVENANCE_CAPTURED")
        != (hierarchy_count > 0)
    ):
        _fail("CAPTURE_HIERARCHY_STATUS_INVALID")
    replay_preimage = hierarchy.model_dump(mode="json", exclude={"replay_digest_sha256"})
    if hierarchy.replay_digest_sha256 != _go_domain_sha256(
        "mineru-native-hierarchy-provenance-replay.v1", replay_preimage
    ):
        _fail("CAPTURE_HIERARCHY_HASH_INVALID")


def _intake_one(
    payload: bytes,
    role: SourceRole,
    source_sha256: str,
) -> MinerUCaptureIntakeItem5961V1:
    raw, structure_bytes = _parse_payload(payload)
    cross_page_present = "cross_page_facts" in raw
    marker_present = "cross_page_marker_provenance" in raw
    try:
        payload_model = _CapturePayloadV2.model_validate(raw)
    except ValidationError:
        _fail("CAPTURE_SHAPE_INVALID")
    if payload_model.source_sha256 != source_sha256:
        _fail("CAPTURE_SOURCE_IDENTITY_INVALID")
    _validate_parser(payload_model.parser)
    if payload_model.sanitized_structure_sha256 != _sha256(structure_bytes):
        _fail("CAPTURE_STRUCTURE_HASH_INVALID")
    if payload_model.content_snapshot_sha256 != _sha256(payload_model.content_snapshot.encode()):
        _fail("CAPTURE_CONTENT_HASH_INVALID")
    _privacy_check(payload_model.sanitized_structure, payload_model.content_snapshot)
    if cross_page_present and not marker_present:
        _fail("CAPTURE_MARKER_ENVELOPE_INVALID")
    if marker_present and not cross_page_present:
        _fail("CAPTURE_CROSS_PAGE_ENVELOPE_INVALID")
    if cross_page_present:
        if not cross_page_present or payload_model.cross_page_facts is None:
            _fail("CAPTURE_CROSS_PAGE_ENVELOPE_INVALID")
        if not marker_present or payload_model.cross_page_marker_provenance is None:
            _fail("CAPTURE_MARKER_ENVELOPE_INVALID")
        capability = (
            "cross_page_tables" if role == "rate" else "cross_page_sections"
        )
        _validate_cross_page(
            payload_model.cross_page_facts,
            source_sha256=source_sha256,
            capability=capability,
        )
        _validate_marker_provenance(
            payload_model.cross_page_marker_provenance,
            source_sha256=source_sha256,
            facts=payload_model.cross_page_facts,
        )
    capture_preimage = {
        "contract": payload_model.contract,
        "source_sha256": payload_model.source_sha256,
        "attempt": payload_model.attempt.model_dump(mode="json"),
        "parser_config_sha256": payload_model.parser.config_sha256,
        "raw_structure_sha256": payload_model.raw_structure_sha256,
        "sanitized_structure_sha256": payload_model.sanitized_structure_sha256,
        "content_snapshot_sha256": payload_model.content_snapshot_sha256,
    }
    if cross_page_present:
        facts = payload_model.cross_page_facts
        markers = payload_model.cross_page_marker_provenance
        if facts is None or markers is None:
            _fail("CAPTURE_MARKER_ENVELOPE_INVALID")
        capture_preimage["cross_page_projection_sha256"] = (
            facts.projection_sha256
        )
        capture_preimage["marker_provenance_replay_sha256"] = (
            markers.replay_digest_sha256
        )
    if payload_model.capture_identity_sha256 != _sha256(_compact(capture_preimage)):
        _fail("CAPTURE_IDENTITY_HASH_INVALID")
    evidence = MinerUCaptureEvidenceV2(
        contract=payload_model.contract,
        source_sha256=payload_model.source_sha256,
        attempt=payload_model.attempt,
        raw_structure_sha256=payload_model.raw_structure_sha256,
        sanitized_structure_sha256=payload_model.sanitized_structure_sha256,
        sanitized_structure=structure_bytes,
        content_snapshot_sha256=payload_model.content_snapshot_sha256,
        content_snapshot=payload_model.content_snapshot,
        capture_identity_sha256=payload_model.capture_identity_sha256,
        parser=payload_model.parser,
        calls=payload_model.calls,
        latency_milliseconds=payload_model.latency_milliseconds,
        status=payload_model.status,
        cross_page_facts=payload_model.cross_page_facts,
        cross_page_marker_provenance=payload_model.cross_page_marker_provenance,
    )
    cross_page_digest = (
        canonical_hash(
            "mineru-native-cross-page-facts-custody.v1",
            evidence.cross_page_facts.model_dump(mode="json", exclude_none=True),
        )
        if evidence.cross_page_facts is not None
        else None
    )
    marker_digest = (
        canonical_hash(
            "mineru-cross-page-marker-provenance-custody.v1",
            marker_provenance_custody_preimage(evidence.cross_page_marker_provenance),
        )
        if evidence.cross_page_marker_provenance is not None
        else None
    )
    intake_digest = canonical_hash(
        "mineru-capture-intake-596-1.v1",
        {
            "role": role,
            "source_sha256": source_sha256,
            "capture_identity_sha256": evidence.capture_identity_sha256,
            "parser_config_sha256": evidence.parser.config_sha256,
            "raw_structure_sha256": evidence.raw_structure_sha256,
            "sanitized_structure_sha256": evidence.sanitized_structure_sha256,
            "content_snapshot_sha256": evidence.content_snapshot_sha256,
            "calls": evidence.calls.model_dump(mode="json"),
            "latency_milliseconds": evidence.latency_milliseconds,
            "status": evidence.status,
            "cross_page_facts_digest_sha256": cross_page_digest,
            "marker_provenance_digest_sha256": marker_digest,
        },
    )
    return MinerUCaptureIntakeItem5961V1(
        role=role,
        source_sha256=source_sha256,
        capture_identity_sha256=evidence.capture_identity_sha256,
        cross_page_facts_digest_sha256=cross_page_digest,
        marker_provenance_digest_sha256=marker_digest,
        intake_digest_sha256=intake_digest,
        evidence=evidence,
    )


def intake_mineru_capture_bundle_596_1(
    payloads: tuple[StrictBytes, StrictBytes, StrictBytes],
) -> MinerUCaptureBundle5961V1:
    """Validate three exact in-memory Go capture payloads without external operations."""

    if type(payloads) is not tuple or len(payloads) != 3:
        _fail("CAPTURE_BUNDLE_SHAPE_INVALID")
    sources = (
        _intake_one(payloads[0], *EXPECTED_SOURCES[0]),
        _intake_one(payloads[1], *EXPECTED_SOURCES[1]),
        _intake_one(payloads[2], *EXPECTED_SOURCES[2]),
    )
    bundle_digest = canonical_hash(
        "mineru-capture-bundle-596-1.v1",
        {
            "contract": BUNDLE_CONTRACT,
            "sources": [
                {
                    "role": source.role,
                    "source_sha256": source.source_sha256,
                    "capture_identity_sha256": source.capture_identity_sha256,
                    "intake_digest_sha256": source.intake_digest_sha256,
                }
                for source in sources
            ],
        },
    )
    return MinerUCaptureBundle5961V1(
        contract=BUNDLE_CONTRACT,
        sources=sources,
        bundle_digest_sha256=bundle_digest,
    )


__all__ = [
    "CaptureIntakeError",
    "MinerUCaptureBundle5961V1",
    "MinerUCaptureEvidenceV2",
    "MinerUCaptureIntakeItem5961V1",
    "NativeCrossPageMarkerEvidenceV1",
    "NativeCrossPageMarkerProvenanceV1",
    "intake_mineru_capture_bundle_596_1",
]
