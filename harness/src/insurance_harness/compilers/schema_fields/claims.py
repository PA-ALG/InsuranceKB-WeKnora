"""Schema-field compile output as contract Claims and a candidate bundle (S4g Spec §2.2).

Each field becomes one Claim. Evidence is cut from the page text by the field's selected segment
ids, so every quote equals its page slice by construction; it carries the fixed source revision
(``source:v1:<knowledge_id>:<parse_attempt>:<file_sha256>``) and a PDF_TEXT_SPAN locator with
code-point offsets the platform can verify against its captured parse artifact. A field whose ids
no longer cut its saved evidence, or a document the source map does not name, stops the build:
the bundle never guesses where a quote came from.
"""

from collections.abc import Mapping

from insurance_harness.bundle.assemble import ACCESS_SCOPE, BundleError, assemble
from insurance_harness.bundle.client import Head
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.enums import (
    ClaimState,
    EvidenceMatch,
    LocatorKind,
    SourceClass,
    UnknownReason,
)
from insurance_harness.contracts.knowledge import Claim, Evidence, Locator, Provenance
from insurance_harness.evidence.segments import SegmentedSource, same_text
from insurance_harness.evidence.source_ref import SourceRevision


def candidate_bundle(
    output: CompileOutput,
    source: SegmentedSource,
    sources: Mapping[str, SourceRevision],
    *,
    compiler_identity: str,
    base: Head | None = None,
) -> CandidateBundle:
    """One claim member per field, based on the given Head (None before the first release)."""
    claims = claims_from(output, source, sources)
    return assemble(claims, compiler_identity=compiler_identity, base=base)


def claims_from(
    output: CompileOutput, source: SegmentedSource, sources: Mapping[str, SourceRevision]
) -> list[Claim]:
    claims = []
    for field in output.fields:
        logical_key = f"{output.entity_id}/{field.field_key}"
        claims.append(
            Claim(
                claim_id=logical_key,
                logical_key=logical_key,
                subject_ref=output.entity_id,
                predicate=field.field_key,
                state=ClaimState(field.state),
                value=field.value if field.state == "present" else None,
                evidence=_evidence(field, source, sources),
                provenance=Provenance(
                    compiler="schema_fields",
                    compiler_version=output.cards_version or "",
                    model=output.model,
                ),
                origin=SourceClass.SOURCE_SUPPORTED,
                unknown_reason=UnknownReason.NOT_IN_MATERIAL if field.state == "unknown" else None,
            )
        )
    return claims


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
        raise BundleError("EVIDENCE_MISMATCH", field.field_key)
    evidence = []
    for span in spans:
        revision = sources.get(span.document)
        if revision is None:
            raise BundleError("SOURCE_REVISION_MISSING", field.field_key)
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
