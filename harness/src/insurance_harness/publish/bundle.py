"""Compile output as a candidate bundle of claim members (S4g Spec §2.2).

Each field becomes one Claim. Evidence is cut from the page text by the field's selected segment
ids, so every quote equals its page slice by construction; it carries the fixed source revision
(``source:v1:<knowledge_id>:<parse_attempt>:<file_sha256>``) and a PDF_TEXT_SPAN locator with
code-point offsets the platform can verify against its captured parse artifact. A field whose ids
no longer cut its saved evidence, or a document the source map does not name, stops the build:
the bundle never guesses where a quote came from.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.contracts.bundle import BundleMember, CandidateBundle
from insurance_harness.contracts.enums import (
    ClaimState,
    EvidenceMatch,
    LocatorKind,
    Origin,
    SourceClass,
    UnknownReason,
)
from insurance_harness.contracts.knowledge import Claim, Evidence, Locator, Provenance
from insurance_harness.evidence.segments import SegmentedSource, same_text
from insurance_harness.publish.canonical import member_digest
from insurance_harness.publish.client import MAX_BUNDLE_BYTES, Head

ACCESS_SCOPE = "space"


class BundleError(ValueError):
    """The compile output cannot be published as it stands."""


@dataclass(frozen=True)
class SourceRevision:
    """The platform's fixed source revision a document's pages were read from."""

    knowledge_id: str
    parse_attempt: int

    def ref(self, file_sha256: str) -> str:
        return f"source:v1:{self.knowledge_id}:{self.parse_attempt}:{file_sha256}"


def candidate_bundle(
    output: CompileOutput,
    source: SegmentedSource,
    sources: Mapping[str, SourceRevision],
    *,
    compiler_identity: str,
    base: Head | None = None,
) -> CandidateBundle:
    """One claim member per field, based on the given Head (None before the first release)."""
    members = [_member(output, field, source, sources) for field in output.fields]
    bundle = CandidateBundle(
        contract_version="1",
        base_release_id=base.release_id if base else None,
        base_epoch=base.epoch if base else None,
        origin=Origin.COMPILE,
        members=members,
        compiler_identity=compiler_identity,
    )
    # Constructed through the contract model itself, so the structure already satisfies
    # contracts/candidate_bundle.schema.json (generated from it); the size limit is the platform's.
    document = bundle.model_dump(mode="json")
    if len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise BundleError("bundle exceeds the platform's size limit")
    return bundle


def _member(
    output: CompileOutput,
    field: FieldResult,
    source: SegmentedSource,
    sources: Mapping[str, SourceRevision],
) -> BundleMember:
    logical_key = f"{output.entity_id}/{field.field_key}"
    evidence = _evidence(field, source, sources)
    claim = Claim(
        claim_id=logical_key,
        logical_key=logical_key,
        subject_ref=output.entity_id,
        predicate=field.field_key,
        state=ClaimState(field.state),
        value=field.value if field.state == "present" else None,
        evidence=evidence,
        provenance=Provenance(compiler="schema_fields", model=output.model),
        origin=SourceClass.SOURCE_SUPPORTED,
        unknown_reason=UnknownReason.NOT_IN_MATERIAL if field.state == "unknown" else None,
    )
    payload = claim.model_dump(mode="json")
    return BundleMember(
        kind="claim",
        logical_slug=logical_key,
        payload=payload,
        member_digest=member_digest(payload),
        evidence_refs=sorted({item.source_ref for item in evidence}),
        access_scope=ACCESS_SCOPE,
    )


def _evidence(
    field: FieldResult, source: SegmentedSource, sources: Mapping[str, SourceRevision]
) -> list[Evidence]:
    if field.state == "unknown":
        return []
    ids, dropped = source.resolve(field.segment_ids)
    spans = source.spans(ids) if ids and not dropped and ids == field.segment_ids else []
    if (
        not spans
        or len(spans) != len(field.evidence)
        or not all(
            (span.document, span.document_sha256.lower(), span.page)
            == (saved.document, saved.document_sha256.lower(), saved.page)
            and same_text(span.quote, saved.quote)
            for span, saved in zip(spans, field.evidence, strict=True)
        )
    ):
        raise BundleError(f"{field.field_key}: segment ids do not cut the saved evidence")
    evidence = []
    for span in spans:
        revision = sources.get(span.document)
        if revision is None:
            raise BundleError(f"{field.field_key}: {span.document} has no source revision")
        evidence.append(
            Evidence(
                source_ref=revision.ref(span.document_sha256.lower()),
                file_sha256=span.document_sha256.lower(),
                locator=Locator(
                    kind=LocatorKind.PDF_TEXT_SPAN, page=span.page, start=span.start, end=span.end
                ),
                quote=span.quote,
                match=EvidenceMatch.EXACT,
                access_scope=ACCESS_SCOPE,
            )
        )
    return evidence
