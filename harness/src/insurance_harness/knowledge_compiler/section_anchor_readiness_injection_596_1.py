"""Mechanical 106 section-anchor to 103/104 readiness wiring for 596-1."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.parsed_documents import ParsedDocumentV1, ParseManifestV1
from insurance_harness.knowledge_compiler.bounded_real_capture_readiness_596_1 import (
    BoundProof,
)
from insurance_harness.knowledge_compiler.marker_authority_envelope_596_1 import (
    MarkerAuthorityEnvelopeV1,
)
from insurance_harness.knowledge_compiler.marker_authority_readiness_wiring_596_1 import (
    FutureReadinessProtocol,
    MarkerAuthorityReadinessResultV1,
    TermsSectionBindingEvidenceV1,
    evaluate_test_only_future_marker_authority_readiness_596_1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    RelationReceiptEntry5961V1,
)
from insurance_harness.knowledge_compiler.terms_section_endpoint_pair_bridge_596_1 import (
    TermsSectionEndpointBridgeError,
    TermsSectionMarkerAuthorityEvidenceV1,
    TermsSectionMarkerAuthorityRequestV1,
    derive_terms_section_receipt_entry_596_1,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
_TEST_EVIDENCE_CLASS = "TEST_ONLY_COMPLETE_FIXTURE"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class ReadingOrderFactV1(_FrozenModel):
    endpoint_id: StrictStr = Field(min_length=1)
    page_number: PositiveInt
    order_index: NonNegativeInt


class SectionAnchorEndpointV1(_FrozenModel):
    endpoint_id: StrictStr = Field(min_length=1)
    page_number: PositiveInt
    block_index: NonNegativeInt
    order_index: NonNegativeInt
    endpoint_path_sha256: Sha256Hex
    section_ancestry_node_hashes: tuple[Sha256Hex, ...]
    outline_anchor_node_hashes: tuple[Sha256Hex, ...]

    @model_validator(mode="after")
    def _nonempty_unique_anchors(self) -> Self:
        if (
            not self.section_ancestry_node_hashes
            or not self.outline_anchor_node_hashes
            or len(set(self.section_ancestry_node_hashes))
            != len(self.section_ancestry_node_hashes)
            or len(set(self.outline_anchor_node_hashes))
            != len(self.outline_anchor_node_hashes)
        ):
            raise ValueError("section anchor identity invalid")
        return self


class SectionAnchorIntervalV1(_FrozenModel):
    source_order_index: NonNegativeInt
    target_order_index: NonNegativeInt
    source_page_number: PositiveInt
    target_page_number: PositiveInt
    target_starts_new_heading: StrictBool

    @model_validator(mode="after")
    def _ordered_adjacent_interval(self) -> Self:
        if (
            self.target_order_index <= self.source_order_index
            or self.target_page_number != self.source_page_number + 1
            or self.target_starts_new_heading
        ):
            raise ValueError("section anchor interval invalid")
        return self


class SectionAnchorEvidenceViewV1(_FrozenModel):
    """107's narrow, extraction-neutral view of a future frozen 106 DTO."""

    contract: Literal["section-anchor-evidence-view-596-1.v1"]
    status: Literal["SECTION_ANCHOR_EVIDENCE_VERIFIED"]
    evidence_class: Literal["TEST_ONLY_COMPLETE_FIXTURE", "ACTUAL_106_FROZEN"]
    source_sha256: Sha256Hex
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    parser_identity_sha256: Sha256Hex
    parser_config_sha256: Sha256Hex
    document_hash: Sha256Hex
    manifest_hash: Sha256Hex
    marker_evidence_sha256: Sha256Hex
    reading_order: tuple[ReadingOrderFactV1, ReadingOrderFactV1]
    reading_order_sha256: Sha256Hex
    source_anchor: SectionAnchorEndpointV1
    target_anchor: SectionAnchorEndpointV1
    anchor_interval: SectionAnchorIntervalV1
    anchor_interval_sha256: Sha256Hex
    authority_version_sha256: Sha256Hex
    evidence_preimage_sha256: Sha256Hex
    evidence_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_custody(self) -> Self:
        source_order, target_order = self.reading_order
        if (
            source_order.endpoint_id != self.source_anchor.endpoint_id
            or source_order.page_number != self.source_anchor.page_number
            or source_order.order_index != self.source_anchor.order_index
            or target_order.endpoint_id != self.target_anchor.endpoint_id
            or target_order.page_number != self.target_anchor.page_number
            or target_order.order_index != self.target_anchor.order_index
            or self.source_anchor.endpoint_id == self.target_anchor.endpoint_id
            or self.source_anchor.section_ancestry_node_hashes
            != self.target_anchor.section_ancestry_node_hashes
            or self.source_anchor.outline_anchor_node_hashes
            != self.target_anchor.outline_anchor_node_hashes
            or self.anchor_interval.source_order_index != self.source_anchor.order_index
            or self.anchor_interval.target_order_index != self.target_anchor.order_index
            or self.anchor_interval.source_page_number != self.source_anchor.page_number
            or self.anchor_interval.target_page_number != self.target_anchor.page_number
        ):
            raise ValueError("section anchor evidence mapping invalid")
        if self.reading_order_sha256 != canonical_hash(
            "section-anchor-reading-order.v1",
            tuple(item.model_dump(mode="python") for item in self.reading_order),
        ) or self.anchor_interval_sha256 != canonical_hash(
            "section-anchor-interval.v1", self.anchor_interval.model_dump(mode="python")
        ):
            raise ValueError("section anchor sub-preimage invalid")
        preimage = self.model_dump(
            mode="python",
            exclude={"evidence_preimage_sha256", "evidence_digest_sha256"},
        )
        if self.evidence_preimage_sha256 != canonical_hash(
            "section-anchor-evidence-preimage-596-1.v1", preimage
        ):
            raise ValueError("section anchor evidence preimage invalid")
        digest_input = self.model_dump(mode="python", exclude={"evidence_digest_sha256"})
        if self.evidence_digest_sha256 != canonical_hash(
            "section-anchor-evidence-view-596-1.v1", digest_input
        ):
            raise ValueError("section anchor evidence digest invalid")
        return self


