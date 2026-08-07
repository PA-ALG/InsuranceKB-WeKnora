"""Task-local marker-preserving replay seam for the frozen 086 evaluator."""

from __future__ import annotations

from insurance_harness.compiler.parsed_documents import ParsedDocumentV1, ParseManifestV1
from insurance_harness.knowledge_compiler.marker_endpoint_pair_bridge_596_1 import (
    MarkerEndpointPairInputV1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    CrossPageRelationBindingV1,
    derive_cross_page_relation_596_1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    RelationReceiptEntry5961V1,
)


def derive_marker_preserving_rate_binding_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    endpoint_pair: MarkerEndpointPairInputV1,
) -> CrossPageRelationBindingV1:
    """Replay exact 091 custody before invoking the unchanged 086 table policy."""

    checked_pair = MarkerEndpointPairInputV1.model_validate(endpoint_pair)
    return derive_cross_page_relation_596_1(
        MinerUCaptureBundle5961V1.model_validate(bundle),
        ParsedDocumentV1.model_validate(document),
        ParseManifestV1.model_validate(manifest),
        relation_kind="table",
        marker_replay=checked_pair,
        preserve_marker_envelope=True,
    )


def derive_marker_preserving_rate_entry_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    endpoint_pair: MarkerEndpointPairInputV1,
) -> RelationReceiptEntry5961V1:
    """Return the existing 096-compatible rate entry without publishing a receipt."""

    checked_bundle = MinerUCaptureBundle5961V1.model_validate(bundle)
    binding = derive_marker_preserving_rate_binding_596_1(
        checked_bundle,
        document,
        manifest,
        endpoint_pair,
    )
    rate = checked_bundle.sources[2]
    if rate.marker_provenance_digest_sha256 is None:
        # The marker-preserving 083 replay above normally owns this rejection;
        # retain a closed boundary for model_construct/model_copy callers.
        raise ValueError("marker provenance unavailable")
    return RelationReceiptEntry5961V1(
        receipt_role="rate_table",
        intake_item_digest_sha256=rate.intake_digest_sha256,
        capture_identity_sha256=rate.capture_identity_sha256,
        marker_provenance_digest_sha256=rate.marker_provenance_digest_sha256,
        binding=binding,
    )


__all__ = [
    "derive_marker_preserving_rate_binding_596_1",
    "derive_marker_preserving_rate_entry_596_1",
]
