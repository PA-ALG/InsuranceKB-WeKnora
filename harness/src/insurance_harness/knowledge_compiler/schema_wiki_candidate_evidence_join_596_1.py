"""Closed Candidate Evidence companion for the 596-1 Schema Wiki release.

The companion is deliberately separate from ``Schema67CandidateV2``.  Its
factory joins already-admitted ParsedDocument locator custody to one concrete
live WeKnora source receipt and a replayable chunk claim.  A valid self-hash
is not serving authority: the Go read adapter must replay every receipt
against the immutable revision and chunk repositories before returning bytes.
"""

from __future__ import annotations

import hashlib
import threading
import weakref
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Annotated, Final, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from insurance_harness.compiler.evidence_verifier import (
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
)
from insurance_harness.compiler.parsed_documents import (
    ParseBlockV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseTableV1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationBBoxV1,
    CitationTargetV1,
    schema_wiki_sha256,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    AdmittedParseArtifactV1,
)

if TYPE_CHECKING:
    from insurance_harness.goldenset.expert_golden_admission_596_2 import (
        Schema67CandidateV2,
    )

Sha256Hex = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
NonBlank = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
SourceRole = Literal["terms", "brochure", "rate_table"]
LocatorKind = Literal["block", "table", "cell"]

COORDINATE_POLICY_SHA256: Final[str] = (
    "fd86399f644e6703e847686080f42799dca5376cdfb96e04fd49e6fa3b97c9ae"
)
SOURCE_COORDINATE_SPACE: Final[str] = (
    "mineru_content_list_normalized_0_1000_top_left.v1"
)
TARGET_COORDINATE_SPACE: Final[str] = "normalized_0_1e6"
WEKNORA_MANIFEST_ALGORITHM: Final[str] = "weknora.chunk_manifest.v1"

JOIN_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-citation-authority-join-policy.v1",
    {
        "coordinate_policy_sha256": COORDINATE_POLICY_SHA256,
        "source_coordinate_space": SOURCE_COORDINATE_SPACE,
        "target_coordinate_space": TARGET_COORDINATE_SPACE,
        "origin": "top_left",
        "quote_occurrence_count": 1,
        "server_replay_required": True,
        "cell_highlight_precision": "table_scoped_not_cell_exact_stop",
    },
)


