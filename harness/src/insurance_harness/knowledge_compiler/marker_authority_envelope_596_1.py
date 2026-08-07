"""Privacy-safe public marker authority exported from exact 091 custody."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import traceback
from pathlib import Path
from typing import Annotated, Final, Literal, Never, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    CaptureIntakeError,
    MinerUCaptureBundle5961V1,
    MinerUCaptureIntakeItem5961V1,
    NativeCrossPageMarkerEvidenceV1,
    NativeCrossPageMarkerProvenanceV1,
    intake_mineru_capture_bundle_596_1,
    marker_provenance_custody_preimage,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SourceRole = Literal["terms", "brochure", "rate"]
MarkerSourceRole = Literal["terms", "brochure", "rate"]
MarkerKind = Literal["cross_page", "lines_deleted"]

ENVELOPE_CONTRACT: Final = "mineru-marker-authority-envelope-596-1.v1"
PRODUCT_VERSION: Final = "596-1"
SOURCE_ORDER: Final[tuple[SourceRole, SourceRole, SourceRole]] = (
    "terms",
    "brochure",
    "rate",
)
EXPECTED_SOURCE_SHA256: Final[tuple[str, ...]] = (
    "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
)
_MAX_CAPTURE_BYTES: Final = 512 * 1024 * 1024


class MarkerAuthorityExportError(ValueError):
    """Fixed, non-echoing export failure."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)

    def __repr__(self) -> str:
        return f"MarkerAuthorityExportError({self.reason_code!r})"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class PrivateContentDigestV1(_FrozenModel):
    scope: Literal["raw_zip_bytes", "native_member_bytes"]
    sha256: Sha256Hex
    preimage_authority: Literal["091_VERIFIED_PRIVATE_BYTES"]


class CanonicalDigestBindingV1(_FrozenModel):
    object_type: Literal[
        "mineru-native-cross-page-facts-custody.v1",
        "mineru-cross-page-marker-provenance-custody.v1",
        "mineru-capture-intake-596-1.v1",
    ]
    canonical_preimage_json: StrictStr
    sha256: Sha256Hex

    @model_validator(mode="after")
    def _canonical_and_recomputable(self) -> Self:
        try:
            value = json.loads(self.canonical_preimage_json)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("canonical digest preimage") from exc
        if _compact(value).decode() != self.canonical_preimage_json:
            raise ValueError("canonical digest preimage")
        if canonical_hash(self.object_type, value) != self.sha256:
            raise ValueError("canonical digest mismatch")
        return self


class CaptureIdentityPreimageV1(_FrozenModel):
    contract: Literal["mineru-semantic-content-custody.v2"]
    source_sha256: Sha256Hex
    attempt_number: Literal[2]
    attempt_role: Literal["bounded_upgrade"]
    generation: Literal[0]
    parser_config_sha256: Sha256Hex
    raw_structure_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    content_snapshot_sha256: Sha256Hex
    cross_page_projection_sha256: Sha256Hex
    marker_provenance_replay_sha256: Sha256Hex


class StructuralPathPreimageV1(_FrozenModel):
    contract: Literal["mineru-cross-page-marker-path.v1"]
    source_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    structural_path: Annotated[
        StrictStr,
        StringConstraints(
            pattern=r"^p[0-9]+/b[0-9]+(?:/(?:blocks|lines|spans)/[0-9]+)*$"
        ),
    ]


class CanonicalNodePreimageV1(_FrozenModel):
    contract: Literal["mineru-marker-canonical-node.v1"]
    source_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    page_index: Annotated[StrictInt, Field(ge=0)]
    structural_path_sha256: Sha256Hex
    node_type: StrictStr
    local_index: Annotated[StrictInt, Field(ge=0)]


class MarkerEvidencePreimageV1(_FrozenModel):
    contract: Literal["mineru-native-cross-page-marker-provenance.v1"]
    source_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    native_member_sha256: Sha256Hex
    marker_kind: MarkerKind
    page_index: Annotated[StrictInt, Field(ge=0)]
    structural_path_sha256: Sha256Hex
    node_type: StrictStr
    local_index: Annotated[StrictInt, Field(ge=0)]


