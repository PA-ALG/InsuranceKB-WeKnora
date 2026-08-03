"""OpenSpec 076: Candidate to draft Wiki member manifest compiler."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    CandidateValueV1,
    EvidenceLocatorSnapshotV1,
    EvidenceSnapshotV1,
    EvidenceSupportScopeV1,
    FieldCandidateV1,
    FieldVerificationV1,
    VerificationBatchV1,
    value_snapshot,
)
from insurance_harness.knowledge_compiler import candidate_wiki_manifest as manifest_module
from insurance_harness.knowledge_compiler.candidate_batches import (
    CandidateAssemblyV1,
    FactVerificationLinkV1,
    HumanBatchPolicyV1,
    build_fixture_candidate_batch,
)
from insurance_harness.knowledge_compiler.candidate_wiki_manifest import (
    BaseWikiManifestV1,
    CandidateWikiManifestDraftV1,
    CandidateWikiManifestError,
    ReleaseBaseAuthorityV1,
    compile_candidate_wiki_manifest,
)
from insurance_harness.knowledge_compiler.incremental_changes import (
    ChangeItemDraftV1,
    ChangeSetDraftV1,
    VerifiedFactV1,
)
from tests.test_fixture_candidate_human_batch_059 import (
    HASH_A,
    _authority,
    _receipt_chain,
    _scope,
)

FIELD_ADD = "field_add"
FIELD_ENRICH = "field_enrich"
FIELD_SUPERSEDE = "field_supersede"
FIELD_CONFLICT = "field_conflict"
FIELD_RETRACT = "field_retract"
FIELD_KEEP = "field_keep"
EVIDENCE_DOMAIN = "verified-evidence-snapshot.v1"
SECRET_SHAPES = (
    "password=fixture-password",
    "token=fixture-token-123456",
    "api_key=" + "sk-" + "proj-test-fixture-1234",
    "secret: fixture-secret",
    "Bearer " + "fixture-token-123456",
    "private_key=fixture-private-key",
)


@dataclass(frozen=True)
class _TrustedBaseAuthority:
    expected: ReleaseBaseAuthorityV1

    def resolve_base_authority(
        self, *, base_release_id: str, base_activation_epoch: int
    ) -> ReleaseBaseAuthorityV1:
        assert base_release_id == self.expected.base_release_id
        assert base_activation_epoch == self.expected.base_activation_epoch
        return self.expected


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _candidate(
    *, field_id: str, revision: str, source_sha: str, raw_value: str, label: str
) -> FieldCandidateV1:
    value = CandidateValueV1(kind="enum", enum_value=raw_value)
    snapshot = value_snapshot(value)
    content = f"上下文 {label}"
    quote = f"证据 {label}"
    evidence = EvidenceSnapshotV1(
        field_id=field_id,
        product_version_id="596-1",
        source_revision_id=revision,
        parse_attempt_id=f"attempt:{label}",
        parsed_document_hash=_sha(f"document:{label}"),
        parse_manifest_hash=_sha(f"manifest:{label}"),
        locator=EvidenceLocatorSnapshotV1(
            subject_type="cell" if field_id == FIELD_ADD else "block",
            subject_ref=f"locator:{label}",
            page_number=1,
            parent_refs=(f"page:{label}", f"table:{label}"),
            content_snapshot=content,
            content_snapshot_sha256=_sha(content),
        ),
        quote_snapshot=quote,
        quote_snapshot_sha256=_sha(quote),
        value_snapshot=snapshot,
        value_snapshot_sha256=_sha(snapshot),
        support_scope=EvidenceSupportScopeV1(
            product_version_id="596-1",
            subject_id="product:596-1",
            condition_ids=("plan=standard",),
        ),
    )
    return FieldCandidateV1(
        field_id=field_id,
        product_version_id="596-1",
        subject_id="product:596-1",
        condition_ids=("plan=standard",),
        tri_state="present",
        value=value,
        evidence=(evidence,),
    )


def _fact(
    candidate: FieldCandidateV1, *, source_sha: str, reliable_at: str
) -> VerifiedFactV1:
    assert candidate.value is not None
    evidence_hashes = tuple(
        sorted(
            canonical_hash(
                EVIDENCE_DOMAIN,
                item.model_dump(mode="python", exclude_computed_fields=True),
            )
            for item in candidate.evidence
        )
    )
    source = candidate.evidence[0]
    return VerifiedFactV1(
        scope=_scope(candidate.field_id),
        state="known",
        value_hash=_sha(value_snapshot(candidate.value)),
        authority=_authority(source.source_revision_id, source_sha, reliable_at),
        evidence_hashes=evidence_hashes,
        supporting_source_revision_ids=(source.source_revision_id,),
    )


def _fact_with_source(
    candidate: FieldCandidateV1, *, source_sha: str, reliable_at: str
) -> VerifiedFactV1:
    return _fact(candidate, source_sha=source_sha, reliable_at=reliable_at)


def _assembly(
    *,
    changes: Iterable[
        tuple[str, VerifiedFactV1 | None, tuple[VerifiedFactV1, ...], str | None]
    ],
    candidates_by_fact: dict[str, FieldCandidateV1],
    verification_overrides: dict[str, tuple[str, str, str]] | None = None,
) -> CandidateAssemblyV1:
    facts: list[VerifiedFactV1] = []
    items: list[ChangeItemDraftV1] = []
    for action, incoming, prior, proof_hash in changes:
        if incoming is not None:
            facts.append(incoming)
            scope = incoming.scope
        else:
            facts.extend(prior)
            scope = prior[0].scope
        facts.extend(fact for fact in prior if fact not in facts)
        change_facts = (*prior, *((incoming,) if incoming is not None else ()))
        items.append(
            ChangeItemDraftV1(
                action=action,  # type: ignore[arg-type]
                scope=scope,
                incoming_fact_hash=None if incoming is None else incoming.fact_hash,
                prior_fact_hashes=tuple(sorted(fact.fact_hash for fact in prior)),
                evidence_hashes=(
                    ()
                    if action == "retract"
                    else tuple(
                        sorted(
                            {
                                evidence_hash
                                for fact in change_facts
                                for evidence_hash in fact.evidence_hashes
                            }
                        )
                    )
                ),
                retraction_proof_hash=proof_hash,
                reason=f"076 {action}",
            )
        )
    unique_facts = {fact.fact_hash: fact for fact in facts}
    ordered_items = tuple(sorted(items, key=lambda item: (item.scope.scope_hash, item.item_hash)))
    change_set = ChangeSetDraftV1(
        space_id="space-059",
        product_version_id="596-1",
        authority_policy_hash=HASH_A,
        input_hash=_sha("076-input"),
        items=ordered_items,
    )
    ordered_facts = tuple(unique_facts.values())
    verification_overrides = verification_overrides or {}
    verification_items: list[VerificationBatchV1] = []
    for fact in ordered_facts:
        candidate = candidates_by_fact[fact.fact_hash]
        evidence = candidate.evidence[0]
        parse_attempt, document_hash, manifest_hash = verification_overrides.get(
            fact.fact_hash,
            (
                evidence.parse_attempt_id,
                evidence.parsed_document_hash,
                evidence.parse_manifest_hash,
            ),
        )
        verification_items.append(
            VerificationBatchV1(
                contract="evidence-verification-batch.v1",
                product_version_id=fact.scope.product_version_id,
                source_revision_id=fact.authority.source_revision_id,
                parse_attempt_id=parse_attempt,
                parsed_document_hash=document_hash,
                parse_manifest_hash=manifest_hash,
                results=(
                    FieldVerificationV1(
                        field_id=fact.scope.field_id,
                        status="PASS",
                        reason_codes=(),
                        candidate_snapshot_hash=candidate.candidate_snapshot_hash,
                    ),
                ),
            )
        )
    verifications = tuple(verification_items)
    links = tuple(
        FactVerificationLinkV1(
            fact_hash=fact.fact_hash,
            verification_hash=verification.verification_hash,
            field_id=fact.scope.field_id,
            candidate_snapshot_hash=candidates_by_fact[fact.fact_hash].candidate_snapshot_hash,
        )
        for fact, verification in zip(ordered_facts, verifications, strict=True)
    )
    return build_fixture_candidate_batch(
        change_set=change_set,
        facts=ordered_facts,
        verification_batches=verifications,
        receipt_chains=tuple(_receipt_chain(item) for item in verifications),
        fact_verification_links=links,
        repair_resolutions=(),
        review_policy=HumanBatchPolicyV1(
            policy_id="076-human-batch", high_risk_field_ids=()
        ),
    )


def _facts() -> tuple[dict[str, VerifiedFactV1], dict[str, FieldCandidateV1]]:
    specs = (
        ("add", FIELD_ADD, "r-add", "a" * 64, "已添加", "a"),
        ("enrich-old", FIELD_ENRICH, "r-enrich-old", "b" * 64, "相同", "b"),
        ("enrich-new", FIELD_ENRICH, "r-enrich-new", "c" * 64, "相同", "c"),
        ("sup-old", FIELD_SUPERSEDE, "r-sup-old", "d" * 64, "旧值", "d"),
        ("sup-new", FIELD_SUPERSEDE, "r-sup-new", "e" * 64, "新值", "e"),
        ("conf-old", FIELD_CONFLICT, "r-conf-old", "1" * 64, "左值", "f"),
        ("conf-new", FIELD_CONFLICT, "r-conf-new", "2" * 64, "右值", "g"),
        ("retract", FIELD_RETRACT, "r-retract", "3" * 64, "退役", "h"),
        ("keep", FIELD_KEEP, "r-keep", "4" * 64, "不变", "i"),
    )
    facts: dict[str, VerifiedFactV1] = {}
    candidates: dict[str, FieldCandidateV1] = {}
    for index, (key, field, revision, source, raw_value, label) in enumerate(specs):
        candidate = _candidate(
            field_id=field,
            revision=revision,
            source_sha=source,
            raw_value=raw_value,
            label=label,
        )
        fact = _fact_with_source(
            candidate,
            source_sha=source,
            reliable_at=f"2026-01-{index + 1:02d}T00:00:00.000000Z",
        )
        facts[key] = fact
        candidates[fact.fact_hash] = candidate
    return facts, candidates


def _initial() -> tuple[
    CandidateWikiManifestDraftV1,
    dict[str, VerifiedFactV1],
    dict[str, FieldCandidateV1],
]:
    facts, candidates = _facts()
    keys = ("enrich-old", "sup-old", "conf-old", "retract", "keep")
    selected = {facts[key].fact_hash: candidates[facts[key].fact_hash] for key in keys}
    assembly = _assembly(
        changes=(("add", facts[key], (), None) for key in keys),
        candidates_by_fact=selected,
    )
    result = compile_candidate_wiki_manifest(
        assembly=assembly,
        base=BaseWikiManifestV1.initial(
            space_id="space-059",
            product_version_id="596-1",
            schema_contract=assembly.candidate.schema_contract,
        ),
        base_authority=None,
        field_candidates=selected.values(),
    )
    return result, facts, candidates


def _incremental_inputs() -> tuple[
    CandidateAssemblyV1,
    BaseWikiManifestV1,
    _TrustedBaseAuthority,
    tuple[FieldCandidateV1, ...],
]:
    initial, facts, candidates = _initial()
    changes = (
        ("add", facts["add"], (), None),
        ("enrich", facts["enrich-new"], (facts["enrich-old"],), None),
        ("supersede", facts["sup-new"], (facts["sup-old"],), None),
        ("conflict", facts["conf-new"], (facts["conf-old"],), None),
        ("retract", None, (facts["retract"],), _sha("retraction-proof")),
    )
    selected_hashes = {
        fact.fact_hash
        for _, incoming, prior, _ in changes
        for fact in (*prior, *((incoming,) if incoming else ()))
    }
    selected = {fact_hash: candidates[fact_hash] for fact_hash in selected_hashes}
    assembly = _assembly(changes=changes, candidates_by_fact=selected)
    base = BaseWikiManifestV1(
        mode="incremental",
        space_id="space-059",
        product_version_id="596-1",
        schema_contract=assembly.candidate.schema_contract,
        base_release_id="release-r0",
        base_activation_epoch=1,
        members=initial.members,
        manifest_bytes=initial.manifest_bytes,
        manifest_digest=initial.manifest_digest,
    )
    binding = _TrustedBaseAuthority(
        ReleaseBaseAuthorityV1(
            base_release_id="release-r0",
            base_activation_epoch=1,
            expected_manifest_digest=initial.manifest_digest,
            expected_member_count=len(initial.members),
        )
    )
    return assembly, base, binding, tuple(selected.values())


def _compile_incremental() -> CandidateWikiManifestDraftV1:
    assembly, base, binding, candidates = _incremental_inputs()
    return compile_candidate_wiki_manifest(
        assembly=assembly,
        base=base,
        base_authority=binding,
        field_candidates=candidates,
    )


def _vector_result() -> CandidateWikiManifestDraftV1:
    facts, candidates = _facts()
    old_fact = facts["enrich-old"]
    new_fact = facts["enrich-new"]
    old_candidate = candidates[old_fact.fact_hash]
    new_candidate = candidates[new_fact.fact_hash]
    initial_assembly = _assembly(
        changes=(("add", old_fact, (), None),),
        candidates_by_fact={old_fact.fact_hash: old_candidate},
    )
    initial = compile_candidate_wiki_manifest(
        assembly=initial_assembly,
        base=BaseWikiManifestV1.initial(
            space_id="space-059",
            product_version_id="596-1",
            schema_contract=initial_assembly.candidate.schema_contract,
        ),
        base_authority=None,
        field_candidates=(old_candidate,),
    )
    assembly = _assembly(
        changes=(("enrich", new_fact, (old_fact,), None),),
        candidates_by_fact={
            old_fact.fact_hash: old_candidate,
            new_fact.fact_hash: new_candidate,
        },
    )
    base = BaseWikiManifestV1(
        mode="incremental",
        space_id="space-059",
        product_version_id="596-1",
        schema_contract=assembly.candidate.schema_contract,
        base_release_id="release-vector-r0",
        base_activation_epoch=1,
        members=initial.members,
        manifest_bytes=initial.manifest_bytes,
        manifest_digest=initial.manifest_digest,
    )
    return compile_candidate_wiki_manifest(
        assembly=assembly,
        base=base,
        base_authority=_TrustedBaseAuthority(
            ReleaseBaseAuthorityV1(
                base_release_id="release-vector-r0",
                base_activation_epoch=1,
                expected_manifest_digest=initial.manifest_digest,
                expected_member_count=len(initial.members),
            )
        ),
        field_candidates=(old_candidate, new_candidate),
    )


def test_initial_and_incremental_compile_all_actions_without_authority() -> None:
    initial, _, _ = _initial()
    result = _compile_incremental()
    assert result.authority == "DRAFT_ONLY_NO_REVIEW_READY_RELEASE_OR_SERVING_AUTHORITY"
    actions = {
        item["action"]
        for item in json.loads(
            next(member for member in result.members if member.kind == "change_log").payload
        )["changes"]
    }
    assert actions == {"add", "enrich", "supersede", "conflict", "retract"}
    initial_by_slug = {member.logical_slug: member for member in initial.members}
    result_by_slug = {member.logical_slug: member for member in result.members}
    keep_slug = next(slug for slug, member in initial_by_slug.items() if member.title == FIELD_KEEP)
    assert result_by_slug[keep_slug].member_bytes == initial_by_slug[keep_slug].member_bytes
    assert not any(member.title == FIELD_RETRACT for member in result.members)


def test_exact_field_candidate_bijection_and_full_locator_are_preserved() -> None:
    assembly, base, binding, candidates = _incremental_inputs()
    with pytest.raises(CandidateWikiManifestError, match="field_candidate_bijection"):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=base,
            base_authority=binding,
            field_candidates=candidates[1:],
        )
    result = _compile_incremental()
    add = next(member for member in result.members if member.title == FIELD_ADD)
    snapshot = json.loads(add.payload)["facts"][0]["evidence"][0]["snapshot"]
    expected = next(candidate for candidate in candidates if candidate.field_id == FIELD_ADD)
    assert snapshot == expected.evidence[0].model_dump(mode="json")
    assert {"parsed_document_hash", "parse_manifest_hash", "parse_attempt_id"} <= snapshot.keys()


@pytest.mark.parametrize(
    ("parse_attempt", "document_hash", "manifest_hash"),
    [
        ("attempt:drift", _sha("document:a"), _sha("manifest:a")),
        ("attempt:a", _sha("document:drift"), _sha("manifest:a")),
        ("attempt:a", _sha("document:a"), _sha("manifest:drift")),
    ],
)
def test_evidence_must_match_fully_recomputed_verification_and_receipt_custody(
    parse_attempt: str, document_hash: str, manifest_hash: str
) -> None:
    facts, candidates = _facts()
    fact = facts["add"]
    candidate = candidates[fact.fact_hash]
    assembly = _assembly(
        changes=(("add", fact, (), None),),
        candidates_by_fact={fact.fact_hash: candidate},
        verification_overrides={
            fact.fact_hash: (parse_attempt, document_hash, manifest_hash)
        },
    )
    with pytest.raises(CandidateWikiManifestError, match="evidence_scope_mismatch"):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=BaseWikiManifestV1.initial(
                space_id="space-059",
                product_version_id="596-1",
                schema_contract=assembly.candidate.schema_contract,
            ),
            base_authority=None,
            field_candidates=(candidate,),
        )


def test_evidence_source_revision_must_match_linked_verification() -> None:
    candidate = _candidate(
        field_id=FIELD_ADD,
        revision="r-evidence-drift",
        source_sha="a" * 64,
        raw_value="safe",
        label="source-drift",
    )
    assert candidate.value is not None
    fact = VerifiedFactV1(
        scope=_scope(FIELD_ADD),
        state="known",
        value_hash=_sha(value_snapshot(candidate.value)),
        authority=_authority(
            "r-authority", "a" * 64, "2026-01-01T00:00:00.000000Z"
        ),
        evidence_hashes=tuple(
            canonical_hash(
                EVIDENCE_DOMAIN,
                item.model_dump(mode="python", exclude_computed_fields=True),
            )
            for item in candidate.evidence
        ),
        supporting_source_revision_ids=("r-authority",),
    )
    assembly = _assembly(
        changes=(("add", fact, (), None),),
        candidates_by_fact={fact.fact_hash: candidate},
    )
    with pytest.raises(CandidateWikiManifestError, match="evidence_scope_mismatch"):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=BaseWikiManifestV1.initial(
                space_id="space-059",
                product_version_id="596-1",
                schema_contract=assembly.candidate.schema_contract,
            ),
            base_authority=None,
            field_candidates=(candidate,),
        )


def test_bogus_fact_link_candidate_snapshot_hash_is_rejected() -> None:
    assembly, base, binding, candidates = _incremental_inputs()
    links = assembly.candidate.fact_verification_links
    bogus = links[0].model_copy(update={"candidate_snapshot_hash": "0" * 64})
    candidate_payload = {
        field: getattr(assembly.candidate, field)
        for field in type(assembly.candidate).model_fields
    }
    candidate_payload["fact_verification_links"] = (bogus, *links[1:])
    forged_candidate = assembly.candidate.model_construct(**candidate_payload)
    forged = CandidateAssemblyV1.model_construct(
        candidate=forged_candidate, human_batch=assembly.human_batch
    )
    with pytest.raises(CandidateWikiManifestError):
        compile_candidate_wiki_manifest(
            assembly=forged,
            base=base,
            base_authority=binding,
            field_candidates=candidates,
        )


def test_release_base_authority_port_rejects_truncation_and_forged_payload() -> None:
    assembly, base, binding, candidates = _incremental_inputs()
    kept = base.members[:-1]
    raw = manifest_module._manifest_bytes(kept)
    truncated = BaseWikiManifestV1(
        mode="incremental",
        space_id=base.space_id,
        product_version_id=base.product_version_id,
        schema_contract=base.schema_contract,
        base_release_id=base.base_release_id,
        base_activation_epoch=base.base_activation_epoch,
        members=kept,
        manifest_bytes=raw,
        manifest_digest=hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(CandidateWikiManifestError, match="base_authority_mismatch"):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=truncated,
            base_authority=binding,
            field_candidates=candidates,
        )
    attacker_created_dto = ReleaseBaseAuthorityV1(
        base_release_id=truncated.base_release_id,
        base_activation_epoch=truncated.base_activation_epoch,
        expected_manifest_digest=truncated.manifest_digest,
        expected_member_count=len(truncated.members),
    )
    with pytest.raises(CandidateWikiManifestError, match="base_authority_unavailable"):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=truncated,
            base_authority=attacker_created_dto,  # type: ignore[arg-type]
            field_candidates=candidates,
        )
    with pytest.raises(CandidateWikiManifestError, match="base_authority_port_required"):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=base,
            base_authority=None,
            field_candidates=candidates,
        )

    page = next(member for member in base.members if member.kind == "page")
    payload = json.loads(page.payload)
    payload["extra"] = "forged"
    forged = manifest_module._make_member(
        kind="page",
        logical_slug=page.logical_slug,
        title=page.title,
        content=page.content,
        payload=payload,
    )
    members = tuple(
        sorted(
            (forged, *(item for item in base.members if item != page)),
            key=lambda item: item.logical_slug,
        )
    )
    forged_raw = manifest_module._manifest_bytes(members)
    forged_base = BaseWikiManifestV1(
        mode="incremental",
        space_id=base.space_id,
        product_version_id=base.product_version_id,
        schema_contract=base.schema_contract,
        base_release_id=base.base_release_id,
        base_activation_epoch=base.base_activation_epoch,
        members=members,
        manifest_bytes=forged_raw,
        manifest_digest=hashlib.sha256(forged_raw).hexdigest(),
    )
    forged_authority = _TrustedBaseAuthority(
        ReleaseBaseAuthorityV1(
            base_release_id=forged_base.base_release_id,
            base_activation_epoch=forged_base.base_activation_epoch,
            expected_manifest_digest=forged_base.manifest_digest,
            expected_member_count=len(forged_base.members),
        )
    )
    with pytest.raises(CandidateWikiManifestError, match="invalid_base_page_scope"):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=forged_base,
            base_authority=forged_authority,
            field_candidates=candidates,
        )

    content_forged = manifest_module._make_member(
        kind="page",
        logical_slug=page.logical_slug,
        title=page.title,
        content=page.content + "\nforged readable value",
        payload=json.loads(page.payload),
    )
    content_members = tuple(
        sorted(
            (content_forged, *(item for item in base.members if item != page)),
            key=lambda item: item.logical_slug,
        )
    )
    content_raw = manifest_module._manifest_bytes(content_members)
    content_base = BaseWikiManifestV1(
        mode="incremental",
        space_id=base.space_id,
        product_version_id=base.product_version_id,
        schema_contract=base.schema_contract,
        base_release_id=base.base_release_id,
        base_activation_epoch=base.base_activation_epoch,
        members=content_members,
        manifest_bytes=content_raw,
        manifest_digest=hashlib.sha256(content_raw).hexdigest(),
    )
    with pytest.raises(CandidateWikiManifestError, match="invalid_base_page_scope"):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=content_base,
            base_authority=_TrustedBaseAuthority(
                ReleaseBaseAuthorityV1(
                    base_release_id=content_base.base_release_id,
                    base_activation_epoch=content_base.base_activation_epoch,
                    expected_manifest_digest=content_base.manifest_digest,
                    expected_member_count=len(content_base.members),
                )
            ),
            field_candidates=candidates,
        )


@pytest.mark.parametrize("secret", SECRET_SHAPES)
def test_secret_shaped_value_is_rejected(secret: str) -> None:
    candidate = _candidate(
        field_id=FIELD_ADD,
        revision="r-secret",
        source_sha="a" * 64,
        raw_value=secret,
        label="secret",
    )
    fact = _fact_with_source(
        candidate, source_sha="a" * 64, reliable_at="2026-01-01T00:00:00.000000Z"
    )
    assembly = _assembly(
        changes=(("add", fact, (), None),),
        candidates_by_fact={fact.fact_hash: candidate},
    )
    with pytest.raises(CandidateWikiManifestError):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=BaseWikiManifestV1.initial(
                space_id="space-059",
                product_version_id="596-1",
                schema_contract=assembly.candidate.schema_contract,
            ),
            base_authority=None,
            field_candidates=(candidate,),
        )


@pytest.mark.parametrize("secret", SECRET_SHAPES)
def test_secret_shaped_evidence_is_rejected(secret: str) -> None:
    candidate = _candidate(
        field_id=FIELD_ADD,
        revision="r-secret-evidence",
        source_sha="a" * 64,
        raw_value="safe",
        label="secret-evidence",
    )
    old = candidate.evidence[0]
    locator = old.locator.model_copy(
        update={"content_snapshot": secret, "content_snapshot_sha256": _sha(secret)}
    )
    evidence = old.model_copy(update={"locator": locator})
    candidate = candidate.model_copy(update={"evidence": (evidence,)})
    fact = _fact_with_source(
        candidate, source_sha="a" * 64, reliable_at="2026-01-01T00:00:00.000000Z"
    )
    assembly = _assembly(
        changes=(("add", fact, (), None),),
        candidates_by_fact={fact.fact_hash: candidate},
    )
    with pytest.raises(CandidateWikiManifestError):
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=BaseWikiManifestV1.initial(
                space_id="space-059",
                product_version_id="596-1",
                schema_contract=assembly.candidate.schema_contract,
            ),
            base_authority=None,
            field_candidates=(candidate,),
        )


def test_decomposed_unicode_and_malformed_inputs_are_typed_without_cause() -> None:
    assembly, base, binding, candidates = _incremental_inputs()
    original = candidates[0]
    bad_value = CandidateValueV1.model_construct(kind="enum", enum_value="Cafe\u0301")
    malformed = FieldCandidateV1.model_construct(
        **{
            **original.model_dump(mode="python", exclude_computed_fields=True),
            "value": bad_value,
        }
    )
    with pytest.raises(CandidateWikiManifestError, match="non_nfc_text") as caught:
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=base,
            base_authority=binding,
            field_candidates=(malformed, *candidates[1:]),
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    malformed_binding = ReleaseBaseAuthorityV1.model_construct(
        base_release_id=base.base_release_id,
        base_activation_epoch=base.base_activation_epoch,
        expected_manifest_digest=base.manifest_digest,
        expected_member_count=-1,
    )
    with pytest.raises(CandidateWikiManifestError) as malformed_caught:
        compile_candidate_wiki_manifest(
            assembly=assembly,
            base=base,
            base_authority=_TrustedBaseAuthority(malformed_binding),
            field_candidates=candidates,
        )
    assert malformed_caught.value.__cause__ is None
    assert malformed_caught.value.__context__ is None


def test_order_is_stable_and_manifest_mutation_changes_identity() -> None:
    assembly, base, binding, candidates = _incremental_inputs()
    left = compile_candidate_wiki_manifest(
        assembly=assembly,
        base=base,
        base_authority=binding,
        field_candidates=candidates,
    )
    right = compile_candidate_wiki_manifest(
        assembly=assembly,
        base=base,
        base_authority=binding,
        field_candidates=reversed(candidates),
    )
    assert left == right
    mutated = bytearray(left.manifest_bytes)
    mutated[-2] ^= 1
    assert hashlib.sha256(mutated).hexdigest() != left.manifest_digest
    with pytest.raises(ValueError, match="draft_manifest_identity_mismatch"):
        left.model_copy(update={"manifest_bytes": bytes(mutated)})


def test_frozen_incremental_non_ascii_python_to_go_manifest_vector() -> None:
    vector_path = (
        Path(__file__).parents[2]
        / "internal/application/service/testdata/076_candidate_wiki_manifest_vector.json"
    )
    vector = json.loads(vector_path.read_bytes())
    result = _vector_result()
    assert [member.go_dict() for member in result.members] == vector["members"]
    assert result.manifest_bytes.decode() == vector["expected_manifest_utf8"]
    assert result.manifest_digest == vector["expected_manifest_digest"]