@runtime_checkable
class SectionAnchorEvidenceProtocol(Protocol):
    def load_section_anchor_evidence(self) -> object | None: ...


@dataclass(frozen=True)
class SectionAnchorReadinessResultV1:
    status: str
    reason_code: str
    evidence_class: str
    capture_authorized: bool
    downstream_calls: int
    anchor_evidence_sha256: str | None = None
    terms_receipt_sha256: str | None = None
    readiness: MarkerAuthorityReadinessResultV1 | None = None
    relation_count: int = 0
    terms_receipt_entries: tuple[RelationReceiptEntry5961V1, ...] = ()


def _result(
    reason_code: str,
    *,
    evidence_class: str = "BLOCKED",
    downstream_calls: int = 0,
    anchor_sha256: str | None = None,
    receipt_sha256: str | None = None,
    readiness: MarkerAuthorityReadinessResultV1 | None = None,
    relation_count: int = 0,
    terms_receipt_entries: tuple[RelationReceiptEntry5961V1, ...] = (),
) -> SectionAnchorReadinessResultV1:
    return SectionAnchorReadinessResultV1(
        status=reason_code,
        reason_code=reason_code,
        evidence_class=evidence_class,
        capture_authorized=False,
        downstream_calls=downstream_calls,
        anchor_evidence_sha256=anchor_sha256,
        terms_receipt_sha256=receipt_sha256,
        readiness=readiness,
        relation_count=relation_count,
        terms_receipt_entries=terms_receipt_entries,
    )


def _proof(value: object) -> BoundProof:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return BoundProof(preimage=payload, sha256=hashlib.sha256(payload).hexdigest())


def _module_blob_sha256(value: Callable[..., object]) -> str:
    source = inspect.getsourcefile(value)
    if source is None:
        raise ValueError("module source unavailable")
    return hashlib.sha256(Path(source).read_bytes()).hexdigest()