class MarkerAuthorityV1(_FrozenModel):
    marker_kind: MarkerKind
    page_index: Annotated[StrictInt, Field(ge=0)]
    node_type: StrictStr
    local_index: Annotated[StrictInt, Field(ge=0)]
    structural_path_preimage: StructuralPathPreimageV1
    structural_path_sha256: Sha256Hex
    node_identity_preimage: CanonicalNodePreimageV1
    node_identity_sha256: Sha256Hex
    marker_preimage: MarkerEvidencePreimageV1
    marker_sha256: Sha256Hex


class MarkerReplayPreimageV1(_FrozenModel):
    contract: Literal["mineru-native-cross-page-marker-provenance.v1"]
    source_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    marker_count: Annotated[StrictInt, Field(ge=1)]
    markers: tuple[MarkerEvidencePreimageV1, ...]
    native_hierarchy_replay_sha256: Sha256Hex | None = None


class SourceAuthorityPreimageV1(_FrozenModel):
    contract: Literal["mineru-marker-source-authority.v1"]
    role: MarkerSourceRole
    source_sha256: Sha256Hex
    capture_identity_sha256: Sha256Hex
    parser_config_sha256: Sha256Hex
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    cross_page_facts_digest_sha256: Sha256Hex
    marker_provenance_digest_sha256: Sha256Hex
    marker_replay_digest_sha256: Sha256Hex
    intake_digest_sha256: Sha256Hex
    marker_sha256: tuple[Sha256Hex, ...]
    relation_authority: Literal["UNBOUND"]


class MarkerSourceAuthorityV1(_FrozenModel):
    role: MarkerSourceRole
    source_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    parser_config_sha256: Sha256Hex
    raw_zip: PrivateContentDigestV1
    native_member: PrivateContentDigestV1
    capture_identity_preimage: CaptureIdentityPreimageV1
    capture_identity_sha256: Sha256Hex
    marker_replay_preimage: MarkerReplayPreimageV1
    marker_replay_digest_sha256: Sha256Hex
    cross_page_facts_custody: CanonicalDigestBindingV1
    marker_provenance_custody: CanonicalDigestBindingV1
    intake_custody: CanonicalDigestBindingV1
    markers: tuple[MarkerAuthorityV1, ...]
    relation_authority: Literal["UNBOUND"]
    source_authority_preimage: SourceAuthorityPreimageV1
    source_authority_sha256: Sha256Hex


class BundleDigestPreimageV1(_FrozenModel):
    contract: Literal["mineru-capture-intake-596-1.v1"]
    roles: tuple[SourceRole, SourceRole, SourceRole]
    source_sha256: tuple[Sha256Hex, Sha256Hex, Sha256Hex]
    capture_identity_sha256: tuple[Sha256Hex, Sha256Hex, Sha256Hex]
    intake_digest_sha256: tuple[Sha256Hex, Sha256Hex, Sha256Hex]


class EnvelopePreimageV1(_FrozenModel):
    contract: Literal["mineru-marker-authority-envelope-596-1.v1"]
    product_version: Literal["596-1"]
    source_order: tuple[SourceRole, SourceRole, SourceRole]
    bundle_digest_sha256: Sha256Hex
    marker_source_authority_sha256: tuple[Sha256Hex, ...] = Field(
        min_length=1, max_length=3
    )
    relation_authority: Literal["UNBOUND"]


class MarkerAuthorityEnvelopeV1(_FrozenModel):
    contract: Literal["mineru-marker-authority-envelope-596-1.v1"]
    product_version: Literal["596-1"]
    source_order: tuple[SourceRole, SourceRole, SourceRole]
    bundle_preimage: BundleDigestPreimageV1
    bundle_digest_sha256: Sha256Hex
    marker_sources: tuple[MarkerSourceAuthorityV1, ...] = Field(
        min_length=1, max_length=3
    )
    relation_authority: Literal["UNBOUND"]
    envelope_preimage: EnvelopePreimageV1
    envelope_sha256: Sha256Hex

    @model_validator(mode="after")
    def _exact_roles(self) -> Self:
        roles = tuple(source.role for source in self.marker_sources)
        if (
            self.source_order != SOURCE_ORDER
            or len(set(roles)) != len(roles)
            or roles != tuple(role for role in SOURCE_ORDER if role in roles)
            or self.envelope_preimage.marker_source_authority_sha256
            != tuple(source.source_authority_sha256 for source in self.marker_sources)
        ):
            raise ValueError("marker authority source order")
        return self


