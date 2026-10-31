"""Schema-field compile output as contract Claims and a candidate bundle (S4g Spec §2.2).

Each field becomes one Claim. Evidence is cut from the page text by the field's selected segment
ids, so every quote equals its page slice by construction; it carries the fixed source revision
(``source:v1:<knowledge_id>:<parse_attempt>:<file_sha256>``) and a PDF_TEXT_SPAN locator with
code-point offsets the platform can verify against its captured parse artifact. Evidence on a
document not read as evidence (S4i), a field whose ids no longer cut its saved evidence, or a
document the source map does not name, stops the build: the bundle never guesses where a quote
came from. Evidence on an Office page stops it too (EVIDENCE_LOCATOR_UNSUPPORTED, S11c Spec §2.3):
the platform verifies and cites only PDF text spans until S11d, which removes this stop. With
the product page (S3d-2), the bundle also carries the product's entity and its pack's presentation
profile, which must be for the same product and pack as the output.
"""

from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from insurance_harness.bundle.assemble import ACCESS_SCOPE, BundleError, assemble
from insurance_harness.bundle.client import Head
from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.compilers.schema_fields.page import ProductPage
from insurance_harness.compilers.schema_fields.review_items import logical_key
from insurance_harness.contracts.bundle import CandidateBundle, ReviewPlan
from insurance_harness.contracts.enums import (
    ClaimState,
    EvidenceMatch,
    LocatorKind,
    SourceClass,
    UnknownReason,
)
from insurance_harness.contracts.knowledge import (
    Claim,
    Evidence,
    NavigationProfile,
    Provenance,
)
from insurance_harness.evidence.segments import SegmentedSource, same_text
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.review.routing import HUMAN_DECISION, Route, Scores, labelled


def candidate_bundle(
    output: CompileOutput,
    source: SegmentedSource,
    sources: Mapping[str, SourceRevision],
    *,
    compiler_identity: str,
    base: Head | None = None,
    page: ProductPage | None = None,
    review: tuple[Route, Scores | None] | None = None,
    removals: Sequence[str] = (),
    navigation: NavigationProfile | None = None,
) -> CandidateBundle:
    """One claim member per field, plus the product page when given, based on the given Head.

    Claims are labelled by the review route (RV1): without one, a person decides.
    """
    if page is not None and (
        page.entity.entity_id != output.entity_id or page.profile.schema_pack_id != output.pack_id
    ):
        raise BundleError("PAGE_MISMATCH")
    route, scores = review if review is not None else (HUMAN_DECISION, None)
    claims = labelled(claims_from(output, source, sources), route, scores)
    return assemble(
        claims,
        compiler_identity=compiler_identity,
        base=base,
        entities=[page.entity] if page else [],
        profiles=[page.profile] if page else [],
        review_plan=[ReviewPlan(mode=route.mode, policy_ref=route.policy_ref)],
        removals=removals,
        navigations=[navigation] if navigation else [],
    )


def require_cards_version(output: CompileOutput) -> str:
    """The card version the output was compiled with; missing or blank cannot be published."""
    version = (output.cards_version or "").strip()
    if not version:
        raise BundleError("CARDS_VERSION_UNKNOWN")
    return version


def compiler_version(output: CompileOutput) -> str:
    """The compiler identity a Claim records: card version, plus the value protocol when known.

    Change decisions compare it to tell a compiler upgrade from model churn (S12c-1b). Outputs
    written before S12c-1 have no protocol and keep the plain card version they published with.
    """
    cards = require_cards_version(output)
    protocol = (output.value_protocol or "").strip()
    return f"{cards}+value:{protocol}" if protocol else cards


def claims_from(
    output: CompileOutput, source: SegmentedSource, sources: Mapping[str, SourceRevision]
) -> list[Claim]:
    version = compiler_version(output)
    return [
        _claim(output, index, field, version, source, sources)
        for index, field in enumerate(output.fields)
    ]


def _claim(
    output: CompileOutput,
    index: int,
    field: FieldResult,
    version: str,
    source: SegmentedSource,
    sources: Mapping[str, SourceRevision],
) -> Claim:
    key = logical_key(output.entity_id, field.field_key)
    evidence = _evidence(index, field, source, sources)
    try:
        return Claim(
            claim_id=key,
            logical_key=key,
            subject_ref=output.entity_id,
            predicate=field.field_key,
            state=ClaimState(field.state),
            value=field.value if field.state == "present" else None,
            evidence=evidence,
            provenance=Provenance(
                compiler="schema_fields", compiler_version=version, model=output.model
            ),
            origin=SourceClass.SOURCE_SUPPORTED,
            unknown_reason=UnknownReason.NOT_IN_MATERIAL if field.state == "unknown" else None,
        )
    except ValidationError:
        # A compile output can pass its own model yet violate the claim contract
        # (e.g. present without a value); report where, never the input itself.
        raise BundleError("CLAIM_INVALID", index) from None


def _evidence(
    index: int, field: FieldResult, source: SegmentedSource, sources: Mapping[str, SourceRevision]
) -> list[Evidence]:
    if field.state == "unknown":
        return []
    # Evidence on a document that was not read as evidence (a material excluded by role since
    # S4i, or one the source map does not name) is refused before any id is checked.
    read = {page.document for page in source.pages}
    if any(saved.document not in read for saved in field.evidence):
        raise BundleError("EVIDENCE_DOCUMENT_NOT_READ", index)
    policy = load_trust_policy()
    if any(
        (role := source.header_role(saved.document)) is not None
        and field.field_key not in policy.restricted_fields(role)
        for saved in field.evidence
    ):
        raise BundleError("EVIDENCE_ROLE_NOT_TRUSTED", index)
    # Evidence is the step-one selection plus the carried (S12c-4 §2.3) and recalled (S12c-6 §4)
    # segments step two used.
    wanted = [*field.segment_ids, *field.carried_segment_ids, *field.recalled_segment_ids]
    ids, dropped = source.resolve(wanted)
    spans = source.spans(ids) if ids and not dropped and ids == wanted else []
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
        raise BundleError("EVIDENCE_MISMATCH", index)
    evidence = []
    for span in spans:
        revision = sources.get(span.document)
        if revision is None:
            raise BundleError("SOURCE_REVISION_MISSING", index)
        locator = source.locator(span)
        if locator.kind != LocatorKind.PDF_TEXT_SPAN:
            raise BundleError("EVIDENCE_LOCATOR_UNSUPPORTED", index)
        evidence.append(
            Evidence(
                source_ref=revision.ref(span.document_sha256.lower()),
                file_sha256=span.document_sha256.lower(),
                locator=locator,
                quote=span.quote,
                match=EvidenceMatch.EXACT,
                access_scope=ACCESS_SCOPE,
            )
        )
    return evidence