def _schema_sha256(model: type[BaseModel]) -> str:
    return hashlib.sha256(
        json.dumps(
            model.model_json_schema(), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class _SectionAnchorAuthorityReplay:
    def __init__(
        self,
        evidence: SectionAnchorEvidenceViewV1,
        document: ParsedDocumentV1,
        manifest: ParseManifestV1,
    ) -> None:
        self._evidence = evidence
        self._document = document
        self._manifest = manifest

    def replay_terms_section_authority(
        self, request: TermsSectionMarkerAuthorityRequestV1
    ) -> TermsSectionMarkerAuthorityEvidenceV1 | None:
        evidence = self._evidence
        source = evidence.source_anchor
        target = evidence.target_anchor
        if not (
            evidence.document_hash == self._document.document_hash
            and evidence.manifest_hash == self._manifest.manifest_hash
            and request.source_sha256 == evidence.source_sha256
            and request.raw_zip_sha256 == evidence.raw_zip_sha256
            and request.native_member_sha256 == evidence.native_member_sha256
            and request.parser_identity_sha256 == evidence.parser_identity_sha256
            and request.parser_config_sha256 == evidence.parser_config_sha256
            and request.marker_evidence_sha256 == evidence.marker_evidence_sha256
            and request.source_endpoint.endpoint_id == source.endpoint_id
            and request.source_endpoint.page_number == source.page_number
            and request.source_endpoint.order_index == source.order_index
            and request.source_endpoint.locator_digest_sha256
            == source.endpoint_path_sha256
            and request.target_endpoint.endpoint_id == target.endpoint_id
            and request.target_endpoint.page_number == target.page_number
            and request.target_endpoint.order_index == target.order_index
            and request.target_endpoint.locator_digest_sha256
            == target.endpoint_path_sha256
        ):
            return None
        ancestry = source.section_ancestry_node_hashes
        outline = source.outline_anchor_node_hashes
        values: dict[str, object] = {
            "contract": "terms-section-marker-authority-evidence.v1",
            "authority_contract": "marker-authority-envelope.v1",
            "authority_version_sha256": evidence.authority_version_sha256,
            "request_digest_sha256": request.request_digest_sha256,
            "marker_kind": "cross_page",
            "relation_kind": "section",
            "source_endpoint_id": source.endpoint_id,
            "source_page_number": source.page_number,
            "source_endpoint_path_sha256": source.endpoint_path_sha256,
            "target_endpoint_id": target.endpoint_id,
            "target_page_number": target.page_number,
            "target_endpoint_path_sha256": target.endpoint_path_sha256,
            "source_section_ancestry_node_hashes": ancestry,
            "target_section_ancestry_node_hashes": ancestry,
            "section_ancestry_sha256": canonical_hash(
                "terms-section-ancestry.v1", ancestry
            ),
            "source_outline_anchor_node_hashes": outline,
            "target_outline_anchor_node_hashes": outline,
            "outline_anchor_sha256": canonical_hash(
                "terms-section-outline-anchor.v1", outline
            ),
            "target_starts_new_heading": False,
        }
        authority_preimage = {
            key: values[key]
            for key in (
                "authority_contract",
                "authority_version_sha256",
                "request_digest_sha256",
                "marker_kind",
                "relation_kind",
                "source_endpoint_id",
                "source_page_number",
                "source_endpoint_path_sha256",
                "target_endpoint_id",
                "target_page_number",
                "target_endpoint_path_sha256",
                "source_section_ancestry_node_hashes",
                "target_section_ancestry_node_hashes",
                "source_outline_anchor_node_hashes",
                "target_outline_anchor_node_hashes",
                "target_starts_new_heading",
            )
        }
        values["authority_preimage_sha256"] = canonical_hash(
            "terms-section-marker-authority-preimage.v1", authority_preimage
        )
        values["evidence_digest_sha256"] = canonical_hash(
            "terms-section-marker-authority-evidence.v1", values
        )
        return TermsSectionMarkerAuthorityEvidenceV1.model_validate(values)


class _TermsBinding:
    def __init__(
        self,
        bundle: MinerUCaptureBundle5961V1,
        document: ParsedDocumentV1,
        manifest: ParseManifestV1,
        evidence: SectionAnchorEvidenceViewV1,
    ) -> None:
        self._bundle = bundle
        self._document = document
        self._manifest = manifest
        self._evidence = evidence
        self.receipt_sha256: str | None = None

    def bind_terms_section(
        self, envelope: MarkerAuthorityEnvelopeV1
    ) -> TermsSectionBindingEvidenceV1:
        authority = _SectionAnchorAuthorityReplay(
            self._evidence, self._document, self._manifest
        )
        entry = derive_terms_section_receipt_entry_596_1(
            self._bundle, self._document, self._manifest, authority
        )
        canonical = _proof(
            {
                "contract": "terms-section-binding-596-1.v1",
                "marker_authority_envelope_sha256": envelope.envelope_sha256,
                "section_anchor_evidence_sha256": self._evidence.evidence_digest_sha256,
                "relation_receipt_entry": entry.model_dump(mode="json"),
            }
        )
        receipt = _proof(
            {
                "contract": "terms-section-binding-receipt-596-1.v1",
                "canonical_preimage_sha256": canonical.sha256,
                "binding_replay_sha256": entry.binding.replay_digest_sha256,
            }
        )
        self.receipt_sha256 = receipt.sha256
        return TermsSectionBindingEvidenceV1(
            evidence_class=_TEST_EVIDENCE_CLASS,
            contract_id="terms-section-binding-596-1.v1",
            contract_version="v1",
            implementation_blob_sha256=_module_blob_sha256(
                derive_terms_section_receipt_entry_596_1
            ),
            api_schema_sha256=_schema_sha256(RelationReceiptEntry5961V1),
            source_sha256=self._evidence.source_sha256,
            marker_authority_envelope_sha256=envelope.envelope_sha256,
            canonical_preimage=canonical,
            receipt=receipt,
            context_sha256=self._bundle.bundle_digest_sha256,
            policy_sha256=entry.binding.policy_sha256,
            replay_sha256=entry.binding.replay_digest_sha256,
            status="TERMS_SECTION_BINDING_VERIFIED",
        )


def _load_test_evidence(
    source: object,
) -> SectionAnchorEvidenceViewV1 | Literal["UNAVAILABLE", "INVALID"]:
    if not isinstance(source, SectionAnchorEvidenceProtocol):
        return "UNAVAILABLE"
    try:
        value = source.load_section_anchor_evidence()
    except (AttributeError, TypeError, ValueError):
        return "INVALID"
    if value is None:
        return "UNAVAILABLE"
    if type(value) is not SectionAnchorEvidenceViewV1:
        return "INVALID"
    try:
        checked = SectionAnchorEvidenceViewV1.model_validate(value)
    except (TypeError, ValidationError, ValueError):
        return "INVALID"
    if checked.evidence_class != _TEST_EVIDENCE_CLASS:
        return "INVALID"
    return checked


def evaluate_section_anchor_readiness_596_1(
    marker_authority: object,
    *,
    anchor_source: SectionAnchorEvidenceProtocol | None,
) -> SectionAnchorReadinessResultV1:
    """Current formal gate: 106 actual authority is intentionally not frozen yet."""

    del marker_authority, anchor_source
    return _result("SECTION_ANCHOR_EVIDENCE_UNAVAILABLE")


def evaluate_actual_section_anchor_readiness_596_1(
    marker_authority: MarkerAuthorityEnvelopeV1,
    intake_bundle: MinerUCaptureBundle5961V1,
    terms_document: ParsedDocumentV1,
    terms_manifest: ParseManifestV1,
) -> SectionAnchorReadinessResultV1:
    """Run the real 106 collection through 103 without granting provider authority."""

    from insurance_harness.knowledge_compiler.mineru_native_section_anchor_evidence_596_1 import (
        SectionAnchorEvidenceError,
        derive_section_anchor_authority_collection_596_1,
    )
    from insurance_harness.knowledge_compiler.terms_section_endpoint_pair_bridge_596_1 import (
        derive_terms_section_receipt_entries_596_1,
    )

    try:
        bundle = MinerUCaptureBundle5961V1.model_validate(intake_bundle)
        document = ParsedDocumentV1.model_validate(terms_document)
        manifest = ParseManifestV1.model_validate(terms_manifest)
        envelope = MarkerAuthorityEnvelopeV1.model_validate(marker_authority)
        collection = derive_section_anchor_authority_collection_596_1(
            bundle, document, manifest, envelope
        )
        entries = derive_terms_section_receipt_entries_596_1(
            bundle, document, manifest, collection
        )
        if len(entries) != len(collection.relations) or not entries:
            raise ValueError("section relation cardinality mismatch")
        receipt = _proof(
            {
                "contract": "terms-section-binding-receipt-collection-596-1.v1",
                "authority_digest_sha256": collection.authority_digest_sha256,
                "relations": tuple(
                    entry.binding.replay_digest_sha256 for entry in entries
                ),
            }
        )
        return _result(
            "SECTION_ANCHOR_RELATIONS_VERIFIED",
            evidence_class="ACTUAL_106_FROZEN",
            downstream_calls=1,
            anchor_sha256=collection.authority_digest_sha256,
            receipt_sha256=receipt.sha256,
            relation_count=len(entries),
            terms_receipt_entries=entries,
        )
    except (
        SectionAnchorEvidenceError,
        TermsSectionEndpointBridgeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        return _result("SECTION_ANCHOR_EVIDENCE_INVALID")


def evaluate_test_only_future_section_anchor_readiness_596_1(
    marker_authority: object,
    intake_bundle: object,
    terms_document: object,
    terms_manifest: object,
    rate_document: object,
    rate_manifest: object,
    *,
    anchor_source: SectionAnchorEvidenceProtocol,
    future_dependencies: FutureReadinessProtocol,
) -> SectionAnchorReadinessResultV1:
    """Exercise the full future dependency chain without granting capture authority."""

    evidence = _load_test_evidence(anchor_source)
    if evidence == "UNAVAILABLE":
        return _result("SECTION_ANCHOR_EVIDENCE_UNAVAILABLE")
    if evidence == "INVALID":
        return _result("SECTION_ANCHOR_EVIDENCE_INVALID")
    try:
        bundle = MinerUCaptureBundle5961V1.model_validate(intake_bundle)
        terms_doc = ParsedDocumentV1.model_validate(terms_document)
        terms_mft = ParseManifestV1.model_validate(terms_manifest)
        rate_doc = ParsedDocumentV1.model_validate(rate_document)
        rate_mft = ParseManifestV1.model_validate(rate_manifest)
    except (TypeError, ValidationError, ValueError):
        return _result("SECTION_ANCHOR_INPUT_INVALID")
    # Revalidate all 106-owned identities before the first 103 call.
    if (
        evidence.source_sha256 != terms_doc.subject.source_sha256
        or evidence.document_hash != terms_doc.document_hash
        or evidence.manifest_hash != terms_mft.manifest_hash
        or evidence.parser_config_sha256 != terms_doc.parser.parser_config_hash
        or evidence.parser_identity_sha256
        != canonical_hash("parser-identity.v1", terms_doc.parser.model_dump(mode="python"))
    ):
        return _result("SECTION_ANCHOR_EVIDENCE_INVALID")
    binding = _TermsBinding(bundle, terms_doc, terms_mft, evidence)
    try:
        downstream = evaluate_test_only_future_marker_authority_readiness_596_1(
            marker_authority,
            bundle,
            rate_doc,
            rate_mft,
            terms_binding=binding,
            future_dependencies=future_dependencies,
        )
    except (TermsSectionEndpointBridgeError, TypeError, ValidationError, ValueError):
        return _result(
            "TERMS_SECTION_BINDING_INVALID",
            anchor_sha256=evidence.evidence_digest_sha256,
        )
    if binding.receipt_sha256 is None:
        return _result(
            "TERMS_SECTION_BINDING_INVALID",
            anchor_sha256=evidence.evidence_digest_sha256,
        )
    return _result(
        downstream.reason_code,
        evidence_class=downstream.evidence_class,
        downstream_calls=2,
        anchor_sha256=evidence.evidence_digest_sha256,
        receipt_sha256=binding.receipt_sha256,
        readiness=downstream,
    )


__all__ = [
    "ReadingOrderFactV1",
    "SectionAnchorEndpointV1",
    "SectionAnchorEvidenceProtocol",
    "SectionAnchorEvidenceViewV1",
    "SectionAnchorIntervalV1",
    "SectionAnchorReadinessResultV1",
    "evaluate_actual_section_anchor_readiness_596_1",
    "evaluate_section_anchor_readiness_596_1",
    "evaluate_test_only_future_section_anchor_readiness_596_1",
]