def _block(reason_code: str) -> Never:
    raise MarkerAuthorityExportError(reason_code)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _go_compact(value: object) -> bytes:
    """Mirror encoding/json's canonical HTML escaping without changing the value."""

    return (
        _compact(value)
        .replace(b"&", b"\\u0026")
        .replace(b"<", b"\\u003c")
        .replace(b">", b"\\u003e")
        .replace("\u2028".encode(), b"\\u2028")
        .replace("\u2029".encode(), b"\\u2029")
    )


def _go_domain_sha256(domain: str, value: object | str) -> str:
    material = value if isinstance(value, str) else _compact(value).decode()
    return _sha256(domain.encode() + b"\0" + material.encode())


def _same_stat(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _read_private_snapshot(paths: tuple[Path, Path, Path]) -> tuple[bytes, bytes, bytes]:
    if type(paths) is not tuple or len(paths) != 3 or any(
        not isinstance(path, Path) for path in paths
    ):
        _block("CUSTODY_INPUT_INVALID")
    parents = tuple(path.parent for path in paths)
    if parents[0] != parents[1] or parents[1] != parents[2]:
        _block("CUSTODY_DIRECTORY_UNSAFE")
    try:
        parent_stat = os.lstat(parents[0])
    except OSError:
        _block("CUSTODY_DIRECTORY_UNSAFE")
    if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_IMODE(parent_stat.st_mode) != 0o700:
        _block("CUSTODY_DIRECTORY_UNSAFE")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(parents[0], directory_flags)
    except OSError:
        _block("CUSTODY_DIRECTORY_UNSAFE")
    payloads: list[bytes] = []
    try:
        for path in paths:
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(path.name, flags, dir_fd=directory_fd)
            except OSError:
                _block("CUSTODY_FILE_UNSAFE")
            try:
                before = os.fstat(fd)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_size <= 0
                    or before.st_size > _MAX_CAPTURE_BYTES
                ):
                    _block("CUSTODY_FILE_UNSAFE")
                chunks: list[bytes] = []
                remaining = before.st_size + 1
                while remaining > 0:
                    chunk = os.read(fd, min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                payload = b"".join(chunks)
                after = os.fstat(fd)
                current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
                if (
                    len(payload) != before.st_size
                    or not _same_stat(before, after)
                    or before.st_dev != current.st_dev
                    or before.st_ino != current.st_ino
                    or not _same_stat(after, current)
                ):
                    _block("CUSTODY_SNAPSHOT_DRIFT")
                payloads.append(payload)
            finally:
                try:
                    os.close(fd)
                except OSError:
                    _block("CUSTODY_FILE_UNSAFE")
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            _block("CUSTODY_DIRECTORY_UNSAFE")
    return (payloads[0], payloads[1], payloads[2])


def _canonical_payload(payload: bytes) -> dict[str, object]:
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        _block("CUSTODY_JSON_NONCANONICAL")
    try:
        value = json.loads(payload[:-1])
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        _block("CUSTODY_JSON_NONCANONICAL")
    if type(value) is not dict or payload not in {
        _compact(value) + b"\n",
        _go_compact(value) + b"\n",
    }:
        _block("CUSTODY_JSON_NONCANONICAL")
    return value


def _walk_marker_paths(
    value: object,
    *,
    page_index: int,
    structural_path: str,
    local_index: int,
    found: list[tuple[str, int, str, str, int]],
) -> None:
    if type(value) is not dict:
        _block("MARKER_PATH_IDENTITY_INVALID")
    node = value
    for marker_kind in ("cross_page", "lines_deleted"):
        if marker_kind not in node:
            continue
        flag = node[marker_kind]
        if type(flag) is not bool:
            _block("MARKER_PATH_IDENTITY_INVALID")
        if flag:
            node_type = node.get("type")
            if type(node_type) is not str:
                _block("MARKER_PATH_IDENTITY_INVALID")
            found.append((marker_kind, page_index, structural_path, node_type, local_index))
    for key in ("blocks", "lines", "spans"):
        if key not in node:
            continue
        children = node[key]
        if type(children) is not list:
            _block("MARKER_PATH_IDENTITY_INVALID")
        for index, child in enumerate(children):
            _walk_marker_paths(
                child,
                page_index=page_index,
                structural_path=f"{structural_path}/{key}/{index}",
                local_index=index,
                found=found,
            )


def _reconstruct_paths(source: MinerUCaptureIntakeItem5961V1) -> dict[str, str]:
    provenance = source.evidence.cross_page_marker_provenance
    facts = source.evidence.cross_page_facts
    hierarchy = provenance.native_hierarchy_provenance if provenance is not None else None
    if (
        provenance is None
        or facts is None
        or facts.native_member_sha256 is None
        or hierarchy is None
    ):
        _block("MARKER_AUTHORITY_UNAVAILABLE")
    top_level_paths = {
        (node.page_index, node.structural_path): node for node in hierarchy.nodes
    }
    if len(top_level_paths) != len(hierarchy.nodes):
        _block("MARKER_PATH_IDENTITY_INVALID")
    reconstructed: dict[str, str] = {}
    for marker in provenance.markers:
        structural_path = marker.structural_path
        if structural_path is None:
            _block("MARKER_PATH_IDENTITY_INVALID")
        path_parts = structural_path.split("/")
        top_level_path = "/".join(path_parts[:2])
        if (marker.page_index, top_level_path) not in top_level_paths:
            _block("MARKER_PATH_IDENTITY_INVALID")
        identity = "\0".join(
            (
                marker.marker_kind,
                str(marker.page_index),
                marker.structural_path_sha256,
                marker.node_type,
                str(marker.local_index),
            )
        )
        if identity in reconstructed:
            _block("MARKER_MEMBERSHIP_INVALID")
        reconstructed[identity] = structural_path
    if not reconstructed:
        _block("MARKER_PATH_IDENTITY_INVALID")
    return reconstructed


def _marker_preimage(
    provenance: NativeCrossPageMarkerProvenanceV1,
    marker: NativeCrossPageMarkerEvidenceV1,
) -> MarkerEvidencePreimageV1:
    return MarkerEvidencePreimageV1(
        contract=provenance.contract,
        source_sha256=provenance.source_sha256,
        parser_model=provenance.parser_model,
        mineru_version=provenance.mineru_version,
        native_member_sha256=provenance.native_member_sha256,
        marker_kind=marker.marker_kind,
        page_index=marker.page_index,
        structural_path_sha256=marker.structural_path_sha256,
        node_type=marker.node_type,
        local_index=marker.local_index,
    )


def _canonical_binding(
    object_type: Literal[
        "mineru-native-cross-page-facts-custody.v1",
        "mineru-cross-page-marker-provenance-custody.v1",
        "mineru-capture-intake-596-1.v1",
    ],
    preimage: object,
    digest: str,
) -> CanonicalDigestBindingV1:
    return CanonicalDigestBindingV1(
        object_type=object_type,
        canonical_preimage_json=_compact(preimage).decode(),
        sha256=digest,
    )


def _build_source(source: MinerUCaptureIntakeItem5961V1) -> MarkerSourceAuthorityV1:
    if source.role not in SOURCE_ORDER:
        _block("MARKER_AUTHORITY_UNAVAILABLE")
    provenance = source.evidence.cross_page_marker_provenance
    facts = source.evidence.cross_page_facts
    if (
        provenance is None
        or facts is None
        or facts.native_member_sha256 is None
        or source.cross_page_facts_digest_sha256 is None
        or source.marker_provenance_digest_sha256 is None
        or not provenance.markers
    ):
        _block("MARKER_AUTHORITY_UNAVAILABLE")
    paths = _reconstruct_paths(source)
    markers: list[MarkerAuthorityV1] = []
    replay_items: list[MarkerEvidencePreimageV1] = []
    for marker in provenance.markers:
        identity = "\0".join(
            (
                marker.marker_kind,
                str(marker.page_index),
                marker.structural_path_sha256,
                marker.node_type,
                str(marker.local_index),
            )
        )
        structural_path = paths.get(identity)
        if structural_path is None:
            _block("MARKER_PATH_IDENTITY_INVALID")
        path_preimage = StructuralPathPreimageV1(
            contract="mineru-cross-page-marker-path.v1",
            source_sha256=source.source_sha256,
            native_member_sha256=facts.native_member_sha256,
            structural_path=structural_path,
        )
        expected_path_hash = _go_domain_sha256(
            path_preimage.contract,
            source.source_sha256
            + "\0"
            + facts.native_member_sha256
            + "\0"
            + structural_path,
        )
        if expected_path_hash != marker.structural_path_sha256:
            _block("MARKER_PATH_IDENTITY_INVALID")
        marker_preimage = _marker_preimage(provenance, marker)
        if marker.marker_sha256 != _go_domain_sha256(
            "mineru-cross-page-marker-evidence.v1",
            marker_preimage.model_dump(mode="json"),
        ):
            _block("MARKER_IDENTITY_INVALID")
        node_preimage = CanonicalNodePreimageV1(
            contract="mineru-marker-canonical-node.v1",
            source_sha256=source.source_sha256,
            native_member_sha256=facts.native_member_sha256,
            page_index=marker.page_index,
            structural_path_sha256=marker.structural_path_sha256,
            node_type=marker.node_type,
            local_index=marker.local_index,
        )
        replay_items.append(marker_preimage)
        markers.append(
            MarkerAuthorityV1(
                marker_kind=marker.marker_kind,
                page_index=marker.page_index,
                node_type=marker.node_type,
                local_index=marker.local_index,
                structural_path_preimage=path_preimage,
                structural_path_sha256=marker.structural_path_sha256,
                node_identity_preimage=node_preimage,
                node_identity_sha256=canonical_hash(
                    node_preimage.contract, node_preimage.model_dump(mode="json")
                ),
                marker_preimage=marker_preimage,
                marker_sha256=marker.marker_sha256,
            )
        )
    replay_preimage = MarkerReplayPreimageV1(
        contract=provenance.contract,
        source_sha256=provenance.source_sha256,
        parser_model=provenance.parser_model,
        mineru_version=provenance.mineru_version,
        raw_zip_sha256=provenance.raw_zip_sha256,
        native_member_sha256=provenance.native_member_sha256,
        marker_count=provenance.marker_count,
        markers=tuple(replay_items),
        native_hierarchy_replay_sha256=(
            provenance.native_hierarchy_provenance.replay_digest_sha256
            if provenance.native_hierarchy_provenance is not None
            else None
        ),
    )
    replay_wire = {
        **replay_preimage.model_dump(mode="json", exclude_none=True),
        "markers": [
            {
                "marker_kind": marker.marker_kind,
                "page_index": marker.page_index,
                "structural_path": marker.structural_path,
                "structural_path_sha256": marker.structural_path_sha256,
                "node_type": marker.node_type,
                "local_index": marker.local_index,
                "marker_sha256": marker.marker_sha256,
            }
            for marker in provenance.markers
        ],
    }
    if provenance.native_hierarchy_provenance is not None:
        replay_wire["native_hierarchy_replay_sha256"] = (
            provenance.native_hierarchy_provenance.replay_digest_sha256
        )
    if provenance.replay_digest_sha256 != _go_domain_sha256(
        "mineru-cross-page-marker-provenance-replay.v1", replay_wire
    ):
        _block("MARKER_REPLAY_INVALID")
    attempt = source.evidence.attempt
    capture_preimage = CaptureIdentityPreimageV1(
        contract=source.evidence.contract,
        source_sha256=source.source_sha256,
        attempt_number=attempt.attempt_number,
        attempt_role=attempt.attempt_role,
        generation=attempt.generation,
        parser_config_sha256=source.evidence.parser.config_sha256,
        raw_structure_sha256=source.evidence.raw_structure_sha256,
        sanitized_structure_sha256=source.evidence.sanitized_structure_sha256,
        content_snapshot_sha256=source.evidence.content_snapshot_sha256,
        cross_page_projection_sha256=facts.projection_sha256,
        marker_provenance_replay_sha256=provenance.replay_digest_sha256,
    )
    capture_wire = {
        "contract": capture_preimage.contract,
        "source_sha256": capture_preimage.source_sha256,
        "attempt": {
            "attempt_number": capture_preimage.attempt_number,
            "attempt_role": capture_preimage.attempt_role,
            "generation": capture_preimage.generation,
        },
        "parser_config_sha256": capture_preimage.parser_config_sha256,
        "raw_structure_sha256": capture_preimage.raw_structure_sha256,
        "sanitized_structure_sha256": capture_preimage.sanitized_structure_sha256,
        "content_snapshot_sha256": capture_preimage.content_snapshot_sha256,
        "cross_page_projection_sha256": capture_preimage.cross_page_projection_sha256,
        "marker_provenance_replay_sha256": (
            capture_preimage.marker_provenance_replay_sha256
        ),
    }
    if source.capture_identity_sha256 != _sha256(_compact(capture_wire)):
        _block("CAPTURE_IDENTITY_INVALID")
    source_preimage = SourceAuthorityPreimageV1(
        contract="mineru-marker-source-authority.v1",
        role=source.role,
        source_sha256=source.source_sha256,
        capture_identity_sha256=source.capture_identity_sha256,
        parser_config_sha256=source.evidence.parser.config_sha256,
        raw_zip_sha256=provenance.raw_zip_sha256,
        native_member_sha256=provenance.native_member_sha256,
        cross_page_facts_digest_sha256=source.cross_page_facts_digest_sha256,
        marker_provenance_digest_sha256=source.marker_provenance_digest_sha256,
        marker_replay_digest_sha256=provenance.replay_digest_sha256,
        intake_digest_sha256=source.intake_digest_sha256,
        marker_sha256=tuple(marker.marker_sha256 for marker in markers),
        relation_authority="UNBOUND",
    )
    facts_preimage = facts.model_dump(mode="json", exclude_none=True)
    provenance_preimage = marker_provenance_custody_preimage(provenance)
    intake_preimage = {
        "role": source.role,
        "source_sha256": source.source_sha256,
        "capture_identity_sha256": source.capture_identity_sha256,
        "parser_config_sha256": source.evidence.parser.config_sha256,
        "raw_structure_sha256": source.evidence.raw_structure_sha256,
        "sanitized_structure_sha256": source.evidence.sanitized_structure_sha256,
        "content_snapshot_sha256": source.evidence.content_snapshot_sha256,
        "calls": source.evidence.calls.model_dump(mode="json"),
        "latency_milliseconds": source.evidence.latency_milliseconds,
        "status": source.evidence.status,
        "cross_page_facts_digest_sha256": source.cross_page_facts_digest_sha256,
        "marker_provenance_digest_sha256": source.marker_provenance_digest_sha256,
    }
    return MarkerSourceAuthorityV1(
        role=source.role,
        source_sha256=source.source_sha256,
        parser_model=provenance.parser_model,
        mineru_version=provenance.mineru_version,
        parser_config_sha256=source.evidence.parser.config_sha256,
        raw_zip=PrivateContentDigestV1(
            scope="raw_zip_bytes",
            sha256=provenance.raw_zip_sha256,
            preimage_authority="091_VERIFIED_PRIVATE_BYTES",
        ),
        native_member=PrivateContentDigestV1(
            scope="native_member_bytes",
            sha256=provenance.native_member_sha256,
            preimage_authority="091_VERIFIED_PRIVATE_BYTES",
        ),
        capture_identity_preimage=capture_preimage,
        capture_identity_sha256=source.capture_identity_sha256,
        marker_replay_preimage=replay_preimage,
        marker_replay_digest_sha256=provenance.replay_digest_sha256,
        cross_page_facts_custody=_canonical_binding(
            "mineru-native-cross-page-facts-custody.v1",
            facts_preimage,
            source.cross_page_facts_digest_sha256,
        ),
        marker_provenance_custody=_canonical_binding(
            "mineru-cross-page-marker-provenance-custody.v1",
            provenance_preimage,
            source.marker_provenance_digest_sha256,
        ),
        intake_custody=_canonical_binding(
            "mineru-capture-intake-596-1.v1",
            intake_preimage,
            source.intake_digest_sha256,
        ),
        markers=tuple(markers),
        relation_authority="UNBOUND",
        source_authority_preimage=source_preimage,
        source_authority_sha256=canonical_hash(
            source_preimage.contract, source_preimage.model_dump(mode="json")
        ),
    )


def _bundle_preimage(bundle: MinerUCaptureBundle5961V1) -> BundleDigestPreimageV1:
    return BundleDigestPreimageV1(
        contract=bundle.contract,
        roles=tuple(source.role for source in bundle.sources),  # type: ignore[arg-type]
        source_sha256=tuple(source.source_sha256 for source in bundle.sources),  # type: ignore[arg-type]
        capture_identity_sha256=tuple(
            source.capture_identity_sha256 for source in bundle.sources
        ),  # type: ignore[arg-type]
        intake_digest_sha256=tuple(
            source.intake_digest_sha256 for source in bundle.sources
        ),  # type: ignore[arg-type]
    )


def _recompute_bundle_digest(preimage: BundleDigestPreimageV1) -> str:
    return canonical_hash(
        "mineru-capture-bundle-596-1.v1",
        {
            "contract": preimage.contract,
            "sources": [
                {
                    "role": role,
                    "source_sha256": source_sha,
                    "capture_identity_sha256": capture_sha,
                    "intake_digest_sha256": intake_sha,
                }
                for role, source_sha, capture_sha, intake_sha in zip(
                    preimage.roles,
                    preimage.source_sha256,
                    preimage.capture_identity_sha256,
                    preimage.intake_digest_sha256,
                    strict=True,
                )
            ],
        },
    )


def _build_envelope(payloads: tuple[bytes, bytes, bytes]) -> MarkerAuthorityEnvelopeV1:
    parsed = tuple(_canonical_payload(payload) for payload in payloads)
    observed_sources = tuple(value.get("source_sha256") for value in parsed)
    if observed_sources != EXPECTED_SOURCE_SHA256:
        _block("SOURCE_ORDER_INVALID")
    try:
        bundle = intake_mineru_capture_bundle_596_1(payloads)
    except CaptureIntakeError as exc:
        if "MARKER" in exc.reason_code:
            _block("MARKER_AUTHORITY_UNAVAILABLE")
        _block("CUSTODY_AUTHORITY_INVALID")
    bundle_preimage = _bundle_preimage(bundle)
    if _recompute_bundle_digest(bundle_preimage) != bundle.bundle_digest_sha256:
        _block("BUNDLE_REPLAY_INVALID")
    marker_sources = tuple(
        _build_source(source)
        for source in bundle.sources
        if source.evidence.cross_page_marker_provenance is not None
        and source.evidence.cross_page_marker_provenance.markers
    )
    if not marker_sources:
        _block("MARKER_AUTHORITY_UNAVAILABLE")
    envelope_preimage = EnvelopePreimageV1(
        contract=ENVELOPE_CONTRACT,
        product_version=PRODUCT_VERSION,
        source_order=SOURCE_ORDER,
        bundle_digest_sha256=bundle.bundle_digest_sha256,
        marker_source_authority_sha256=tuple(
            source.source_authority_sha256 for source in marker_sources
        ),
        relation_authority="UNBOUND",
    )
    return MarkerAuthorityEnvelopeV1(
        contract=ENVELOPE_CONTRACT,
        product_version=PRODUCT_VERSION,
        source_order=SOURCE_ORDER,
        bundle_preimage=bundle_preimage,
        bundle_digest_sha256=bundle.bundle_digest_sha256,
        marker_sources=marker_sources,
        relation_authority="UNBOUND",
        envelope_preimage=envelope_preimage,
        envelope_sha256=canonical_hash(
            ENVELOPE_CONTRACT, envelope_preimage.model_dump(mode="json")
        ),
    )


def recompute_marker_authority_envelope_sha256(
    envelope: MarkerAuthorityEnvelopeV1,
) -> str:
    """Recompute the public envelope digest from its typed safe preimage."""

    return canonical_hash(
        ENVELOPE_CONTRACT, envelope.envelope_preimage.model_dump(mode="json")
    )


def export_marker_authority_envelope_596_1(
    paths: tuple[Path, Path, Path],
) -> MarkerAuthorityEnvelopeV1:
    """Snapshot exact 091 private files and export only public marker authority."""

    reason_code: str | None = None
    result: MarkerAuthorityEnvelopeV1 | None = None
    try:
        result = _build_envelope(_read_private_snapshot(paths))
    except MarkerAuthorityExportError as caught:
        reason_code = caught.reason_code
        if caught.__traceback__ is not None:
            traceback.clear_frames(caught.__traceback__)
        caught.__traceback__ = None
        caught.__cause__ = None
        caught.__context__ = None
    except (OSError, ValueError, TypeError) as caught:
        reason_code = "MARKER_AUTHORITY_EXPORT_INVALID"
        if caught.__traceback__ is not None:
            traceback.clear_frames(caught.__traceback__)
        caught.__traceback__ = None
        caught.__cause__ = None
        caught.__context__ = None
    paths = None  # type: ignore[assignment]
    if reason_code is not None:
        raise MarkerAuthorityExportError(reason_code) from None
    if result is None:
        raise MarkerAuthorityExportError("MARKER_AUTHORITY_EXPORT_INVALID") from None
    return result


__all__ = [
    "MarkerAuthorityEnvelopeV1",
    "MarkerAuthorityExportError",
    "MarkerAuthorityV1",
    "MarkerSourceAuthorityV1",
    "export_marker_authority_envelope_596_1",
    "recompute_marker_authority_envelope_sha256",
]
