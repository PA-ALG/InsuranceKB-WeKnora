"""Pure Candidate-to-Wiki draft manifest compiler (OpenSpec 076)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Final, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    ValidationError,
    computed_field,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.canonical.errors import CanonicalEncodingError
from insurance_harness.compiler.evidence_verifier import (
    EvidenceSnapshotV1,
    FieldCandidateV1,
    VerificationBatchV1,
    value_snapshot,
)
from insurance_harness.compiler.extraction_tasks import ArtifactRefV1
from insurance_harness.knowledge_compiler.candidate_batches import (
    CandidateAssemblyV1,
    CandidateChangeV1,
)
from insurance_harness.knowledge_compiler.incremental_changes import VerifiedFactV1
from insurance_harness.knowledge_compiler.source_authority import (
    FactScopeV1,
    SourceAuthorityV1,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=4096, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
MemberKind = Literal["page", "change_log"]

EVIDENCE_SNAPSHOT_OBJECT_TYPE: Final[str] = "verified-evidence-snapshot.v1"
MEMBER_OBJECT_TYPE: Final[str] = "candidate-wiki-release-member.v1"
PAGE_REVISION_OBJECT_TYPE: Final[str] = "candidate-wiki-page-revision.v1"
CHANGE_LOG_OBJECT_TYPE: Final[str] = "candidate-wiki-change-log.v1"
DRAFT_OBJECT_TYPE: Final[str] = "candidate-wiki-manifest-draft.v1"
PAGE_PAYLOAD_CONTRACT: Final[Literal["candidate-wiki-field-page.v1"]] = (
    "candidate-wiki-field-page.v1"
)
CHANGE_LOG_PAYLOAD_CONTRACT: Final[Literal["candidate-wiki-change-log.v1"]] = (
    "candidate-wiki-change-log.v1"
)
EMPTY_RELEASE_ID: Final[str] = "NONE"
_CONTROL_RE: Final[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WINDOWS_ABS_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:[\\/]")
_SECRET_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?:api[_-]?key|authorization|access[_-]?token|password|passwd|private[_-]?key|secret|token)\s*[:=]\s*\S+"
)
_SECRET_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?:sk-(?:proj-)?[A-Za-z0-9_-]{8,}"
    r"|bearer(?:\s+|[:=]\s*)[A-Za-z0-9._~+/-]{12,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


class CandidateWikiManifestError(ValueError):
    """Typed failure with no partial draft output."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        del deep
        values = self.model_dump(
            mode="python",
            round_trip=True,
            warnings=False,
            exclude_computed_fields=True,
        )
        if update is not None:
            values.update(dict(update))
        return type(self).model_validate(values)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_text(value: str, *, reason: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("non_nfc_text")
    if (
        not value
        or _CONTROL_RE.search(value)
        or value.startswith("/")
        or _WINDOWS_ABS_RE.match(value)
        or _SECRET_ASSIGNMENT_RE.search(value)
        or _SECRET_TOKEN_RE.search(value)
    ):
        raise ValueError(reason)
    return value


def _require_safe_text_tree(value: object, *, reason: str) -> None:
    if isinstance(value, str):
        _safe_text(value, reason=reason)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _require_safe_text_tree(key, reason=reason)
            _require_safe_text_tree(item, reason=reason)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _require_safe_text_tree(item, reason=reason)


def _go_json_bytes(value: object) -> bytes:
    """Match Go encoding/json for the closed JSON subset used by 076."""

    raw = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    raw = (
        raw.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return raw.encode("utf-8")


def _load_canonical_payload(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("member_payload_invalid") from None
    if not isinstance(value, dict) or _go_json_bytes(value) != raw:
        raise ValueError("member_payload_not_canonical")
    return value


def _evidence_snapshot_hash(evidence: EvidenceSnapshotV1) -> str:
    return canonical_hash(
        EVIDENCE_SNAPSHOT_OBJECT_TYPE,
        evidence.model_dump(mode="python", exclude_computed_fields=True),
    )


class WikiReleaseMemberV1(_FrozenModel):
    """Python representation of the existing Go WikiReleaseMemberSnapshot."""

    kind: MemberKind
    logical_slug: NonBlankStr
    revision_id: Sha256Hex
    member_digest: Sha256Hex
    title: str = Field(min_length=1, max_length=1024)
    content: str = Field(min_length=1, max_length=262144)
    payload: bytes = Field(min_length=2, max_length=1048576, repr=False)

    @model_validator(mode="after")
    def require_closed_member(self) -> Self:
        _safe_text(self.logical_slug, reason="unsafe_logical_slug")
        title = _safe_text(self.title, reason="unsafe_member_title")
        content = _safe_text(self.content, reason="unsafe_member_content")
        payload = _load_canonical_payload(self.payload)
        expected_revision = canonical_hash(
            PAGE_REVISION_OBJECT_TYPE,
            {
                "content_sha256": _sha256(content.encode("utf-8")),
                "payload_sha256": _sha256(self.payload),
            },
        )
        expected_member = _member_digest(
            kind=self.kind,
            logical_slug=self.logical_slug,
            revision_id=self.revision_id,
            title=title,
            content=content,
            payload=payload,
        )
        if self.revision_id != expected_revision:
            raise ValueError("member_revision_mismatch")
        if self.member_digest != expected_member:
            raise ValueError("member_digest_mismatch")
        return self

    def go_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "logical_slug": self.logical_slug,
            "revision_id": self.revision_id,
            "member_digest": self.member_digest,
            "title": self.title,
            "content": self.content,
            "payload": _load_canonical_payload(self.payload),
        }

    @property
    def member_bytes(self) -> bytes:
        return _go_json_bytes(self.go_dict())


def _member_digest(
    *,
    kind: MemberKind,
    logical_slug: str,
    revision_id: str,
    title: str,
    content: str,
    payload: dict[str, object],
) -> str:
    return canonical_hash(
        MEMBER_OBJECT_TYPE,
        {
            "kind": kind,
            "logical_slug": logical_slug,
            "revision_id": revision_id,
            "title": title,
            "content": content,
            "payload": payload,
        },
    )


def _make_member(
    *,
    kind: MemberKind,
    logical_slug: str,
    title: str,
    content: str,
    payload: dict[str, object],
) -> WikiReleaseMemberV1:
    payload_bytes = _go_json_bytes(payload)
    revision_id = canonical_hash(
        PAGE_REVISION_OBJECT_TYPE,
        {
            "content_sha256": _sha256(content.encode("utf-8")),
            "payload_sha256": _sha256(payload_bytes),
        },
    )
    return WikiReleaseMemberV1(
        kind=kind,
        logical_slug=logical_slug,
        revision_id=revision_id,
        member_digest=_member_digest(
            kind=kind,
            logical_slug=logical_slug,
            revision_id=revision_id,
            title=title,
            content=content,
            payload=payload,
        ),
        title=title,
        content=content,
        payload=payload_bytes,
    )


def _manifest_bytes(members: tuple[WikiReleaseMemberV1, ...]) -> bytes:
    return _go_json_bytes({"members": [member.go_dict() for member in members]})


class RenderedEvidenceV1(_FrozenModel):
    evidence_hash: Sha256Hex
    snapshot: EvidenceSnapshotV1

    @model_validator(mode="after")
    def require_exact_snapshot_hash(self) -> Self:
        if self.evidence_hash != _evidence_snapshot_hash(self.snapshot):
            raise ValueError("rendered_evidence_hash_mismatch")
        return self


class RenderedFactV1(_FrozenModel):
    fact_hash: Sha256Hex
    candidate_snapshot_hash: Sha256Hex
    state: Literal["known"]
    value_hash: Sha256Hex
    value_snapshot: NonBlankStr
    authority: SourceAuthorityV1
    supporting_source_revision_ids: tuple[NonBlankStr, ...]
    evidence: tuple[RenderedEvidenceV1, ...]

    @model_validator(mode="after")
    def require_closed_rendered_fact(self) -> Self:
        if not self.evidence:
            raise ValueError("rendered_fact_evidence_missing")
        if tuple(item.evidence_hash for item in self.evidence) != tuple(
            sorted(item.evidence_hash for item in self.evidence)
        ):
            raise ValueError("rendered_fact_evidence_not_canonical")
        _safe_text(self.value_snapshot, reason="unsafe_value_snapshot")
        return self


class FieldPagePayloadV1(_FrozenModel):
    contract: Literal["candidate-wiki-field-page.v1"]
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    schema_contract: ArtifactRefV1
    scope: FactScopeV1
    scope_hash: Sha256Hex
    status: Literal["resolved", "conflict"]
    action: Literal["add", "enrich", "supersede", "conflict"]
    candidate_change_hash: Sha256Hex
    facts: tuple[RenderedFactV1, ...]

    @model_validator(mode="after")
    def require_closed_page(self) -> Self:
        if self.scope_hash != self.scope.scope_hash or not self.facts:
            raise ValueError("field_page_scope_or_facts_mismatch")
        if self.status == "conflict" and (
            self.action != "conflict" or len(self.facts) < 2
        ):
            raise ValueError("conflict_page_incomplete")
        if self.status != "conflict" and self.action == "conflict":
            raise ValueError("conflict_page_status_mismatch")
        return self


class ChangeLogEntryV1(_FrozenModel):
    action: Literal["add", "enrich", "supersede", "conflict", "retract"]
    scope_hash: Sha256Hex
    change_item_hash: Sha256Hex
    candidate_change_hash: Sha256Hex
    before_member_digest: Sha256Hex | None
    after_member_digest: Sha256Hex | None
    retraction_proof_hash: Sha256Hex | None
    fact_hashes: tuple[Sha256Hex, ...]
    evidence_hashes: tuple[Sha256Hex, ...]


class ChangeLogPayloadV1(_FrozenModel):
    contract: Literal["candidate-wiki-change-log.v1"]
    candidate_hash: Sha256Hex
    human_batch_hash: Sha256Hex
    review_policy_hash: Sha256Hex
    base_release_id: NonBlankStr
    base_activation_epoch: int = Field(ge=0)
    base_manifest_digest: Sha256Hex
    change_set_hash: Sha256Hex
    changes: tuple[ChangeLogEntryV1, ...]


class ReleaseBaseAuthorityV1(_FrozenModel):
    """Expected immutable base identity returned by a trusted Release read port."""

    base_release_id: NonBlankStr
    base_activation_epoch: int = Field(ge=0)
    expected_manifest_digest: Sha256Hex
    expected_member_count: int = Field(ge=0)

    @classmethod
    def initial(cls) -> ReleaseBaseAuthorityV1:
        raw = _manifest_bytes(())
        return cls(
            base_release_id=EMPTY_RELEASE_ID,
            base_activation_epoch=0,
            expected_manifest_digest=_sha256(raw),
            expected_member_count=0,
        )


class ReleaseBaseAuthorityPort(Protocol):
    """Trust seam for resolving base identity independently from supplied members."""

    def resolve_base_authority(
        self,
        *,
        base_release_id: str,
        base_activation_epoch: int,
    ) -> ReleaseBaseAuthorityV1: ...


class BaseWikiManifestV1(_FrozenModel):
    mode: Literal["initial", "incremental"]
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    schema_contract: ArtifactRefV1
    base_release_id: NonBlankStr
    base_activation_epoch: int = Field(ge=0)
    members: tuple[WikiReleaseMemberV1, ...]
    manifest_bytes: bytes = Field(repr=False)
    manifest_digest: Sha256Hex

    @model_validator(mode="after")
    def require_complete_canonical_base(self) -> Self:
        _safe_text(self.space_id, reason="unsafe_space_id")
        _safe_text(self.product_version_id, reason="unsafe_product_version_id")
        members = _validate_member_set(self.members)
        expected = _manifest_bytes(members)
        if self.manifest_bytes != expected or self.manifest_digest != _sha256(expected):
            raise ValueError("base_manifest_identity_mismatch")
        if self.mode == "initial":
            if (
                self.base_release_id != EMPTY_RELEASE_ID
                or self.base_activation_epoch != 0
                or members
            ):
                raise ValueError("initial_base_must_be_explicitly_empty")
        elif self.base_release_id == EMPTY_RELEASE_ID or self.base_activation_epoch < 1:
            raise ValueError("incremental_base_identity_missing")
        return self

    @classmethod
    def initial(
        cls,
        *,
        space_id: str,
        product_version_id: str,
        schema_contract: ArtifactRefV1,
    ) -> BaseWikiManifestV1:
        raw = _manifest_bytes(())
        return cls(
            mode="initial",
            space_id=space_id,
            product_version_id=product_version_id,
            schema_contract=schema_contract,
            base_release_id=EMPTY_RELEASE_ID,
            base_activation_epoch=0,
            members=(),
            manifest_bytes=raw,
            manifest_digest=_sha256(raw),
        )


class CandidateWikiManifestDraftV1(_FrozenModel):
    object_type: Literal["candidate_wiki_manifest_draft.v1"] = "candidate_wiki_manifest_draft.v1"
    authority: Literal["DRAFT_ONLY_NO_REVIEW_READY_RELEASE_OR_SERVING_AUTHORITY"] = (
        "DRAFT_ONLY_NO_REVIEW_READY_RELEASE_OR_SERVING_AUTHORITY"
    )
    candidate_hash: Sha256Hex
    human_batch_hash: Sha256Hex
    review_policy_hash: Sha256Hex
    base_release_id: NonBlankStr
    base_activation_epoch: int = Field(ge=0)
    base_manifest_digest: Sha256Hex
    members: tuple[WikiReleaseMemberV1, ...]
    manifest_bytes: bytes = Field(repr=False)
    manifest_digest: Sha256Hex

    @model_validator(mode="after")
    def require_canonical_draft(self) -> Self:
        members = _validate_member_set(self.members)
        expected = _manifest_bytes(members)
        if self.manifest_bytes != expected or self.manifest_digest != _sha256(expected):
            raise ValueError("draft_manifest_identity_mismatch")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def draft_hash(self) -> str:
        return canonical_hash(
            DRAFT_OBJECT_TYPE,
            {
                "authority": self.authority,
                "candidate_hash": self.candidate_hash,
                "human_batch_hash": self.human_batch_hash,
                "review_policy_hash": self.review_policy_hash,
                "base_release_id": self.base_release_id,
                "base_activation_epoch": self.base_activation_epoch,
                "base_manifest_digest": self.base_manifest_digest,
                "manifest_digest": self.manifest_digest,
            },
        )


def _validate_member_set(
    members: tuple[WikiReleaseMemberV1, ...],
) -> tuple[WikiReleaseMemberV1, ...]:
    keys = tuple(member.logical_slug for member in members)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("manifest_members_not_sorted_unique")
    return members


def _validate_base_member_scope(
    base: BaseWikiManifestV1,
    member: WikiReleaseMemberV1,
) -> None:
    if member.kind == "change_log":
        try:
            log_payload = ChangeLogPayloadV1.model_validate(
                _load_canonical_payload(member.payload)
            )
        except (TypeError, ValueError, ValidationError):
            raise CandidateWikiManifestError("invalid_base_change_log") from None
        _require_safe_text_tree(
            log_payload.model_dump(
                mode="python", exclude_computed_fields=True
            ),
            reason="unsafe_base_change_log",
        )
        expected = _make_member(
            kind="change_log",
            logical_slug="change-log",
            title="Candidate change log",
            content=_change_log_markdown(log_payload.changes),
            payload=log_payload.model_dump(
                mode="json", exclude_computed_fields=True
            ),
        )
        if member.logical_slug != "change-log" or member != expected:
            raise CandidateWikiManifestError("invalid_base_change_log")
        return
    try:
        page_payload = FieldPagePayloadV1.model_validate(
            _load_canonical_payload(member.payload)
        )
    except (TypeError, ValueError, ValidationError):
        raise CandidateWikiManifestError("invalid_base_page_scope") from None
    _require_safe_text_tree(
        page_payload.model_dump(mode="python", exclude_computed_fields=True),
        reason="unsafe_base_page",
    )
    expected = _make_member(
        kind="page",
        logical_slug=_scope_slug(base.product_version_id, page_payload.scope_hash),
        title=page_payload.scope.field_id,
        content=_page_markdown(page_payload),
        payload=page_payload.model_dump(
            mode="json", exclude_computed_fields=True
        ),
    )
    if (
        page_payload.space_id != base.space_id
        or page_payload.product_version_id != base.product_version_id
        or page_payload.schema_contract != base.schema_contract
        or member != expected
    ):
        raise CandidateWikiManifestError("invalid_base_page_scope")


def _base_prior_fact_hashes(member: WikiReleaseMemberV1) -> tuple[str, ...]:
    try:
        payload = FieldPagePayloadV1.model_validate(
            _load_canonical_payload(member.payload)
        )
    except (TypeError, ValueError, ValidationError):
        raise CandidateWikiManifestError("invalid_base_page_facts") from None
    hashes = tuple(item.fact_hash for item in payload.facts)
    if len(hashes) != len(set(hashes)):
        raise CandidateWikiManifestError("invalid_base_page_facts")
    return tuple(sorted(hashes))


def _revalidate[ModelT: BaseModel](value: object, expected: type[ModelT], reason: str) -> ModelT:
    if not isinstance(value, expected):
        raise CandidateWikiManifestError(reason)
    try:
        return expected.model_validate(
            value.model_dump(mode="python", exclude_computed_fields=True)
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise CandidateWikiManifestError(reason) from None


def _revalidate_many[ModelT: BaseModel](
    values: Iterable[object], expected: type[ModelT], reason: str
) -> tuple[ModelT, ...]:
    return tuple(_revalidate(value, expected, reason) for value in values)


def _scope_slug(product_version_id: str, scope_hash: str) -> str:
    product_key = _sha256(product_version_id.encode("utf-8"))[:24]
    return f"products/{product_key}/fields/{scope_hash}"


def _fact_set(change: CandidateChangeV1) -> tuple[VerifiedFactV1, ...]:
    incoming = () if change.incoming_fact is None else (change.incoming_fact,)
    if change.item.action == "add":
        return incoming
    if change.item.action == "enrich":
        return tuple(sorted((*change.prior_facts, *incoming), key=lambda fact: fact.fact_hash))
    if change.item.action == "supersede":
        return incoming
    if change.item.action == "conflict":
        return tuple(sorted((*change.prior_facts, *incoming), key=lambda fact: fact.fact_hash))
    return ()


def _fact_payload(
    fact: VerifiedFactV1,
    candidate: FieldCandidateV1,
    verification: VerificationBatchV1,
) -> RenderedFactV1:
    if fact.state != "known" or fact.value_hash is None or candidate.value is None:
        raise CandidateWikiManifestError("unknown_fact_cannot_render_page")
    snapshot = value_snapshot(candidate.value)
    _safe_text(snapshot, reason="unsafe_value_snapshot")
    if _sha256(snapshot.encode("utf-8")) != fact.value_hash:
        raise CandidateWikiManifestError("value_preimage_mismatch")
    if (
        candidate.field_id != fact.scope.field_id
        or candidate.product_version_id != fact.scope.product_version_id
        or candidate.subject_id != fact.scope.subject_id
        or candidate.condition_ids != fact.scope.conditions
        or candidate.tri_state != "present"
    ):
        raise CandidateWikiManifestError("candidate_fact_scope_mismatch")
    rendered_evidence: list[RenderedEvidenceV1] = []
    for item in candidate.evidence:
        _require_safe_text_tree(
            item.model_dump(mode="python", exclude_computed_fields=True),
            reason="unsafe_evidence",
        )
        if (
            item.source_revision_id not in fact.supporting_source_revision_ids
            or item.source_revision_id != verification.source_revision_id
            or item.parse_attempt_id != verification.parse_attempt_id
            or item.parsed_document_hash != verification.parsed_document_hash
            or item.parse_manifest_hash != verification.parse_manifest_hash
            or item.product_version_id != fact.scope.product_version_id
            or item.field_id != fact.scope.field_id
            or item.support_scope.product_version_id != fact.scope.product_version_id
            or item.support_scope.subject_id != fact.scope.subject_id
            or item.support_scope.condition_ids != fact.scope.conditions
            or item.value_snapshot != snapshot
        ):
            raise CandidateWikiManifestError("evidence_scope_mismatch")
        rendered_evidence.append(
            RenderedEvidenceV1(
                evidence_hash=_evidence_snapshot_hash(item),
                snapshot=item,
            )
        )
    rendered_evidence.sort(key=lambda value: value.evidence_hash)
    if tuple(item.evidence_hash for item in rendered_evidence) != fact.evidence_hashes:
        raise CandidateWikiManifestError("evidence_preimage_mismatch")
    return RenderedFactV1(
        fact_hash=fact.fact_hash,
        candidate_snapshot_hash=candidate.candidate_snapshot_hash,
        state="known",
        value_hash=fact.value_hash,
        value_snapshot=snapshot,
        authority=fact.authority,
        supporting_source_revision_ids=fact.supporting_source_revision_ids,
        evidence=tuple(rendered_evidence),
    )


def _page_markdown(payload: FieldPagePayloadV1) -> str:
    lines = [f"# {payload.scope.field_id}", "", f"Status: {payload.status}"]
    for index, fact in enumerate(payload.facts, start=1):
        lines.extend(["", f"## Fact {index}", "", f"Value: {fact.value_snapshot}"])
        for evidence in fact.evidence:
            locator = evidence.snapshot.locator
            lines.append(
                f"Evidence p.{locator.page_number} {locator.subject_type} "
                f"{locator.subject_ref}: {evidence.snapshot.quote_snapshot}"
            )
    return "\n".join(lines)


def _render_page(
    *,
    assembly: CandidateAssemblyV1,
    change: CandidateChangeV1,
    candidates_by_fact: dict[str, FieldCandidateV1],
    verifications_by_fact: dict[str, VerificationBatchV1],
) -> WikiReleaseMemberV1:
    facts = _fact_set(change)
    if not facts:
        raise CandidateWikiManifestError("action_has_no_renderable_fact")
    try:
        fact_payloads = tuple(
            _fact_payload(
                fact,
                candidates_by_fact[fact.fact_hash],
                verifications_by_fact[fact.fact_hash],
            )
            for fact in facts
        )
    except KeyError:
        raise CandidateWikiManifestError("field_candidate_bijection_mismatch") from None
    status: Literal["resolved", "conflict"] = (
        "conflict" if change.item.action == "conflict" else "resolved"
    )
    payload = FieldPagePayloadV1(
        contract=PAGE_PAYLOAD_CONTRACT,
        space_id=assembly.candidate.space_id,
        product_version_id=assembly.candidate.product_version_id,
        schema_contract=assembly.candidate.schema_contract,
        scope=change.item.scope,
        scope_hash=change.item.scope.scope_hash,
        status=status,
        action=change.item.action,  # type: ignore[arg-type]
        candidate_change_hash=change.candidate_change_hash,
        facts=fact_payloads,
    )
    return _make_member(
        kind="page",
        logical_slug=_scope_slug(
            assembly.candidate.product_version_id, change.item.scope.scope_hash
        ),
        title=change.item.scope.field_id,
        content=_page_markdown(payload),
        payload=payload.model_dump(mode="json", exclude_computed_fields=True),
    )


def _change_log_markdown(changes: tuple[ChangeLogEntryV1, ...]) -> str:
    lines = ["# Candidate change log", ""]
    for item in changes:
        lines.append(f"- {item.action}: {item.scope_hash}")
    return "\n".join(lines)


def _change_log_member(
    *,
    assembly: CandidateAssemblyV1,
    base: BaseWikiManifestV1,
    changes: tuple[ChangeLogEntryV1, ...],
) -> WikiReleaseMemberV1:
    payload = ChangeLogPayloadV1(
        contract=CHANGE_LOG_PAYLOAD_CONTRACT,
        candidate_hash=assembly.candidate.candidate_hash,
        human_batch_hash=assembly.human_batch.batch_hash,
        review_policy_hash=assembly.human_batch.review_policy.policy_hash,
        base_release_id=base.base_release_id,
        base_activation_epoch=base.base_activation_epoch,
        base_manifest_digest=base.manifest_digest,
        change_set_hash=assembly.candidate.change_set.change_set_hash,
        changes=changes,
    )
    return _make_member(
        kind="change_log",
        logical_slug="change-log",
        title="Candidate change log",
        content=_change_log_markdown(changes),
        payload=payload.model_dump(mode="json", exclude_computed_fields=True),
    )


def _require_nfc_tree(value: object) -> None:
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise CandidateWikiManifestError("non_nfc_text")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _require_nfc_tree(key)
            _require_nfc_tree(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _require_nfc_tree(item)


def _compile_candidate_wiki_manifest(
    *,
    assembly: CandidateAssemblyV1,
    base: BaseWikiManifestV1,
    base_authority: ReleaseBaseAuthorityPort | None,
    field_candidates: Iterable[FieldCandidateV1],
) -> CandidateWikiManifestDraftV1:
    candidates_input = tuple(field_candidates)
    for value in (assembly, base, *candidates_input):
        _require_nfc_tree(
            value.model_dump(
                mode="python", warnings=False, exclude_computed_fields=True
            )
        )
    assembly = _revalidate(assembly, CandidateAssemblyV1, "invalid_candidate_assembly")
    base = _revalidate(base, BaseWikiManifestV1, "invalid_base_manifest")
    if base.mode == "initial":
        expected_base = ReleaseBaseAuthorityV1.initial()
    else:
        if base_authority is None:
            raise CandidateWikiManifestError("base_authority_port_required")
        try:
            resolved_base = base_authority.resolve_base_authority(
                base_release_id=base.base_release_id,
                base_activation_epoch=base.base_activation_epoch,
            )
        except (AttributeError, TypeError, ValueError):
            raise CandidateWikiManifestError("base_authority_unavailable") from None
        expected_base = _revalidate(
            resolved_base,
            ReleaseBaseAuthorityV1,
            "invalid_base_authority",
        )
    candidates_tuple = _revalidate_many(
        candidates_input, FieldCandidateV1, "invalid_field_candidate"
    )
    candidates = {item.candidate_snapshot_hash: item for item in candidates_tuple}
    if len(candidates) != len(candidates_tuple):
        raise CandidateWikiManifestError("duplicate_field_candidate")
    if (
        expected_base.base_release_id != base.base_release_id
        or expected_base.base_activation_epoch != base.base_activation_epoch
        or expected_base.expected_manifest_digest != base.manifest_digest
        or expected_base.expected_member_count != len(base.members)
    ):
        raise CandidateWikiManifestError("base_authority_mismatch")
    if (
        base.space_id != assembly.candidate.space_id
        or base.product_version_id != assembly.candidate.product_version_id
        or base.schema_contract != assembly.candidate.schema_contract
    ):
        raise CandidateWikiManifestError("base_scope_mismatch")
    for member in base.members:
        _validate_base_member_scope(base, member)

    all_facts = {
        fact.fact_hash: fact
        for change in assembly.candidate.changes
        for fact in (
            *change.prior_facts,
            *((change.incoming_fact,) if change.incoming_fact is not None else ()),
        )
    }
    links = {item.fact_hash: item for item in assembly.candidate.fact_verification_links}
    if set(links) != set(all_facts):
        raise CandidateWikiManifestError("fact_verification_link_bijection_mismatch")
    candidates_by_fact: dict[str, FieldCandidateV1] = {}
    verifications = {
        item.verification_hash: item
        for item in assembly.candidate.verification_batches
    }
    verifications_by_fact: dict[str, VerificationBatchV1] = {}
    for fact_hash, fact in all_facts.items():
        link = links[fact_hash]
        candidate = candidates.get(link.candidate_snapshot_hash)
        verification = verifications.get(link.verification_hash)
        if (
            candidate is None
            or verification is None
            or link.field_id != fact.scope.field_id
        ):
            raise CandidateWikiManifestError("field_candidate_bijection_mismatch")
        candidates_by_fact[fact_hash] = candidate
        verifications_by_fact[fact_hash] = verification
    if set(candidates) != {
        link.candidate_snapshot_hash for link in links.values()
    }:
        raise CandidateWikiManifestError("field_candidate_bijection_mismatch")

    current = {
        member.logical_slug: member
        for member in base.members
        if member.logical_slug != "change-log"
    }
    if base.mode == "initial" and any(
        change.item.action != "add" for change in assembly.candidate.changes
    ):
        raise CandidateWikiManifestError("initial_compile_requires_add_only")

    change_log: list[ChangeLogEntryV1] = []
    for change in assembly.candidate.changes:
        slug = _scope_slug(assembly.candidate.product_version_id, change.item.scope.scope_hash)
        before = current.get(slug)
        if change.item.action == "add":
            if before is not None:
                raise CandidateWikiManifestError("add_page_already_exists")
        elif before is None:
            raise CandidateWikiManifestError("incomplete_base_manifest")
        elif _base_prior_fact_hashes(before) != tuple(
            sorted(fact.fact_hash for fact in change.prior_facts)
        ):
            raise CandidateWikiManifestError("base_prior_fact_membership_mismatch")
        after: WikiReleaseMemberV1 | None
        if change.item.action == "retract":
            after = None
            del current[slug]
        else:
            after = _render_page(
                assembly=assembly,
                change=change,
                candidates_by_fact=candidates_by_fact,
                verifications_by_fact=verifications_by_fact,
            )
            current[slug] = after
        change_log.append(
            ChangeLogEntryV1(
                action=change.item.action,
                scope_hash=change.item.scope.scope_hash,
                change_item_hash=change.item.item_hash,
                candidate_change_hash=change.candidate_change_hash,
                before_member_digest=None if before is None else before.member_digest,
                after_member_digest=None if after is None else after.member_digest,
                retraction_proof_hash=change.item.retraction_proof_hash,
                fact_hashes=tuple(fact.fact_hash for fact in _fact_set(change)),
                evidence_hashes=change.item.evidence_hashes,
            )
        )

    log = _change_log_member(
        assembly=assembly,
        base=base,
        changes=tuple(change_log),
    )
    current[log.logical_slug] = log
    members = tuple(sorted(current.values(), key=lambda member: member.logical_slug))
    _validate_member_set(members)
    manifest = _manifest_bytes(members)
    return CandidateWikiManifestDraftV1(
        candidate_hash=assembly.candidate.candidate_hash,
        human_batch_hash=assembly.human_batch.batch_hash,
        review_policy_hash=assembly.human_batch.review_policy.policy_hash,
        base_release_id=base.base_release_id,
        base_activation_epoch=base.base_activation_epoch,
        base_manifest_digest=base.manifest_digest,
        members=members,
        manifest_bytes=manifest,
        manifest_digest=_sha256(manifest),
    )


def compile_candidate_wiki_manifest(
    *,
    assembly: CandidateAssemblyV1,
    base: BaseWikiManifestV1,
    base_authority: ReleaseBaseAuthorityPort | None,
    field_candidates: Iterable[FieldCandidateV1],
) -> CandidateWikiManifestDraftV1:
    """Compile one complete draft or fail typed before returning any output."""

    result: CandidateWikiManifestDraftV1 | None = None
    failure: CandidateWikiManifestError | None = None
    try:
        result = _compile_candidate_wiki_manifest(
            assembly=assembly,
            base=base,
            base_authority=base_authority,
            field_candidates=field_candidates,
        )
    except CandidateWikiManifestError as error:
        failure = CandidateWikiManifestError(error.reason_code)
    except (
        AttributeError,
        CanonicalEncodingError,
        TypeError,
        UnicodeError,
        ValidationError,
        ValueError,
    ):
        failure = CandidateWikiManifestError("candidate_wiki_manifest_validation_failed")
    if failure is not None:
        raise failure
    if result is None:  # pragma: no cover - closed by the branches above
        raise CandidateWikiManifestError("candidate_wiki_manifest_validation_failed")
    return result


__all__ = [
    "BaseWikiManifestV1",
    "CandidateWikiManifestDraftV1",
    "CandidateWikiManifestError",
    "ReleaseBaseAuthorityPort",
    "ReleaseBaseAuthorityV1",
    "WikiReleaseMemberV1",
    "compile_candidate_wiki_manifest",
]
