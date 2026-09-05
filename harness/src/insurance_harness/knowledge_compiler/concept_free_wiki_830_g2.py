"""G2 immutable domain objects; no serving state, storage, or provider access."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, StringConstraints(min_length=1, max_length=512, pattern=r"^\S.*\S$|^\S$")]
State = Literal["present", "absent_explicitly", "unknown"]
Disposition = Literal[
    "new_page",
    "update",
    "sense",
    "field_rule",
    "alias_link",
    "pending",
    "reject",
    "mention",
    "duplicate",
]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def digest(kind: str, value: object) -> str:
    return schema_wiki_sha256(f"{kind}.830.g2.v1", value)


def concept_id(space_id: str, canonical_key: str, sense_key: str) -> str:
    normalized = [
        unicodedata.normalize("NFC", x).strip()
        for x in (space_id, canonical_key.casefold(), sense_key.casefold())
    ]
    if not all(normalized):
        raise ValueError("CONCEPT_IDENTITY_MISSING")
    return "concept_" + digest("concept-identity", normalized)


class SourceIdentity(Frozen):
    tenant_id: int = Field(gt=0, strict=True)
    space_id: Identity
    raw_kb_id: Identity
    knowledge_id: Identity
    parse_attempt: int = Field(gt=0, strict=True)
    revision_id: Identity
    source_hash: Digest
    parse_hash: Digest
    parser_identity: Identity


class SourceBlock(SourceIdentity):
    block_id: Identity
    page_number: int = Field(gt=0)
    text: str = Field(min_length=1)
    source_type: Literal["DOCUMENT", "EXPERT_REVISION_RECORD"]


class Evidence(SourceIdentity):
    source_type: Literal["DOCUMENT", "EXPERT_REVISION_RECORD"]
    block_id: Identity
    page_number: int = Field(gt=0)
    offset_unit: Literal["UNICODE_CODE_POINT"] = "UNICODE_CODE_POINT"
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)
    quote_hash: Digest

    @model_validator(mode="after")
    def check_quote(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("LOCATOR_UNRESOLVABLE")
        if hashlib.sha256(self.quote.encode()).hexdigest() != self.quote_hash:
            raise ValueError("QUOTE_MISMATCH")
        return self


def evidence_for(source: SourceBlock, start: int, end: int) -> Evidence:
    quote = source.text[start:end]
    evidence = Evidence(
        **source.model_dump(exclude={"text"}),
        start=start,
        end=end,
        quote=quote,
        quote_hash=hashlib.sha256(quote.encode()).hexdigest(),
    )
    verify_evidence(evidence, (source,))
    return evidence


def verify_evidence(evidence: Evidence, sources: Sequence[SourceBlock]) -> None:
    evidence = Evidence.model_validate(evidence)
    matches = [
        s
        for s in sources
        if (s.revision_id, s.block_id) == (evidence.revision_id, evidence.block_id)
    ]
    if len(matches) != 1:
        raise ValueError("SOURCE_REVISION_NOT_FOUND")
    source = matches[0]
    for key in (*SourceIdentity.model_fields, "source_type", "page_number"):
        if getattr(evidence, key) != getattr(source, key):
            raise ValueError("PARSE_MANIFEST_MISMATCH")
    if source.text[evidence.start : evidence.end] != evidence.quote:
        raise ValueError("QUOTE_MISMATCH")


class ConceptDefinition(Frozen):
    space_id: Identity
    canonical_key: Identity
    sense_key: Identity
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    aliases: tuple[Identity, ...] = ()
    origin: Literal["SCHEMA_DEFINITION", "MODEL_COMPILE", "EXPERT_REVISION_RECORD"] = (
        "MODEL_COMPILE"
    )

    @property
    def concept_id(self) -> str:
        return concept_id(self.space_id, self.canonical_key, self.sense_key)

    @property
    def definition_hash(self) -> str:
        return digest("concept-definition", self.model_dump(mode="json", exclude={"aliases"}))


class FieldAssertion(Frozen):
    space_id: Identity
    entity_id: Identity
    field_key: Identity
    state: State
    value: str | None
    attempted: bool
    unknown_reason: str | None = None
    evidence: tuple[Evidence, ...] = ()
    concept_ids: tuple[Identity, ...] = ()
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    entity_version: str = ""
    valid_time: str = ""

    @model_validator(mode="after")
    def check_state(self) -> Self:
        if not self.attempted:
            raise ValueError("FIELD_NOT_ATTEMPTED")
        if self.state == "unknown":
            if self.value is not None or self.evidence or not self.unknown_reason:
                raise ValueError("UNKNOWN_SHAPE_INVALID")
        elif not self.value or not self.evidence or self.unknown_reason is not None:
            raise ValueError("KNOWN_EVIDENCE_REQUIRED")
        if len(set(self.concept_ids)) != len(self.concept_ids):
            raise ValueError("DUPLICATE_CONCEPT_LINK")
        return self

    @property
    def assertion_id(self) -> str:
        return "assertion_" + digest(
            "field-identity", [self.space_id, self.entity_id, self.field_key]
        )


class FreeWikiPage(Frozen):
    space_id: Identity
    entity_id: Identity
    stable_key: Identity
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    concept_ids: tuple[Identity, ...] = ()
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    entity_version: str = ""
    valid_time: str = ""


class ConceptAggregate(Frozen):
    release_id: Identity
    activation_epoch: int = Field(gt=0)
    concept_id: Identity
    definition_hash: Digest
    assertions: tuple[FieldAssertion, ...]

    @property
    def aggregate_hash(self) -> str:
        return digest("concept-aggregate", self.model_dump(mode="json"))


def aggregate_concept(
    release_id: str,
    activation_epoch: int,
    definition: ConceptDefinition,
    assertions: Sequence[FieldAssertion],
) -> ConceptAggregate:
    checked = tuple(FieldAssertion.model_validate(a) for a in assertions)
    if any(a.space_id != definition.space_id for a in checked):
        raise ValueError("CROSS_SPACE_REFERENCE")
    ids = [a.assertion_id for a in checked]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_ASSERTION_IDENTITY")
    matching = tuple(
        sorted(
            (a for a in checked if definition.concept_id in a.concept_ids),
            key=lambda a: (a.entity_id, a.field_key),
        )
    )
    return ConceptAggregate(
        release_id=release_id,
        activation_epoch=activation_epoch,
        concept_id=definition.concept_id,
        definition_hash=definition.definition_hash,
        assertions=matching,
    )


def admission_disposition(
    placement: Disposition,
    score: int,
    *,
    evidence_valid: bool,
    identity_valid: bool,
    required: bool = False,
    attempted: bool = True,
    value_state: State = "present",
) -> Disposition:
    if not 0 <= score <= 100:
        raise ValueError("SCORE_OUT_OF_RANGE")
    if placement == "reject" or not attempted:
        return "reject"
    if not identity_valid:
        return "pending"
    if required and placement == "field_rule" and value_state == "unknown":
        return "field_rule"
    if not evidence_valid:
        return "reject"
    if placement in ("field_rule", "alias_link", "duplicate", "pending", "mention"):
        return placement
    return "mention" if score < 60 else "pending" if score < 80 else placement


def lint_members(
    space_id: str,
    definitions: Sequence[ConceptDefinition],
    assertions: Sequence[FieldAssertion],
    pages: Sequence[FreeWikiPage],
) -> None:
    ids = [d.concept_id for d in definitions]
    field_ids = [a.assertion_id for a in assertions]
    page_ids = [(p.entity_id, p.stable_key) for p in pages]
    if (
        len(ids) != len(set(ids))
        or len(field_ids) != len(set(field_ids))
        or len(page_ids) != len(set(page_ids))
    ):
        raise ValueError("DUPLICATE_MEMBER_IDENTITY")
    all_members: tuple[ConceptDefinition | FieldAssertion | FreeWikiPage, ...] = (
        *definitions,
        *assertions,
        *pages,
    )
    if any(x.space_id != space_id for x in all_members):
        raise ValueError("CROSS_SPACE_REFERENCE")
    linked_members: tuple[FieldAssertion | FreeWikiPage, ...] = (*assertions, *pages)
    links = {link for a in linked_members for link in a.concept_ids}
    if links - set(ids):
        raise ValueError("DANGLING_CONCEPT_LINK")
