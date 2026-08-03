"""OpenSpec077: complete Candidate display-only human review dossier."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Literal

import pytest

from insurance_harness.compiler.evidence_verifier import (
    CandidateValueV1,
    EvidenceLocatorSnapshotV1,
    EvidenceReviewItemV1,
    EvidenceSnapshotV1,
    EvidenceSupportScopeV1,
    FieldCandidateV1,
    FieldVerificationV1,
    GapV1,
    RepairResolutionV1,
    VerificationBatchV1,
    value_snapshot,
)
from insurance_harness.compiler.extraction_receipts import (
    FieldOutcomeV1,
    ReceiptChainV1,
    build_attempt_receipt,
    build_initial_attempt,
)
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    AttemptBudgetV1,
    ExtractionInputRefsV1,
    build_extraction_task,
    build_extraction_task_profile,
)
from insurance_harness.compiler.material_profiles import (
    MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
    ApprovedParsePolicy,
    FieldAuthority,
    MaterialProfile,
    ParsePolicyReceipt,
    SourceDocumentIdentity,
)
from insurance_harness.knowledge_compiler.candidate_batches import (
    CandidateAssemblyV1,
    FactVerificationLinkV1,
    HumanBatchPolicyV1,
    build_fixture_candidate_batch,
)
from insurance_harness.knowledge_compiler.incremental_changes import (
    ChangeItemDraftV1,
    ChangeSetDraftV1,
    VerifiedFactV1,
)
from insurance_harness.knowledge_compiler.review_dossier import (
    DISPLAY_AUTHORITY,
    ReviewDossierError,
    build_review_dossier,
    dossier_json_bytes,
)
from insurance_harness.knowledge_compiler.review_dossier_html import (
    render_review_dossier_html,
)
from insurance_harness.knowledge_compiler.source_authority import (
    FactScopeV1,
    MaterialBindingReceiptV1,
    SourceAuthorityV1,
)

ROOT = Path(__file__).parents[1]
SPACE_ID = "space-077"
PRODUCT_VERSION_ID = "596-1"
SCHEMA_HASH = "e" * 64
CATALOG_HASH = "a" * 64
BINDING_HASH = "b" * 64
LocatorKind = Literal["page", "block", "table", "cell"]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope(field_id: str) -> FactScopeV1:
    return FactScopeV1(
        space_id=SPACE_ID,
        product_version_id=PRODUCT_VERSION_ID,
        subject_id="product:596-1",
        field_id=field_id,
        valid_from="2026-01-01T00:00:00.000000Z",
        valid_through=None,
        region="CN",
        channel="all-approved-channels",
        population="eligible-insured",
        conditions=("plan=standard",),
    )


def _authority(revision: str) -> SourceAuthorityV1:
    source_id = _sha(f"source:{revision}")
    return SourceAuthorityV1(
        source_id=source_id,
        source_revision_id=revision,
        material_role="terms",
        binding=MaterialBindingReceiptV1(
            catalog_hash=CATALOG_HASH,
            binding_hash=BINDING_HASH,
            space_id=SPACE_ID,
            product_version_id=PRODUCT_VERSION_ID,
            source_id=source_id,
            source_revision_id=revision,
            material_role="terms",
        ),
        reliable_at="2026-01-01T00:00:00.000000Z",
    )


def _candidate(
    field_id: str,
    *,
    revision: str,
    value: str,
    locator_kind: LocatorKind,
    marker: str = "review",
    evidence_source_revision_id: str | None = None,
    evidence_support_product_version_id: str | None = None,
) -> FieldCandidateV1:
    candidate_value = CandidateValueV1(kind="enum", enum_value=value)
    snapshot = value_snapshot(candidate_value)
    content = f"<{marker}> source text for {field_id}"
    quote = f"source text for {field_id}"
    page_number = {"page": 1, "block": 2, "table": 3, "cell": 4}[locator_kind]
    parent_refs = {
        "page": (),
        "block": (f"page-{page_number}",),
        "table": (f"page-{page_number}",),
        "cell": (f"page-{page_number}", f"table-{field_id}"),
    }[locator_kind]
    evidence = EvidenceSnapshotV1(
        field_id=field_id,
        product_version_id=PRODUCT_VERSION_ID,
        source_revision_id=evidence_source_revision_id or revision,
        parse_attempt_id=f"attempt:{revision}",
        parsed_document_hash=_sha(f"document:{revision}"),
        parse_manifest_hash=_sha(f"manifest:{revision}"),
        locator=EvidenceLocatorSnapshotV1(
            subject_type=locator_kind,
            subject_ref=f"{locator_kind}:{field_id}:{revision}",
            page_number=page_number,
            parent_refs=parent_refs,
            content_snapshot=content,
            content_snapshot_sha256=_sha(content),
        ),
        quote_snapshot=quote,
        quote_snapshot_sha256=_sha(quote),
        value_snapshot=snapshot,
        value_snapshot_sha256=_sha(snapshot),
        support_scope=EvidenceSupportScopeV1(
            product_version_id=(
                evidence_support_product_version_id or PRODUCT_VERSION_ID
            ),
            subject_id="product:596-1",
            condition_ids=("plan=standard",),
        ),
    )
    return FieldCandidateV1(
        field_id=field_id,
        product_version_id=PRODUCT_VERSION_ID,
        subject_id="product:596-1",
        condition_ids=("plan=standard",),
        tri_state="present",
        value=candidate_value,
        evidence=(evidence,),
    )


def _fact(
    candidate: FieldCandidateV1,
    revision: str,
    *,
    supporting_source_revision_ids: tuple[str, ...] | None = None,
) -> VerifiedFactV1:
    return VerifiedFactV1(
        scope=_scope(candidate.field_id),
        state="known",
        value_hash=_sha(value_snapshot(candidate.value)),
        authority=_authority(revision),
        evidence_hashes=(_sha(f"evidence:{candidate.candidate_snapshot_hash}"),),
        supporting_source_revision_ids=(
            (revision,)
            if supporting_source_revision_ids is None
            else supporting_source_revision_ids
        ),
    )


def _verification(
    candidate: FieldCandidateV1,
    *,
    revision: str,
    parse_identity_override: tuple[str, str, str] | None = None,
) -> VerificationBatchV1:
    evidence = candidate.evidence[0]
    parse_attempt_id, parsed_document_hash, parse_manifest_hash = (
        (
            evidence.parse_attempt_id,
            evidence.parsed_document_hash,
            evidence.parse_manifest_hash,
        )
        if parse_identity_override is None
        else parse_identity_override
    )
    return VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id=PRODUCT_VERSION_ID,
        source_revision_id=revision,
        parse_attempt_id=parse_attempt_id,
        parsed_document_hash=parsed_document_hash,
        parse_manifest_hash=parse_manifest_hash,
        results=(
            FieldVerificationV1(
                field_id=candidate.field_id,
                status="PASS",
                reason_codes=(),
                candidate_snapshot_hash=candidate.candidate_snapshot_hash,
            ),
        ),
    )


def _receipt_chain(verification: VerificationBatchV1) -> ReceiptChainV1:
    field_ids = tuple(item.field_id for item in verification.results)
    budget = AttemptBudgetV1(
        max_fields=len(field_ids), max_total_attempts=2, max_targeted_repairs=1
    )
    material_profile = MaterialProfile(
        profile_id="profile-terms-596-1",
        material_role="terms",
        source=SourceDocumentIdentity(
            name="terms.pdf",
            path="dataset/596-1/terms.pdf",
            size=1024,
            sha256=CATALOG_HASH,
        ),
        document_type_id="insurance-terms",
        required_parse_capabilities=("ordered_pages",),
        parse_policy=ApprovedParsePolicy(
            policy_id="policy-077",
            policy_version="v1",
            material_profile_id="profile-terms-596-1",
            default_parser_profile_ref=(
                "approved-parser-profile:parser-neutral-default.v1"
            ),
            bounded_upgrade_profile_ref=(
                "approved-parser-profile:parser-neutral-upgrade.v1"
            ),
            upgrade_trigger_conditions=("required_capability_missing",),
            max_parser_attempts=2,
            privacy_policy_ref="privacy-policy:internal.v1",
            output_policy_ref="output-policy:internal.v1",
        ),
    )
    policy_receipt = ParsePolicyReceipt.model_validate(
        {
            **material_profile.parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": material_profile.required_parse_capabilities,
        }
    )
    profile = build_extraction_task_profile(
        material_profile=material_profile,
        material_profile_binding_hash=BINDING_HASH,
        parse_policy_receipt=policy_receipt,
        field_authority=FieldAuthority(
            authority_class="contract_fact",
            primary_role="terms",
            support_roles=(),
            field_ids=field_ids,
        ),
        attempt_budget=budget,
    )
    task = build_extraction_task(
        space_id=SPACE_ID,
        product_version_id=PRODUCT_VERSION_ID,
        source_revision_id=verification.source_revision_id,
        material_role="terms",
        module_id=f"dossier:{verification.source_revision_id}",
        risk_partition_id="human-review",
        field_ids=field_ids,
        input_refs=ExtractionInputRefsV1(
            source_revision=ArtifactRefV1(
                object_type="source-revision.v1",
                artifact_hash=_sha(f"source:{verification.source_revision_id}"),
            ),
            material_profile=ArtifactRefV1(
                object_type=MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
                artifact_hash=BINDING_HASH,
            ),
            resolved_template=ArtifactRefV1(
                object_type="resolved-template.v1", artifact_hash=_sha("template")
            ),
            schema_contract=ArtifactRefV1(
                object_type="schema-contract.v1", artifact_hash=SCHEMA_HASH
            ),
            parsed_document=ArtifactRefV1(
                object_type="parsed-document.v1",
                artifact_hash=verification.parsed_document_hash,
            ),
            parse_manifest=ArtifactRefV1(
                object_type="parse-manifest.v1",
                artifact_hash=verification.parse_manifest_hash,
            ),
            parse_quality_decision=ArtifactRefV1(
                object_type="parse-quality-decision.v1",
                artifact_hash=_sha(f"quality:{verification.source_revision_id}"),
            ),
        ),
        budget=budget,
        task_profile=profile,
    )
    attempt = build_initial_attempt(task)
    outcomes = tuple(
        FieldOutcomeV1(
            field_id=item.field_id,
            status="candidate" if item.status == "PASS" else "unknown",
            candidate_ref=(
                ArtifactRefV1(
                    object_type="verified-field-candidate.v1",
                    artifact_hash=item.candidate_snapshot_hash,
                )
                if item.status == "PASS"
                else None
            ),
            reason_code=None if item.status == "PASS" else item.reason_codes[0],
        )
        for item in verification.results
    )
    completed = all(item.status == "PASS" for item in verification.results)
    receipt = build_attempt_receipt(
        attempt,
        field_outcomes=outcomes,
        outcome="completed" if completed else "insufficient",
        reason_code=None if completed else "verification_fields_unresolved",
    )
    return ReceiptChainV1(task=task, task_hash=task.task_hash, receipts=(receipt,))


def _assembly(
    *,
    fact_value_hash_override: str | None = None,
    verification_parse_override: tuple[str, str, str] | None = None,
    evidence_source_revision_override: str | None = None,
    evidence_support_product_version_override: str | None = None,
) -> tuple[CandidateAssemblyV1, tuple[FieldCandidateV1, ...]]:
    candidates = (
        _candidate(
            "field_add",
            revision="revision-add",
            value="new",
            locator_kind="page",
            marker="script>alert(1)</script",
            evidence_source_revision_id=evidence_source_revision_override,
            evidence_support_product_version_id=(
                evidence_support_product_version_override
            ),
        ),
        _candidate(
            "field_enrich",
            revision="revision-enrich-old",
            value="same",
            locator_kind="block",
        ),
        _candidate(
            "field_enrich",
            revision="revision-enrich-new",
            value="same",
            locator_kind="cell",
        ),
        _candidate(
            "field_supersede",
            revision="revision-supersede-old",
            value="old",
            locator_kind="block",
        ),
        _candidate(
            "field_supersede",
            revision="revision-supersede-new",
            value="new",
            locator_kind="table",
        ),
        _candidate(
            "field_conflict",
            revision="revision-conflict-old",
            value="left",
            locator_kind="table",
        ),
        _candidate(
            "field_conflict",
            revision="revision-conflict-new",
            value="right",
            locator_kind="cell",
        ),
        _candidate(
            "field_retract",
            revision="revision-retract-old",
            value="withdrawn",
            locator_kind="page",
        ),
    )
    revisions = (
        "revision-add",
        "revision-enrich-old",
        "revision-enrich-new",
        "revision-supersede-old",
        "revision-supersede-new",
        "revision-conflict-old",
        "revision-conflict-new",
        "revision-retract-old",
    )
    facts = tuple(
        _fact(
            candidate,
            revision,
            supporting_source_revision_ids=(
                tuple(sorted((revision, evidence_source_revision_override)))
                if index == 0 and evidence_source_revision_override is not None
                else None
            ),
        )
        for index, (candidate, revision) in enumerate(
            zip(candidates, revisions, strict=True)
        )
    )
    if fact_value_hash_override is not None:
        facts = (
            facts[0].model_copy(update={"value_hash": fact_value_hash_override}),
            *facts[1:],
        )
    by_revision = dict(zip(revisions, facts, strict=True))

    def change(
        action: Literal["add", "enrich", "supersede", "conflict", "retract"],
        *,
        incoming_revision: str | None,
        prior_revisions: tuple[str, ...] = (),
    ) -> ChangeItemDraftV1:
        incoming = (
            None if incoming_revision is None else by_revision[incoming_revision]
        )
        prior = tuple(by_revision[item] for item in prior_revisions)
        evidence_hashes = (
            ()
            if action == "retract"
            else tuple(
                sorted(
                    {
                        evidence
                        for fact in (*prior, *((incoming,) if incoming else ()))
                        for evidence in fact.evidence_hashes
                    }
                )
            )
        )
        scope = incoming.scope if incoming is not None else prior[0].scope
        return ChangeItemDraftV1(
            action=action,
            scope=scope,
            incoming_fact_hash=None if incoming is None else incoming.fact_hash,
            prior_fact_hashes=tuple(sorted(item.fact_hash for item in prior)),
            evidence_hashes=evidence_hashes,
            retraction_proof_hash=_sha("retraction-proof") if action == "retract" else None,
            reason=f"077 {action} review",
        )

    items = (
        change("add", incoming_revision="revision-add"),
        change(
            "enrich",
            incoming_revision="revision-enrich-new",
            prior_revisions=("revision-enrich-old",),
        ),
        change(
            "supersede",
            incoming_revision="revision-supersede-new",
            prior_revisions=("revision-supersede-old",),
        ),
        change(
            "conflict",
            incoming_revision="revision-conflict-new",
            prior_revisions=("revision-conflict-old",),
        ),
        change(
            "retract",
            incoming_revision=None,
            prior_revisions=("revision-retract-old",),
        ),
    )
    change_set = ChangeSetDraftV1(
        space_id=SPACE_ID,
        product_version_id=PRODUCT_VERSION_ID,
        authority_policy_hash=_sha("authority-policy"),
        input_hash=_sha("incremental-input"),
        items=tuple(sorted(items, key=lambda item: (item.scope.scope_hash, item.item_hash))),
    )
    fact_verifications = tuple(
        _verification(
            candidate,
            revision=revision,
            parse_identity_override=(
                verification_parse_override
                if index == 0
                else None
            ),
        )
        for index, (candidate, revision) in enumerate(
            zip(candidates, revisions, strict=True)
        )
    )
    links = tuple(
        FactVerificationLinkV1(
            fact_hash=fact.fact_hash,
            verification_hash=verification.verification_hash,
            field_id=fact.scope.field_id,
            candidate_snapshot_hash=candidate.candidate_snapshot_hash,
        )
        for candidate, fact, verification in zip(
            candidates, facts, fact_verifications, strict=True
        )
    )
    repair_verification = VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id=PRODUCT_VERSION_ID,
        source_revision_id="revision-repair",
        parse_attempt_id="attempt:revision-repair",
        parsed_document_hash=_sha("document:revision-repair"),
        parse_manifest_hash=_sha("manifest:revision-repair"),
        results=(
            FieldVerificationV1(
                field_id="field_add",
                status="PASS",
                reason_codes=(),
                candidate_snapshot_hash=candidates[0].candidate_snapshot_hash,
            ),
            FieldVerificationV1(
                field_id="field_gap",
                status="FAIL",
                reason_codes=("repair_exhausted",),
                candidate_snapshot_hash=_sha("unresolved-field-gap"),
            ),
        ),
    )
    repair = RepairResolutionV1(
        contract="targeted-repair-resolution.v1",
        parent_verification_hash=repair_verification.verification_hash,
        repair_plan_hash=_sha("repair-plan"),
        results=repair_verification.results,
        gaps=(GapV1(field_id="field_gap", reason_codes=("repair_exhausted",)),),
        review_items=(
            EvidenceReviewItemV1(
                field_id="field_gap",
                reason_code="repair_exhausted",
                parent_verification_hash=repair_verification.verification_hash,
            ),
        ),
    )
    verifications = (*fact_verifications, repair_verification)
    assembled = build_fixture_candidate_batch(
        change_set=change_set,
        facts=facts,
        verification_batches=verifications,
        receipt_chains=tuple(_receipt_chain(item) for item in verifications),
        fact_verification_links=links,
        repair_resolutions=(repair,),
        review_policy=HumanBatchPolicyV1(
            policy_id="human-batch-077",
            high_risk_field_ids=("field_add",),
        ),
    )
    return assembled, candidates


def test_review_dossier_modules_expose_display_only_boundary() -> None:
    assert DISPLAY_AUTHORITY == "DISPLAY_ONLY_REQUIRES_NAMED_HUMAN"
    assert issubclass(ReviewDossierError, ValueError)
    assert callable(build_review_dossier)
    assert callable(dossier_json_bytes)
    assert callable(render_review_dossier_html)


def test_complete_candidate_dossier_preserves_every_neutral_review_category() -> None:
    assembly, candidates = _assembly()

    dossier = build_review_dossier(
        assembly=assembly,
        field_candidates=candidates,
    )

    assert dossier.authority == DISPLAY_AUTHORITY
    assert dossier.upstream_authority == "NONE_REQUIRES_NAMED_HUMAN"
    assert dossier.candidate_hash == assembly.candidate.candidate_hash
    assert dossier.human_batch_hash == assembly.human_batch.batch_hash
    assert dossier.policy_hash == assembly.human_batch.review_policy.policy_hash
    assert dossier.counts.model_dump() == {
        "add": 1,
        "update": 2,
        "conflict": 1,
        "retract": 1,
        "high_risk": 1,
        "repair": 1,
        "gap": 1,
    }
    assert tuple(change.raw_action for change in dossier.changes) == (
        "add",
        "conflict",
        "enrich",
        "retract",
        "supersede",
    )
    assert tuple(change.category for change in dossier.changes) == (
        "add",
        "conflict",
        "update",
        "retract",
        "update",
    )
    conflict = next(change for change in dossier.changes if change.category == "conflict")
    assert conflict.incoming_fact is not None
    assert len(conflict.prior_facts) == 1
    retract = next(change for change in dossier.changes if change.category == "retract")
    assert retract.incoming_fact is None
    assert retract.retraction_proof_hash == _sha("retraction-proof")
    assert len(retract.prior_facts) == 1
    displayed_candidates = tuple(
        fact.field_candidate
        for change in dossier.changes
        for fact in (
            *change.prior_facts,
            *((change.incoming_fact,) if change.incoming_fact else ()),
        )
    )
    assert {item.candidate_snapshot_hash for item in displayed_candidates} == {
        item.candidate_snapshot_hash for item in candidates
    }
    assert all(
        fact.verification_result.status == "PASS"
        and fact.verification_result.candidate_snapshot_hash
        == fact.candidate_snapshot_hash
        for change in dossier.changes
        for fact in (
            *change.prior_facts,
            *((change.incoming_fact,) if change.incoming_fact else ()),
        )
    )
    assert {
        evidence.locator.subject_type
        for item in displayed_candidates
        for evidence in item.evidence
    } == {"page", "block", "table", "cell"}


def test_dossier_json_is_canonical_and_input_order_independent() -> None:
    assembly, candidates = _assembly()

    forward = build_review_dossier(assembly=assembly, field_candidates=candidates)
    reverse = build_review_dossier(
        assembly=assembly,
        field_candidates=tuple(reversed(candidates)),
    )

    assert forward == reverse
    assert forward.dossier_hash == reverse.dossier_hash
    assert dossier_json_bytes(forward) == dossier_json_bytes(reverse)
    assert hashlib.sha256(dossier_json_bytes(forward)).hexdigest() == _sha(
        dossier_json_bytes(forward).decode("utf-8")
    )


def test_static_html_escapes_content_and_exposes_no_decision_control() -> None:
    assembly, candidates = _assembly()
    dossier = build_review_dossier(assembly=assembly, field_candidates=candidates)

    rendered = render_review_dossier_html(dossier)
    lowered = rendered.lower()

    assert assembly.candidate.candidate_hash in rendered
    assert "DISPLAY_ONLY_REQUIRES_NAMED_HUMAN" in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<script" not in lowered
    assert "<form" not in lowered
    assert "<input" not in lowered
    assert "<button" not in lowered
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "winner" not in lowered
    assert "default choice" not in lowered


def test_static_html_projects_the_same_locator_and_repair_custody_as_json() -> None:
    assembly, candidates = _assembly()
    dossier = build_review_dossier(assembly=assembly, field_candidates=candidates)
    payload = dossier.model_dump(mode="json")
    json_text = dossier_json_bytes(dossier).decode("utf-8")

    rendered = render_review_dossier_html(dossier)

    def assert_in_both(value: str) -> None:
        assert value in json_text
        assert value in rendered

    for change in payload["changes"]:
        facts = [*change["prior_facts"]]
        if change["incoming_fact"] is not None:
            facts.append(change["incoming_fact"])
        for fact in facts:
            assert_in_both(fact["verification_hash"])
            assert_in_both(fact["verification_result"]["status"])
            for evidence in fact["field_candidate"]["evidence"]:
                for key in (
                    "parse_attempt_id",
                    "parsed_document_hash",
                    "parse_manifest_hash",
                    "quote_snapshot_sha256",
                    "value_snapshot_sha256",
                ):
                    assert_in_both(evidence[key])
                assert_in_both(evidence["locator"]["content_snapshot_sha256"])
                assert_in_both(evidence["support_scope"]["product_version_id"])
                assert_in_both(evidence["support_scope"]["subject_id"])
                for condition in evidence["support_scope"]["condition_ids"]:
                    assert_in_both(condition)
    for resolution in payload["repair_resolutions"]:
        assert_in_both(resolution["parent_verification_hash"])
        assert_in_both(resolution["repair_plan_hash"])
        for result in resolution["results"]:
            assert_in_both(result["status"])
            for reason in result["reason_codes"]:
                assert_in_both(reason)
        for gap in resolution["gaps"]:
            for reason in gap["reason_codes"]:
                assert_in_both(reason)


def test_fully_recomputed_059_fact_value_cannot_contradict_original_candidate() -> None:
    assembly, candidates = _assembly(fact_value_hash_override="f" * 64)

    with pytest.raises(ReviewDossierError, match="field_candidate_value_mismatch"):
        build_review_dossier(assembly=assembly, field_candidates=candidates)


@pytest.mark.parametrize(
    "parse_identity_override",
    (
        ("attempt:foreign", _sha("document:revision-add"), _sha("manifest:revision-add")),
        ("attempt:revision-add", _sha("document:foreign"), _sha("manifest:revision-add")),
        ("attempt:revision-add", _sha("document:revision-add"), _sha("manifest:foreign")),
    ),
)
def test_fully_recomputed_059_verification_cannot_foreignize_evidence_parse_identity(
    parse_identity_override: tuple[str, str, str],
) -> None:
    assembly, candidates = _assembly(
        verification_parse_override=parse_identity_override
    )

    with pytest.raises(ReviewDossierError, match="field_candidate_parse_identity_mismatch"):
        build_review_dossier(assembly=assembly, field_candidates=candidates)


def test_fully_recomputed_059_evidence_source_must_equal_linked_verification_source() -> None:
    assembly, candidates = _assembly(
        evidence_source_revision_override="revision-foreign"
    )

    with pytest.raises(ReviewDossierError, match="field_candidate_source_revision_mismatch"):
        build_review_dossier(assembly=assembly, field_candidates=candidates)


def test_fully_recomputed_059_evidence_support_product_must_equal_fact_scope() -> None:
    assembly, candidates = _assembly(
        evidence_support_product_version_override="foreign-product-version"
    )

    with pytest.raises(ReviewDossierError, match="field_candidate_support_scope_mismatch"):
        build_review_dossier(assembly=assembly, field_candidates=candidates)


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        ("missing", "field_candidate_membership_mismatch"),
        ("duplicate", "field_candidate_duplicate"),
        ("orphan", "field_candidate_membership_mismatch"),
        ("foreign_snapshot", "field_candidate_membership_mismatch"),
    ),
)
def test_field_candidate_locator_custody_fails_closed(
    mutation: str,
    reason_code: str,
) -> None:
    assembly, candidates = _assembly()
    supplied = candidates
    if mutation == "missing":
        supplied = candidates[:-1]
    elif mutation == "duplicate":
        supplied = (*candidates, candidates[0])
    elif mutation == "orphan":
        supplied = (
            *candidates,
            _candidate(
                "field_orphan",
                revision="revision-orphan",
                value="orphan",
                locator_kind="page",
            ),
        )
    else:
        supplied = (
            candidates[0].model_copy(
                update={"value": CandidateValueV1(kind="enum", enum_value="foreign")}
            ),
            *candidates[1:],
        )

    with pytest.raises(ReviewDossierError, match=reason_code) as caught:
        build_review_dossier(assembly=assembly, field_candidates=supplied)

    assert caught.value.reason_code == reason_code


def test_model_construct_cannot_bypass_candidate_batch_binding() -> None:
    assembly, candidates = _assembly()
    forged = CandidateAssemblyV1.model_construct(
        candidate=assembly.candidate,
        human_batch=assembly.human_batch.model_copy(
            update={"candidate_hash": "0" * 64}
        ),
    )

    with pytest.raises(ReviewDossierError, match="candidate_assembly_invalid"):
        build_review_dossier(assembly=forged, field_candidates=candidates)


@pytest.mark.parametrize("mutation", ("fact", "repair_parent"))
def test_nested_upstream_hash_mutations_fail_before_output(mutation: str) -> None:
    assembly, candidates = _assembly()
    candidate_payload = {
        name: getattr(assembly.candidate, name)
        for name in type(assembly.candidate).model_fields
    }
    if mutation == "fact":
        index, original = next(
            (index, change)
            for index, change in enumerate(assembly.candidate.changes)
            if change.incoming_fact is not None
        )
        assert original.incoming_fact is not None
        forged_fact = original.incoming_fact.model_copy(update={"value_hash": "f" * 64})
        forged_change = type(original).model_construct(
            item=original.item,
            incoming_fact=forged_fact,
            prior_facts=original.prior_facts,
        )
        candidate_payload["changes"] = tuple(
            forged_change if item_index == index else change
            for item_index, change in enumerate(assembly.candidate.changes)
        )
    else:
        original_repair = assembly.candidate.repair_resolutions[0]
        candidate_payload["repair_resolutions"] = (
            original_repair.model_copy(update={"parent_verification_hash": "f" * 64}),
        )
    forged_candidate = type(assembly.candidate).model_construct(**candidate_payload)
    forged = CandidateAssemblyV1.model_construct(
        candidate=forged_candidate,
        human_batch=assembly.human_batch,
    )

    with pytest.raises(ReviewDossierError, match="candidate_assembly_invalid"):
        build_review_dossier(assembly=forged, field_candidates=candidates)


def test_dossier_modules_are_pure_and_contain_no_approval_or_persistence_api() -> None:
    module_paths = (
        ROOT / "src/insurance_harness/knowledge_compiler/review_dossier.py",
        ROOT / "src/insurance_harness/knowledge_compiler/review_dossier_html.py",
    )
    forbidden_import_roots = {"os", "pathlib", "requests", "sqlalchemy", "subprocess"}
    forbidden_calls = {"open", "write", "write_bytes", "write_text", "commit", "execute"}
    forbidden_definitions = {"approve", "reject", "select", "persist", "save"}

    for module_path in module_paths:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        } | {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        definitions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not (imports & forbidden_import_roots)
        assert not (calls & forbidden_calls)
        assert not (definitions & forbidden_definitions)
        assert "ReviewDecision" not in source
        assert "PublishAuthorization" not in source