class CandidateEvidenceAuthorityError(ValueError):
    """Typed privacy-safe companion construction or replay failure."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def _length_delimited_digest(contract: str, fields: Sequence[str]) -> str:
    """Mechanical Python form of Go revisionAuthorityDigest.

    The equation is intentionally not a second canonical-JSON hash.  It is
    the exact language-neutral receipt equation frozen by knowledge_revision.go.
    """

    pieces = [contract, "\n", str(len(fields)), "\n"]
    for value in fields:
        pieces.extend((str(len(value.encode("utf-8"))), ":", value, "\n"))
    return hashlib.sha256("".join(pieces).encode("utf-8")).hexdigest()


def knowledge_revision_source_id(
    *,
    tenant_id: int,
    knowledge_id: str,
    weknora_parse_attempt: int,
    resource_id: str,
    file_sha256: str,
    size: int,
    mime_type: str,
) -> str:
    return _length_delimited_digest(
        "knowledge-revision-source-id.v1",
        (
            str(tenant_id),
            knowledge_id,
            str(weknora_parse_attempt),
            resource_id,
            file_sha256,
            str(size),
            mime_type,
        ),
    )


class LiveRevisionSourceReceiptV1(_FrozenModel):
    """Exact Python mirror of internal/types.LiveRevisionSourceReceiptV1."""

    contract: Literal["live-revision-source-receipt.v1"]
    revision_source_id: Sha256Hex
    tenant_id: PositiveInt
    space_id: NonBlank
    raw_kb_id: NonBlank
    wiki_kb_id: NonBlank
    knowledge_id: NonBlank
    evidence_parse_attempt_id: NonBlank
    weknora_parse_attempt: PositiveInt
    resource_id: NonBlank
    file_sha256: Sha256Hex
    size: PositiveInt
    mime_type: NonBlank
    page_count: PositiveInt
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    weknora_manifest_algorithm: Literal["weknora.chunk_manifest.v1"]
    weknora_manifest_digest: Sha256Hex
    weknora_chunk_count: PositiveInt
    source_receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_receipt(self) -> LiveRevisionSourceReceiptV1:
        expected_source = knowledge_revision_source_id(
            tenant_id=self.tenant_id,
            knowledge_id=self.knowledge_id,
            weknora_parse_attempt=self.weknora_parse_attempt,
            resource_id=self.resource_id,
            file_sha256=self.file_sha256,
            size=self.size,
            mime_type=self.mime_type,
        )
        if self.revision_source_id != expected_source:
            raise ValueError("revision_source_id mismatch")
        if len(
            {
                self.file_sha256,
                self.parsed_document_sha256,
                self.parse_manifest_sha256,
                self.weknora_manifest_digest,
            }
        ) != 4:
            raise ValueError("revision digest domains must remain distinct")
        if self.source_receipt_sha256 != live_revision_source_receipt_sha256(self):
            raise ValueError("source_receipt_sha256 mismatch")
        return self


def live_revision_source_receipt_sha256(
    receipt: LiveRevisionSourceReceiptV1 | dict[str, object],
) -> str:
    if isinstance(receipt, BaseModel):
        row = receipt.model_dump(mode="python")
    else:
        row = dict(receipt)
    return _length_delimited_digest(
        "live-revision-source-receipt.v1",
        tuple(
            str(row[name])
            for name in (
                "revision_source_id",
                "tenant_id",
                "space_id",
                "raw_kb_id",
                "wiki_kb_id",
                "knowledge_id",
                "evidence_parse_attempt_id",
                "weknora_parse_attempt",
                "resource_id",
                "file_sha256",
                "size",
                "mime_type",
                "page_count",
                "parsed_document_sha256",
                "parse_manifest_sha256",
                "weknora_manifest_algorithm",
                "weknora_manifest_digest",
                "weknora_chunk_count",
            )
        ),
    )


class LiveChunkAuthorityInputV1(_FrozenModel):
    """Private construction input; content is omitted from repr and output."""

    source_role: SourceRole
    locator_ref: NonBlank
    chunk_id: NonBlank
    chunk_index: NonNegativeInt
    content_snapshot: NonBlank = Field(repr=False, exclude=True)
    chunk_content_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_content(self) -> LiveChunkAuthorityInputV1:
        digest = hashlib.sha256(self.content_snapshot.encode("utf-8")).hexdigest()
        if digest != self.chunk_content_sha256:
            raise ValueError("chunk_content_sha256 mismatch")
        return self


class Schema67LiveSourceAuthorityV1(_FrozenModel):
    source_role: SourceRole
    source_sha256: Sha256Hex
    live_revision_source_receipt: LiveRevisionSourceReceiptV1


class Schema67CitationAuthorityJoinReceiptV1(_FrozenModel):
    """Exact Python form of types.Schema67CitationAuthorityJoinReceiptV1."""

    contract: Literal["schema67-citation-authority-join-receipt.v1"]
    candidate_sha256: Sha256Hex
    field_id: NonBlank
    source_role: SourceRole
    evidence_receipt_sha256: Sha256Hex
    source_sha256: Sha256Hex
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    evidence_parse_attempt_id: NonBlank
    locator_kind: LocatorKind
    locator_ref: NonBlank
    native_page_index: NonNegativeInt
    page_number: PositiveInt
    locator_content_sha256: Sha256Hex
    quote_sha256: Sha256Hex
    capture_identity_sha256: Sha256Hex
    raw_structure_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    parser_identity_sha256: Sha256Hex
    coordinate_policy_sha256: Sha256Hex
    source_coordinate_space: Literal[
        "mineru_content_list_normalized_0_1000_top_left.v1"
    ]
    target_coordinate_space: Literal["normalized_0_1e6"]
    origin: Literal["top_left"]
    source_bbox_preimage: tuple[StrictStr, StrictStr, StrictStr, StrictStr]
    normalized_bbox: CitationBBoxV1
    page_width: Literal[1_000_000]
    page_height: Literal[1_000_000]
    rotation_degrees: Literal[0, 90, 180, 270]
    highlight_precision: Literal[
        "locator_exact", "table_scoped_not_cell_exact_stop"
    ]
    tenant_id: PositiveInt
    space_id: NonBlank
    raw_kb_id: NonBlank
    knowledge_id: NonBlank
    weknora_parse_attempt: PositiveInt
    file_sha256: Sha256Hex
    weknora_manifest_algorithm: Literal["weknora.chunk_manifest.v1"]
    weknora_manifest_digest: Sha256Hex
    chunk_id: NonBlank
    chunk_index: NonNegativeInt
    chunk_content_sha256: Sha256Hex
    quote_occurrence_start: NonNegativeInt
    quote_occurrence_end: PositiveInt
    quote_occurrence_count: Literal[1]
    join_policy_sha256: Sha256Hex
    live_revision_source_receipt: LiveRevisionSourceReceiptV1
    live_revision_source_receipt_sha256: Sha256Hex
    receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_receipt(self) -> Schema67CitationAuthorityJoinReceiptV1:
        payload = self.model_dump(mode="python", exclude={"receipt_sha256"})
        if self.receipt_sha256 != schema_wiki_sha256(self.contract, payload):
            raise ValueError("receipt_sha256 mismatch")
        if self.native_page_index + 1 != self.page_number:
            raise ValueError("native page index mismatch")
        if (
            self.coordinate_policy_sha256 != COORDINATE_POLICY_SHA256
            or self.join_policy_sha256 != JOIN_POLICY_SHA256
            or self.normalized_bbox.coordinate_system != TARGET_COORDINATE_SPACE
            or self.normalized_bbox.page_width != self.page_width
            or self.normalized_bbox.page_height != self.page_height
        ):
            raise ValueError("coordinate or join policy mismatch")
        expected_precision = (
            "table_scoped_not_cell_exact_stop"
            if self.locator_kind == "cell"
            else "locator_exact"
        )
        if self.highlight_precision != expected_precision:
            raise ValueError("locator precision mismatch")
        if (
            self.live_revision_source_receipt.source_receipt_sha256
            != self.live_revision_source_receipt_sha256
        ):
            raise ValueError("nested live revision source receipt mismatch")
        return self


class Schema67CandidateEvidenceAuthorityV1(_FrozenModel):
    """Immutable companion accepted by the medical release compiler."""

    contract: Literal["schema67-candidate-evidence-authority.v1"]
    candidate_sha256: Sha256Hex
    coordinate_policy_sha256: Sha256Hex
    join_policy_sha256: Sha256Hex
    source_authorities: tuple[Schema67LiveSourceAuthorityV1, ...]
    join_receipts: tuple[Schema67CitationAuthorityJoinReceiptV1, ...]
    authority_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Schema67CandidateEvidenceAuthorityV1:
        payload = self.model_dump(mode="python", exclude={"authority_sha256"})
        if self.authority_sha256 != schema_wiki_sha256(self.contract, payload):
            raise ValueError("authority_sha256 mismatch")
        if (
            self.coordinate_policy_sha256 != COORDINATE_POLICY_SHA256
            or self.join_policy_sha256 != JOIN_POLICY_SHA256
        ):
            raise ValueError("authority policy mismatch")
        return self


_FACTORY_AUTHORITY_LOCK = threading.Lock()
_FACTORY_AUTHORITY_REGISTRY: dict[
    int,
    tuple[
        weakref.ReferenceType[Schema67CandidateEvidenceAuthorityV1],
        str,
    ],
] = {}


def _remove_factory_authority(
    identity: int,
    authority_ref: weakref.ReferenceType[Schema67CandidateEvidenceAuthorityV1],
) -> None:
    with _FACTORY_AUTHORITY_LOCK:
        registered = _FACTORY_AUTHORITY_REGISTRY.get(identity)
        if registered is not None and registered[0] is authority_ref:
            _FACTORY_AUTHORITY_REGISTRY.pop(identity, None)


def _register_factory_authority(
    authority: Schema67CandidateEvidenceAuthorityV1,
) -> None:
    identity = id(authority)

    def remove_when_collected(
        authority_ref: weakref.ReferenceType[Schema67CandidateEvidenceAuthorityV1],
    ) -> None:
        _remove_factory_authority(identity, authority_ref)

    authority_ref = weakref.ref(authority, remove_when_collected)
    with _FACTORY_AUTHORITY_LOCK:
        registered = _FACTORY_AUTHORITY_REGISTRY.get(identity)
        if registered is not None and registered[0]() is not None:
            raise CandidateEvidenceAuthorityError(
                "CANDIDATE_EVIDENCE_AUTHORITY_INVALID"
            )
        _FACTORY_AUTHORITY_REGISTRY[identity] = (
            authority_ref,
            authority.authority_sha256,
        )


def _unregister_factory_authority(
    authority: Schema67CandidateEvidenceAuthorityV1,
) -> None:
    identity = id(authority)
    with _FACTORY_AUTHORITY_LOCK:
        registered = _FACTORY_AUTHORITY_REGISTRY.get(identity)
        if registered is not None and registered[0]() is authority:
            _FACTORY_AUTHORITY_REGISTRY.pop(identity, None)


def _require_factory_authority(
    authority: Schema67CandidateEvidenceAuthorityV1,
) -> None:
    with _FACTORY_AUTHORITY_LOCK:
        registered = _FACTORY_AUTHORITY_REGISTRY.get(id(authority))
        if (
            registered is None
            or registered[0]() is not authority
            or registered[1] != authority.authority_sha256
        ):
            raise CandidateEvidenceAuthorityError(
                "CANDIDATE_EVIDENCE_AUTHORITY_INVALID"
            )


def _decimal_preimage(value: object) -> tuple[Decimal, str]:
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CandidateEvidenceAuthorityError("COORDINATE_AUTHORITY_INVALID") from None
    if not decimal.is_finite() or decimal < 0 or decimal > 1000:
        raise CandidateEvidenceAuthorityError("COORDINATE_AUTHORITY_INVALID")
    if decimal == decimal.to_integral():
        return decimal, str(int(decimal))
    return decimal, format(decimal.normalize(), "f")


def normalize_mineru_bbox_596_1(
    *,
    bbox: Sequence[object],
    page_number: int,
    page_count: int,
) -> tuple[tuple[str, str, str, str], CitationBBoxV1]:
    """Normalize exact MinerU 0..1000 top-left coordinates to 0..1e6."""

    if (
        type(page_number) is not int
        or type(page_count) is not int
        or page_number <= 0
        or page_number > page_count
        or len(bbox) != 4
    ):
        raise CandidateEvidenceAuthorityError("PAGE_OUT_OF_RANGE")
    converted = tuple(_decimal_preimage(value) for value in bbox)
    decimals = tuple(item[0] for item in converted)
    preimage = cast(tuple[str, str, str, str], tuple(item[1] for item in converted))
    scaled: list[int] = []
    for decimal in decimals:
        value = decimal * 1000
        if value != value.to_integral():
            raise CandidateEvidenceAuthorityError("COORDINATE_AUTHORITY_INVALID")
        scaled.append(int(value))
    try:
        normalized = CitationBBoxV1(
            coordinate_system="normalized_0_1e6",
            page_width=1_000_000,
            page_height=1_000_000,
            x0=scaled[0],
            y0=scaled[1],
            x1=scaled[2],
            y1=scaled[3],
        )
    except (TypeError, ValueError, ValidationError):
        raise CandidateEvidenceAuthorityError("COORDINATE_AUTHORITY_INVALID") from None
    return preimage, normalized


def _parser_identity_sha256(document: ParsedDocumentV1) -> str:
    return schema_wiki_sha256(
        "schema67-parser-identity.v1",
        document.parser.model_dump(mode="python"),
    )


def _artifact_locator(
    artifact: AdmittedParseArtifactV1,
    evidence: FreeformEvidenceV1,
) -> tuple[LocatorKind, tuple[object, object, object, object]]:
    kind = evidence.locator.subject_type
    rows: tuple[ParseBlockV1 | ParseTableV1 | ParseCellV1, ...]
    if kind == "block":
        rows = tuple(
            row
            for row in artifact.document.blocks
            if row.block_id == evidence.locator.subject_ref
        )
    elif kind == "table":
        rows = tuple(
            row
            for row in artifact.document.tables
            if row.table_id == evidence.locator.subject_ref
        )
    elif kind == "cell":
        rows = tuple(
            row
            for row in artifact.document.cells
            if row.cell_id == evidence.locator.subject_ref
        )
    else:
        raise CandidateEvidenceAuthorityError("LOCATOR_AUTHORITY_INVALID")
    if len(rows) != 1:
        raise CandidateEvidenceAuthorityError("LOCATOR_AUTHORITY_INVALID")
    row = rows[0]
    if (
        row.locator.page_number != evidence.page_number
        or row.content_hash != evidence.locator.content_snapshot_sha256
    ):
        raise CandidateEvidenceAuthorityError("LOCATOR_AUTHORITY_INVALID")
    return kind, cast(tuple[object, object, object, object], row.locator.bbox)


def _validate_artifact(artifact: object) -> AdmittedParseArtifactV1:
    if type(artifact) is not AdmittedParseArtifactV1:
        raise CandidateEvidenceAuthorityError("PARSED_DOCUMENT_AUTHORITY_INVALID")
    exact = artifact
    if (
        exact.decision.decision != "ADMIT"
        or exact.decision.admitted_attempt_id != exact.document.attempt.attempt_id
        or exact.artifact_sha256 != exact.document.document_hash
        or exact.manifest_sha256 != exact.manifest.manifest_hash
        or exact.manifest.document_hash != exact.document.document_hash
        or exact.decision.manifest_hash != exact.manifest.manifest_hash
        or exact.decision_sha256 != exact.decision.decision_hash
        or exact.source_sha256 != exact.document.subject.source_sha256
        or not all(
            isinstance(value, str) and len(value) == 64
            for value in (
                exact.capture_identity_sha256,
                exact.raw_structure_sha256,
                exact.sanitized_structure_sha256,
            )
        )
    ):
        raise CandidateEvidenceAuthorityError("PARSED_DOCUMENT_AUTHORITY_INVALID")
    return exact


def _fresh_candidate(candidate: object) -> Schema67CandidateV2:
    from insurance_harness.goldenset.expert_golden_admission_596_2 import (
        Schema67CandidateV2,
        validate_schema67_candidate_v2,
    )

    if type(candidate) is not Schema67CandidateV2:
        raise CandidateEvidenceAuthorityError("CANDIDATE_CUSTODY_INVALID")
    try:
        return validate_schema67_candidate_v2(candidate)
    except Exception:
        raise CandidateEvidenceAuthorityError("CANDIDATE_CUSTODY_INVALID") from None


def build_schema67_candidate_evidence_authority_596_1(
    *,
    candidate: object,
    admitted_parse_artifacts: tuple[AdmittedParseArtifactV1, ...],
    live_source_receipts: tuple[LiveRevisionSourceReceiptV1, ...],
    chunk_authorities: tuple[LiveChunkAuthorityInputV1, ...],
) -> Schema67CandidateEvidenceAuthorityV1:
    """Build one factory-sealed companion; no provider or live read occurs."""

    exact_candidate = _fresh_candidate(candidate)
    source_rows = tuple(exact_candidate.source_roles)
    if (
        type(admitted_parse_artifacts) is not tuple
        or type(live_source_receipts) is not tuple
        or type(chunk_authorities) is not tuple
        or tuple(row["role"] for row in source_rows)
        != ("terms", "brochure", "rate_table")
        or len(live_source_receipts) != len(source_rows)
    ):
        raise CandidateEvidenceAuthorityError("SOURCE_AUTHORITY_INVALID")

    sources: list[Schema67LiveSourceAuthorityV1] = []
    receipt_by_source: dict[str, tuple[SourceRole, LiveRevisionSourceReceiptV1]] = {}
    for row, raw_receipt in zip(source_rows, live_source_receipts, strict=True):
        try:
            receipt = LiveRevisionSourceReceiptV1.model_validate(
                raw_receipt.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError):
            raise CandidateEvidenceAuthorityError("LIVE_SOURCE_RECEIPT_INVALID") from None
        role = cast(SourceRole, row["role"])
        source_sha256 = row["source_sha256"]
        if receipt.file_sha256 != source_sha256 or source_sha256 in receipt_by_source:
            raise CandidateEvidenceAuthorityError("SOURCE_AUTHORITY_INVALID")
        sources.append(
            Schema67LiveSourceAuthorityV1(
                source_role=role,
                source_sha256=source_sha256,
                live_revision_source_receipt=receipt,
            )
        )
        receipt_by_source[source_sha256] = (role, receipt)

    artifacts = tuple(_validate_artifact(item) for item in admitted_parse_artifacts)
    artifact_by_source: dict[str, AdmittedParseArtifactV1] = {}
    for artifact in artifacts:
        if artifact.source_sha256 in artifact_by_source:
            raise CandidateEvidenceAuthorityError("PARSED_DOCUMENT_AUTHORITY_INVALID")
        source = receipt_by_source.get(artifact.source_sha256)
        if source is None or source[0] != artifact.role:
            raise CandidateEvidenceAuthorityError("PARSED_DOCUMENT_AUTHORITY_INVALID")
        artifact_by_source[artifact.source_sha256] = artifact

    chunks: dict[tuple[str, str], LiveChunkAuthorityInputV1] = {}
    for raw_chunk in chunk_authorities:
        if type(raw_chunk) is not LiveChunkAuthorityInputV1:
            raise CandidateEvidenceAuthorityError("CHUNK_AUTHORITY_INVALID") from None
        chunk = raw_chunk
        key = (chunk.source_role, chunk.locator_ref)
        if key in chunks:
            raise CandidateEvidenceAuthorityError("CHUNK_AUTHORITY_INVALID")
        chunks[key] = chunk

    joins: list[Schema67CitationAuthorityJoinReceiptV1] = []
    used_chunks: set[tuple[str, str]] = set()
    fields = tuple(exact_candidate.fields)
    evidence_receipts = tuple(exact_candidate.evidence_receipts)
    for output, evidence_receipt in zip(fields, evidence_receipts, strict=True):
        if type(evidence_receipt) is not FreeformEvidenceBindingReceiptV1:
            raise CandidateEvidenceAuthorityError("EVIDENCE_RECEIPT_INVALID")
        for evidence in output.evidence:
            source = receipt_by_source.get(evidence.source_sha256)
            bound_artifact = artifact_by_source.get(evidence.source_sha256)
            if source is None or bound_artifact is None:
                raise CandidateEvidenceAuthorityError("PARSED_DOCUMENT_AUTHORITY_INVALID")
            role, live = source
            if (
                evidence.parsed_document_hash != bound_artifact.document.document_hash
                or evidence.parse_manifest_hash != bound_artifact.manifest.manifest_hash
                or evidence.parse_attempt_id != bound_artifact.document.attempt.attempt_id
                or live.parsed_document_sha256 != evidence.parsed_document_hash
                or live.parse_manifest_sha256 != evidence.parse_manifest_hash
                or live.evidence_parse_attempt_id != evidence.parse_attempt_id
                or live.page_count < len(bound_artifact.document.pages)
                or evidence.page_number > live.page_count
            ):
                raise CandidateEvidenceAuthorityError("LIVE_SOURCE_RECEIPT_INVALID")
            locator_kind, bbox = _artifact_locator(bound_artifact, evidence)
            bbox_preimage, normalized_bbox = normalize_mineru_bbox_596_1(
                bbox=bbox,
                page_number=evidence.page_number,
                page_count=live.page_count,
            )
            chunk_key = (role, evidence.locator.subject_ref)
            bound_chunk = chunks.get(chunk_key)
            if bound_chunk is None:
                raise CandidateEvidenceAuthorityError("CHUNK_AUTHORITY_INVALID")
            used_chunks.add(chunk_key)
            occurrence_count = bound_chunk.content_snapshot.count(evidence.quote_snapshot)
            start = bound_chunk.content_snapshot.find(evidence.quote_snapshot)
            if occurrence_count != 1 or start < 0:
                raise CandidateEvidenceAuthorityError("CHUNK_AUTHORITY_INVALID")
            receipt_payload = {
                "contract": "schema67-citation-authority-join-receipt.v1",
                "candidate_sha256": exact_candidate.candidate_sha256,
                "field_id": output.field_id,
                "source_role": role,
                "evidence_receipt_sha256": evidence_receipt.receipt_hash,
                "source_sha256": evidence.source_sha256,
                "parsed_document_sha256": evidence.parsed_document_hash,
                "parse_manifest_sha256": evidence.parse_manifest_hash,
                "evidence_parse_attempt_id": evidence.parse_attempt_id,
                "locator_kind": locator_kind,
                "locator_ref": evidence.locator.subject_ref,
                "native_page_index": evidence.page_number - 1,
                "page_number": evidence.page_number,
                "locator_content_sha256": evidence.locator.content_snapshot_sha256,
                "quote_sha256": schema_wiki_sha256(
                    "schema-wiki-text.v1", {"text": evidence.quote_snapshot}
                ),
                "capture_identity_sha256": bound_artifact.capture_identity_sha256,
                "raw_structure_sha256": bound_artifact.raw_structure_sha256,
                "sanitized_structure_sha256": bound_artifact.sanitized_structure_sha256,
                "parser_identity_sha256": _parser_identity_sha256(bound_artifact.document),
                "coordinate_policy_sha256": COORDINATE_POLICY_SHA256,
                "source_coordinate_space": SOURCE_COORDINATE_SPACE,
                "target_coordinate_space": TARGET_COORDINATE_SPACE,
                "origin": "top_left",
                "source_bbox_preimage": bbox_preimage,
                "normalized_bbox": normalized_bbox,
                "page_width": 1_000_000,
                "page_height": 1_000_000,
                "rotation_degrees": 0,
                "highlight_precision": (
                    "table_scoped_not_cell_exact_stop"
                    if locator_kind == "cell"
                    else "locator_exact"
                ),
                "tenant_id": live.tenant_id,
                "space_id": live.space_id,
                "raw_kb_id": live.raw_kb_id,
                "knowledge_id": live.knowledge_id,
                "weknora_parse_attempt": live.weknora_parse_attempt,
                "file_sha256": live.file_sha256,
                "weknora_manifest_algorithm": live.weknora_manifest_algorithm,
                "weknora_manifest_digest": live.weknora_manifest_digest,
                "chunk_id": bound_chunk.chunk_id,
                "chunk_index": bound_chunk.chunk_index,
                "chunk_content_sha256": bound_chunk.chunk_content_sha256,
                "quote_occurrence_start": start,
                "quote_occurrence_end": start + len(evidence.quote_snapshot),
                "quote_occurrence_count": 1,
                "join_policy_sha256": JOIN_POLICY_SHA256,
                "live_revision_source_receipt": live,
                "live_revision_source_receipt_sha256": live.source_receipt_sha256,
            }
            joins.append(
                Schema67CitationAuthorityJoinReceiptV1.model_validate(
                    {
                        **receipt_payload,
                        "receipt_sha256": schema_wiki_sha256(
                            "schema67-citation-authority-join-receipt.v1",
                            receipt_payload,
                        ),
                    }
                )
            )
    if used_chunks != set(chunks):
        raise CandidateEvidenceAuthorityError("CHUNK_AUTHORITY_INVALID")
    authority_payload = {
        "contract": "schema67-candidate-evidence-authority.v1",
        "candidate_sha256": exact_candidate.candidate_sha256,
        "coordinate_policy_sha256": COORDINATE_POLICY_SHA256,
        "join_policy_sha256": JOIN_POLICY_SHA256,
        "source_authorities": tuple(sources),
        "join_receipts": tuple(joins),
    }
    authority = Schema67CandidateEvidenceAuthorityV1.model_validate(
        {
            **authority_payload,
            "authority_sha256": schema_wiki_sha256(
                "schema67-candidate-evidence-authority.v1", authority_payload
            ),
        }
    )
    _register_factory_authority(authority)
    try:
        return validate_schema67_candidate_evidence_authority_596_1(
            candidate=exact_candidate,
            authority=authority,
        )
    except Exception:
        _unregister_factory_authority(authority)
        raise


def validate_schema67_candidate_evidence_authority_596_1(
    *,
    candidate: object,
    authority: object,
) -> Schema67CandidateEvidenceAuthorityV1:
    exact_candidate = _fresh_candidate(candidate)
    if type(authority) is not Schema67CandidateEvidenceAuthorityV1:
        raise CandidateEvidenceAuthorityError("CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    exact = authority
    _require_factory_authority(exact)
    try:
        Schema67CandidateEvidenceAuthorityV1.model_validate(
            exact.model_dump(mode="python")
        )
    except (TypeError, ValueError, ValidationError):
        raise CandidateEvidenceAuthorityError("CANDIDATE_EVIDENCE_AUTHORITY_INVALID") from None
    if exact.candidate_sha256 != exact_candidate.candidate_sha256:
        raise CandidateEvidenceAuthorityError("CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    source_rows = tuple(exact_candidate.source_roles)
    if tuple(
        (item.source_role, item.source_sha256)
        for item in exact.source_authorities
    ) != tuple((row["role"], row["source_sha256"]) for row in source_rows):
        raise CandidateEvidenceAuthorityError("CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    expected: list[tuple[object, ...]] = []
    for output, receipt in zip(
        exact_candidate.fields,
        exact_candidate.evidence_receipts,
        strict=True,
    ):
        for evidence in output.evidence:
            expected.append(
                (
                    output.field_id,
                    receipt.receipt_hash,
                    evidence.source_sha256,
                    evidence.parsed_document_hash,
                    evidence.parse_manifest_hash,
                    evidence.parse_attempt_id,
                    evidence.locator.subject_ref,
                    evidence.page_number,
                    evidence.locator.content_snapshot_sha256,
                    schema_wiki_sha256(
                        "schema-wiki-text.v1", {"text": evidence.quote_snapshot}
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
        raise CandidateEvidenceAuthorityError("CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    return exact


def citation_targets_for_field_596_1(
    *,
    candidate: object,
    authority: Schema67CandidateEvidenceAuthorityV1,
    output: object,
    evidence_receipt: FreeformEvidenceBindingReceiptV1,
    entity_version_id: str,
) -> tuple[CitationTargetV1, ...]:
    """Derive exact CitationTargetV1 rows from a validated companion."""

    exact = validate_schema67_candidate_evidence_authority_596_1(
        candidate=candidate,
        authority=authority,
    )
    return _citation_targets_from_validated_authority_596_1(
        authority=exact,
        output=output,
        evidence_receipt=evidence_receipt,
        entity_version_id=entity_version_id,
    )


def _citation_targets_from_validated_authority_596_1(
    *,
    authority: Schema67CandidateEvidenceAuthorityV1,
    output: object,
    evidence_receipt: FreeformEvidenceBindingReceiptV1,
    entity_version_id: str,
) -> tuple[CitationTargetV1, ...]:
    """Internal fast path used only after the outer compiler replayed custody."""

    field_id = getattr(output, "field_id", None)
    evidence = tuple(getattr(output, "evidence", ()))
    joins = tuple(item for item in authority.join_receipts if item.field_id == field_id)
    if len(joins) != len(evidence):
        raise CandidateEvidenceAuthorityError("CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
    citations: list[CitationTargetV1] = []
    for item, evidence_row in zip(joins, evidence, strict=True):
        if item.evidence_receipt_sha256 != evidence_receipt.receipt_hash:
            raise CandidateEvidenceAuthorityError("CANDIDATE_EVIDENCE_AUTHORITY_INVALID")
        payload = {
            "contract": "citation-target.v1",
            "citation_id": f"citation-{item.receipt_sha256[:24]}",
            "source_role": item.source_role,
            "space_id": item.space_id,
            "entity_version_id": entity_version_id,
            "knowledge_id": item.knowledge_id,
            "chunk_id": item.chunk_id,
            "source_revision_id": evidence_row.source_revision_id,
            "parse_attempt_id": item.evidence_parse_attempt_id,
            "parsed_document_sha256": item.parsed_document_sha256,
            "parse_manifest_sha256": item.parse_manifest_sha256,
            "page_number": item.page_number,
            "locator_ref": item.locator_ref,
            "bbox": item.normalized_bbox,
            "quote_snapshot": evidence_row.quote_snapshot,
            "quote_sha256": item.quote_sha256,
            "content_snapshot_sha256": item.locator_content_sha256,
            "logical_member_ref": f"field:{field_id}",
        }
        citations.append(
            CitationTargetV1.model_validate(
                {
                    **payload,
                    "citation_sha256": schema_wiki_sha256(
                        "citation-target.v1", payload
                    ),
                }
            )
        )
    return tuple(citations)


__all__ = [
    "COORDINATE_POLICY_SHA256",
    "JOIN_POLICY_SHA256",
    "CandidateEvidenceAuthorityError",
    "LiveChunkAuthorityInputV1",
    "LiveRevisionSourceReceiptV1",
    "Schema67CandidateEvidenceAuthorityV1",
    "Schema67CitationAuthorityJoinReceiptV1",
    "Schema67LiveSourceAuthorityV1",
    "build_schema67_candidate_evidence_authority_596_1",
    "citation_targets_for_field_596_1",
    "knowledge_revision_source_id",
    "live_revision_source_receipt_sha256",
    "normalize_mineru_bbox_596_1",
    "validate_schema67_candidate_evidence_authority_596_1",
]
