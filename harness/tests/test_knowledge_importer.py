"""K2：pred JSONL → Claim 导入器（specs/mainchain.md）。"""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.compiler.models import PredRecord
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.goldenset.records import Evidence
from insurance_harness.knowledge import (
    MergePolicy,
    import_pred_jsonl,
    import_pred_records,
)
from insurance_harness.knowledge.importer import to_proposed_claim
from insurance_harness.knowledge.models import (
    ProposedEvidence,
    SourceImportContext,
    SourceImportIdentity,
)
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ReviewItem,
)
from tests.kbhelpers import BROCHURE, TERMS, pred, seed_bound_scope, seed_product


def _count(session: Session, table: type) -> int:
    return session.execute(select(func.count()).select_from(table)).scalar_one()


def _scope(session: Session) -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id="tenant-importer",
        raw_kb_id="raw-importer",
        wiki_kb_id="wiki-importer",
    )


def _source_identity(
    *,
    knowledge_id: str,
    raw_kb_id: str = "raw-importer",
    revision_char: str = "a",
) -> dict[str, str]:
    return {
        "knowledge_id": knowledge_id,
        "raw_kb_id": raw_kb_id,
        "source_revision": revision_char * 64,
        "file_hash": revision_char * 32,
        "original_digest": revision_char * 64,
        "parser_version": "pdfplumber@0.11:text-v1",
    }


def _source_context(
    scope: KnowledgeScope,
    documents: dict[str, dict[str, str]],
) -> dict[str, object]:
    return {
        "space_id": scope.space_id,
        "tenant_id": scope.tenant_id,
        "raw_kb_id": scope.raw_kb_id,
        "documents": documents,
    }


def _source_pred(
    field_id: str,
    *,
    doc: str,
    identity: dict[str, str],
    value: str | None = "90天",
    tri_state: str = "present",
) -> PredRecord:
    record = pred(
        field_id,
        value=value,
        tri_state=tri_state,  # type: ignore[arg-type]
        doc=doc,
        quote=None if tri_state == "unknown" else f"{field_id}原文",
    )
    if tri_state == "unknown":
        return record
    return record.model_copy(
        update={
            "evidence": [
                Evidence(
                    page=3,
                    quote=f"{field_id}原文",
                    **identity,
                    chunk_id=f"chunk-{field_id}",
                    chunk_hash="d" * 64,
                    lineage_status="linked",
                )
            ]
        }
    )


def test_k2_1_import_binds_product_and_evidence(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    records = [
        pred("waiting_period", value="90天", doc=BROCHURE, page=3, quote="等待期为90天"),
        pred(
            "grace_period", value="60天", doc=TERMS, page=8, quote="宽限期60日",
            confidence="medium",
        ),
    ]
    report = import_pred_records(
        kb_session,
        records,
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        legacy_replay=True,
    )
    assert report.imported == 2 and report.change_set_id

    claims = kb_session.execute(select(Claim)).scalars().all()
    assert {c.product_version_id for c in claims} == {version.id}
    by_pred = {c.predicate: c for c in claims}
    assert by_pred["waiting_period"].confidence == 0.9  # high → 0.9
    assert by_pred["grace_period"].confidence == 0.6  # medium → 0.6

    evidence = kb_session.execute(select(ClaimEvidence)).scalars().all()
    by_claim = {e.claim_id: e for e in evidence}
    brochure_ev = by_claim[by_pred["waiting_period"].id]
    assert brochure_ev.page == 3 and brochure_ev.quote == "等待期为90天"
    assert brochure_ev.doc_role == "official_desc" and brochure_ev.authority_level == 2
    terms_ev = by_claim[by_pred["grace_period"].id]
    assert terms_ev.doc_role == "terms" and terms_ev.authority_level == 1  # 03 §6.1 映射


def test_k2_1_pending_judge_preserved_and_never_auto(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    report = import_pred_records(
        kb_session,
        [pred("hesitation_period", value="15天", quote="犹豫期15天", pending_judge=True)],
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        policy=MergePolicy(auto_apply_add=True),  # 即便放开自动，也不许通过
        legacy_replay=True,
    )
    claim = kb_session.execute(select(Claim)).scalar_one()
    assert claim.pending_judge is True
    assert claim.status == "candidate"  # 未被自动发布
    assert report.merge.review_keys  # 走审核


def test_k2_2_unknown_becomes_draft_placeholder(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    report = import_pred_records(
        kb_session,
        [pred("premium_waiver", value=None, tri_state="unknown")],
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        legacy_replay=True,
    )
    assert report.unknown_placeholders == 1
    claim = kb_session.execute(select(Claim)).scalar_one()
    assert claim.status == "draft" and claim.value_state == "unknown"
    assert _count(kb_session, ReviewItem) == 0  # 不产生审核项


def test_k2_3_batch_idempotent(kb_session: Session, tmp_path: Path) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    lines = [
        pred("waiting_period", value="90天", quote="等待期为90天").model_dump_json(),
        pred("grace_period", value="60天", quote="宽限期60日").model_dump_json(),
    ]
    path = tmp_path / "pred.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    first = import_pred_jsonl(
        kb_session,
        path,
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        legacy_replay=True,
    )
    assert first.imported == 2
    claims_before = _count(kb_session, Claim)
    items_before = _count(kb_session, ChangeItem)
    evidence_before = _count(kb_session, ClaimEvidence)

    second = import_pred_jsonl(
        kb_session,
        path,
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        legacy_replay=True,
    )
    assert second.duplicate_batch is True
    assert second.change_set_id == first.change_set_id  # 批级幂等键命中
    assert _count(kb_session, Claim) == claims_before
    assert _count(kb_session, ChangeItem) == items_before
    assert _count(kb_session, ClaimEvidence) == evidence_before


def test_k2_3_record_level_idempotent(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    records = [pred("waiting_period", value="90天", quote="等待期为90天")]
    import_pred_records(
        kb_session,
        records,
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        source_revision="r1",
        legacy_replay=True,
    )
    # 批内容相同但 source_revision 不同 → 新 ChangeSet，但记录级幂等键拦截
    report = import_pred_records(
        kb_session,
        records,
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        source_revision="r2",
        legacy_replay=True,
    )
    assert report.duplicate_batch is False
    assert report.imported == 0 and report.skipped_duplicates == 1
    assert _count(kb_session, Claim) == 1
    assert _count(kb_session, ChangeSet) == 2  # 变更集本身留痕


def test_k2_4_present_without_evidence_rejected(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    report = import_pred_records(
        kb_session,
        [pred("waiting_period", value="90天", quote=None)],
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        legacy_replay=True,
    )
    assert report.imported == 0 and report.skipped_no_evidence == 1
    assert _count(kb_session, Claim) == 0


def test_t6_proposed_evidence_exposes_complete_source_audit_contract() -> None:
    assert {
        "raw_kb_id",
        "source_revision",
        "file_hash",
        "original_digest",
        "parser_version",
        "chunk_hash",
        "lineage_status",
        "stale_at",
    } <= set(ProposedEvidence.model_fields)


def test_t6_to_proposed_claim_preserves_source_aware_evidence(
    kb_session: Session,
) -> None:
    scope_raw_kb_id = "raw-importer"
    scope = _scope(kb_session)
    record = pred("waiting_period", value="90天", quote="等待期为90天")
    record = record.model_copy(
        update={
            "evidence": [
                Evidence(
                    page=3,
                    quote="等待期为90天",
                    knowledge_id="knowledge-1",
                    raw_kb_id=scope_raw_kb_id,
                    source_revision="a" * 64,
                    file_hash="b" * 32,
                    original_digest="c" * 64,
                    parser_version="pdfplumber@0.11:text-v1",
                    chunk_id="chunk-1",
                    chunk_hash="d" * 64,
                    lineage_status="linked",
                )
            ]
        }
    )

    proposal = to_proposed_claim(
        record,
        scope=scope,
        product_version_id="version-1",
        knowledge_id="knowledge-1",
        doc_role="terms",
        doc_title=record.doc,
    )

    assert proposal.evidence[0].model_dump(mode="json") == {
        "knowledge_id": "knowledge-1",
        "doc_title": record.doc,
        "chunk_id": "chunk-1",
        "quote": "等待期为90天",
        "page": 3,
        "doc_role": "terms",
        "authority_level": 1,
        "extraction_method": "llm",
        "raw_kb_id": scope_raw_kb_id,
        "source_revision": "a" * 64,
        "file_hash": "b" * 32,
        "original_digest": "c" * 64,
        "parser_version": "pdfplumber@0.11:text-v1",
        "chunk_hash": "d" * 64,
        "lineage_status": "linked",
        "stale_at": None,
    }


def test_t6_import_defaults_to_source_aware_and_rejects_legacy_fallback(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)

    with pytest.raises((ScopeViolation, ValueError), match="source|legacy"):
        import_pred_records(
            kb_session,
            [pred("waiting_period", value="90天", quote="等待期为90天")],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
        )


def test_t6_legacy_replay_requires_explicit_flag(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)

    report = import_pred_records(
        kb_session,
        [pred("waiting_period", value="90天", quote="等待期为90天")],
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        legacy_replay=True,
    )

    assert report.imported == 1


def test_t6_source_aware_import_partitions_multiple_documents_losslessly(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    a = _source_identity(knowledge_id="knowledge-a", revision_char="a")
    b = _source_identity(knowledge_id="knowledge-b", revision_char="b")
    records = [
        _source_pred("waiting_period", doc="a.pdf", identity=a),
        _source_pred("grace_period", doc="b.pdf", identity=b, value="60天"),
    ]

    report = import_pred_records(
        kb_session,
        records,
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        source_context=_source_context(scope, {"a.pdf": a, "b.pdf": b}),
    )

    assert report.imported == 2
    assert report.change_set_id is None
    assert len(report.partitions) == 2
    assert {
        (part.knowledge_id, part.source_revision, part.source_kind)
        for part in report.partitions
    } == {
        ("knowledge-a", "a" * 64, "document"),
        ("knowledge-b", "b" * 64, "document"),
    }
    change_sets = kb_session.execute(select(ChangeSet)).scalars().all()
    assert {(row.external_record_id, row.source_revision) for row in change_sets} == {
        ("knowledge-a", "a" * 64),
        ("knowledge-b", "b" * 64),
    }
    evidence = kb_session.execute(select(ClaimEvidence)).scalars().all()
    assert {(row.knowledge_id, row.source_revision, row.chunk_hash) for row in evidence} == {
        ("knowledge-a", "a" * 64, "d" * 64),
        ("knowledge-b", "b" * 64, "d" * 64),
    }
    assert all(row.stale_at is None for row in evidence)


def test_t6_multi_partition_failure_rolls_back_every_import_side_effect(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    first = _source_identity(knowledge_id="knowledge-a", revision_char="a")
    blocked = _source_identity(knowledge_id="knowledge-z", revision_char="b")
    interrupted = ChangeSet(
        space_id=scope.space_id,
        source_kind="recompile",
        knowledge_ids=["knowledge-z"],
        external_record_id="knowledge-z",
        source_revision="b" * 64,
        status="pending",
        created_by="test",
    )
    kb_session.add(interrupted)
    kb_session.flush()
    kb_session.add(
        ChangeItem(
            change_set_id=interrupted.id,
            action="add",
            proposed={"interrupted": True},
            decision="needs_review",
        )
    )
    kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="source change set cannot be replayed"):
        import_pred_records(
            kb_session,
            [
                _source_pred("waiting_period", doc="a.pdf", identity=first),
                _source_pred("grace_period", doc="z.pdf", identity=blocked),
            ],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(
                scope,
                {"a.pdf": first, "z.pdf": blocked},
            ),
            policy=MergePolicy(auto_apply_add=True),
        )

    kb_session.commit()
    assert {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    } == baseline


def test_t6_source_aware_unknown_uses_trusted_doc_context(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id="knowledge-unknown")

    report = import_pred_records(
        kb_session,
        [_source_pred("premium_waiver", doc="unknown.pdf", identity=identity, value=None,
                      tri_state="unknown")],
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        source_context=_source_context(scope, {"unknown.pdf": identity}),
    )

    assert report.unknown_placeholders == 1
    assert len(report.partitions) == 1
    assert report.partitions[0].knowledge_id == "knowledge-unknown"
    assert report.partitions[0].source_revision == "a" * 64


@pytest.mark.parametrize(
    "bad_context",
    [
        None,
        {"space_id": "wrong", "tenant_id": "tenant-importer", "raw_kb_id": "raw-importer",
         "documents": {}},
        {"space_id": "placeholder", "tenant_id": "tenant-importer",
         "raw_kb_id": "wrong-kb", "documents": {}},
    ],
)
def test_t6_source_aware_unknown_never_guesses_from_filename(
    kb_session: Session,
    bad_context: dict[str, object] | None,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)

    with pytest.raises((ScopeViolation, ValueError), match="scope|source|legacy|document"):
        import_pred_records(
            kb_session,
            [pred("premium_waiver", value=None, tri_state="unknown", doc="unknown.pdf")],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=bad_context,
        )


def test_t6_source_aware_rejects_partial_mixed_and_doc_mismatched_audit(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    a = _source_identity(knowledge_id="knowledge-a", revision_char="a")
    b = _source_identity(knowledge_id="knowledge-b", revision_char="b")
    partial = Evidence.model_construct(
        page=1,
        quote="partial",
        knowledge_id="knowledge-a",
        raw_kb_id=scope.raw_kb_id,
        lineage_status="page_only",
    )
    partial_record = pred("waiting_period", value="90天", quote="partial").model_copy(
        update={"evidence": [partial]}
    )
    mixed_record = _source_pred("grace_period", doc="a.pdf", identity=a)
    mixed_record = mixed_record.model_copy(
        update={
            "evidence": [
                mixed_record.evidence[0],
                Evidence(
                    page=4,
                    quote="mixed",
                    **b,
                    chunk_id="chunk-b",
                    chunk_hash="e" * 64,
                    lineage_status="linked",
                ),
            ]
        }
    )

    for record, context in (
        (partial_record, _source_context(scope, {partial_record.doc: a})),
        (mixed_record, _source_context(scope, {"a.pdf": a})),
        (_source_pred("hesitation_period", doc="a.pdf", identity=a),
         _source_context(scope, {"a.pdf": b})),
    ):
        with pytest.raises((ScopeViolation, ValueError), match="source|identity|lineage"):
            import_pred_records(
                kb_session,
                [record],
                scope=scope,
                product_id="AXB001",
                product_version_id=version.id,
                source_context=context,
            )


def test_t6_production_rejects_legacy_identity_arguments(kb_session: Session) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id="knowledge-a")
    record = _source_pred("waiting_period", doc="a.pdf", identity=identity)

    with pytest.raises((ScopeViolation, ValueError), match="legacy|source"):
        import_pred_records(
            kb_session,
            [record],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(scope, {"a.pdf": identity}),
            knowledge_ids={"a.pdf": "knowledge-a"},
            source_revision="legacy-revision",
        )


@pytest.mark.parametrize("source_kind", ["recompile", "document"])
def test_t6_source_aware_import_resumes_empty_pending_changeset(
    kb_session: Session,
    source_kind: str,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id="knowledge-a")
    pending = ChangeSet(
        space_id=scope.space_id,
        source_kind=source_kind,
        knowledge_ids=["knowledge-a"],
        external_record_id="knowledge-a",
        source_revision="a" * 64,
        status="pending",
        created_by="source-change" if source_kind == "recompile" else "interrupted-import",
    )
    kb_session.add(pending)
    kb_session.flush()

    report = import_pred_records(
        kb_session,
        [_source_pred("waiting_period", doc="a.pdf", identity=identity)],
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        source_context=_source_context(scope, {"a.pdf": identity}),
    )

    assert report.change_set_id == pending.id
    assert report.partitions[0].source_kind == source_kind
    assert _count(kb_session, ChangeSet) == 1
    assert _count(kb_session, ChangeItem) == 1


def test_t6_source_aware_import_rejects_ambiguous_or_partially_used_changeset(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id="knowledge-a")
    rows = [
        ChangeSet(
            space_id=scope.space_id,
            source_kind=kind,
            knowledge_ids=["knowledge-a"],
            external_record_id="knowledge-a",
            source_revision="a" * 64,
            status="pending",
            created_by="test",
        )
        for kind in ("document", "recompile")
    ]
    kb_session.add_all(rows)
    kb_session.flush()

    with pytest.raises((ScopeViolation, ValueError), match="ambiguous|source|change"):
        import_pred_records(
            kb_session,
            [_source_pred("waiting_period", doc="a.pdf", identity=identity)],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(scope, {"a.pdf": identity}),
        )


def test_t6_source_aware_import_rejects_pending_changeset_with_items(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id="knowledge-a")
    pending = ChangeSet(
        space_id=scope.space_id,
        source_kind="recompile",
        knowledge_ids=["knowledge-a"],
        external_record_id="knowledge-a",
        source_revision="a" * 64,
        status="pending",
        created_by="test",
    )
    kb_session.add(pending)
    kb_session.flush()
    kb_session.add(
        ChangeItem(
            change_set_id=pending.id,
            action="add",
            proposed={"interrupted": True},
            decision="needs_review",
        )
    )
    kb_session.flush()

    with pytest.raises((ScopeViolation, ValueError), match="pending|change|replay"):
        import_pred_records(
            kb_session,
            [_source_pred("waiting_period", doc="a.pdf", identity=identity)],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(scope, {"a.pdf": identity}),
        )


def test_t6_applied_identical_revision_is_duplicate_with_zero_items(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id="knowledge-a")
    applied = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=["knowledge-a"],
        external_record_id="knowledge-a",
        source_revision="a" * 64,
        status="applied",
        created_by="previous-import",
    )
    kb_session.add(applied)
    kb_session.flush()

    report = import_pred_records(
        kb_session,
        [_source_pred("waiting_period", doc="a.pdf", identity=identity)],
        scope=scope,
        product_id="AXB001",
        product_version_id=version.id,
        source_context=_source_context(scope, {"a.pdf": identity}),
    )

    assert report.duplicate_batch is True
    assert report.change_set_id == applied.id
    assert report.imported == 0
    assert _count(kb_session, ChangeItem) == 0


def test_t6_same_partition_key_with_conflicting_source_audit_fails_closed(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    a = _source_identity(knowledge_id="knowledge-a", revision_char="a")
    conflicting = {
        **a,
        "file_hash": "b" * 32,
        "original_digest": "c" * 64,
        "parser_version": "different-parser",
    }

    with pytest.raises((ScopeViolation, ValueError), match="source|identity|partition"):
        import_pred_records(
            kb_session,
            [
                _source_pred("waiting_period", doc="a.pdf", identity=a),
                _source_pred("grace_period", doc="b.pdf", identity=conflicting),
            ],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(
                scope, {"a.pdf": a, "b.pdf": conflicting}
            ),
        )


def test_t6_source_context_documents_are_deeply_immutable() -> None:
    from insurance_harness.knowledge import SourceImportContext

    context = SourceImportContext.model_validate(
        {
            "space_id": "space-1",
            "tenant_id": "tenant-1",
            "raw_kb_id": "raw-importer",
            "documents": {
                "a.pdf": _source_identity(knowledge_id="knowledge-a")
            },
        }
    )

    with pytest.raises(TypeError):
        context.documents["b.pdf"] = context.documents["a.pdf"]  # type: ignore[index]


def test_t6_enrich_dedupe_keeps_same_quote_from_new_source_revision(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    first_identity = _source_identity(knowledge_id="knowledge-a", revision_char="a")
    second_identity = _source_identity(knowledge_id="knowledge-a", revision_char="b")
    policy = MergePolicy(auto_apply_add=True, auto_apply_enrich=True)

    for identity in (first_identity, second_identity):
        import_pred_records(
            kb_session,
            [_source_pred("waiting_period", doc="a.pdf", identity=identity)],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(scope, {"a.pdf": identity}),
            policy=policy,
        )

    rows = kb_session.execute(select(ClaimEvidence)).scalars().all()
    assert {row.source_revision for row in rows} == {"a" * 64, "b" * 64}
    assert len(rows) == 2


def test_t6_source_aware_rejects_filename_as_knowledge_placeholder(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id="policy.pdf")

    with pytest.raises((ScopeViolation, ValueError), match="placeholder|source|identity"):
        import_pred_records(
            kb_session,
            [_source_pred("waiting_period", doc="policy.pdf", identity=identity)],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(scope, {"policy.pdf": identity}),
        )


@pytest.mark.parametrize(
    "placeholder",
    [
        "renamed-policy.pdf",
        "archive/policy.pdf",
        r"archive\policy.pdf",
    ],
)
def test_t6_source_aware_rejects_any_filename_or_path_shaped_knowledge_placeholder(
    kb_session: Session,
    placeholder: str,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id=placeholder)

    with pytest.raises((ScopeViolation, ValueError), match="placeholder|source|identity"):
        import_pred_records(
            kb_session,
            [_source_pred("waiting_period", doc="policy.pdf", identity=identity)],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(scope, {"policy.pdf": identity}),
        )


@pytest.mark.parametrize(
    "unsafe_knowledge_id",
    [
        "knowledge\ncontrol",
        "knowledge|page",
        "knowledge?admin=true",
        "knowledge#fragment",
        "knowledge%2Fpath",
        "k" * 129,
    ],
)
def test_t6_source_aware_rejects_knowledge_id_outside_weknora_contract(
    kb_session: Session,
    unsafe_knowledge_id: str,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    identity = _source_identity(knowledge_id=unsafe_knowledge_id)

    with pytest.raises((ScopeViolation, ValueError), match="source|identity|context"):
        import_pred_records(
            kb_session,
            [_source_pred("waiting_period", doc="policy.pdf", identity=identity)],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=_source_context(scope, {"policy.pdf": identity}),
        )


def test_t6_source_context_revalidates_constructed_identity_at_import_boundary(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    raw_identity = _source_identity(knowledge_id="knowledge|forged")
    identity = SourceImportIdentity.model_construct(
        knowledge_id=raw_identity["knowledge_id"],
        raw_kb_id=raw_identity["raw_kb_id"],
        source_revision=raw_identity["source_revision"],
        file_hash=raw_identity["file_hash"],
        original_digest=raw_identity["original_digest"],
        parser_version=raw_identity["parser_version"],
    )
    context = SourceImportContext.model_construct(
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        documents={"policy.pdf": identity},
    )

    with pytest.raises((ScopeViolation, ValueError), match="source context mismatch"):
        import_pred_records(
            kb_session,
            [_source_pred("waiting_period", doc="policy.pdf", identity=raw_identity)],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=context,
        )


def test_t6_source_context_revalidates_nested_constructed_identity_in_raw_dict(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    _, version = seed_product(kb_session, scope=scope)
    raw_identity = _source_identity(knowledge_id="bad|id")
    identity = SourceImportIdentity.model_construct(
        knowledge_id=raw_identity["knowledge_id"],
        raw_kb_id=raw_identity["raw_kb_id"],
        source_revision=raw_identity["source_revision"],
        file_hash=raw_identity["file_hash"],
        original_digest=raw_identity["original_digest"],
        parser_version=raw_identity["parser_version"],
    )
    raw_context: dict[str, object] = {
        "space_id": scope.space_id,
        "tenant_id": scope.tenant_id,
        "raw_kb_id": scope.raw_kb_id,
        "documents": {"policy.pdf": identity},
    }

    with pytest.raises((ScopeViolation, ValueError), match="source context mismatch"):
        import_pred_records(
            kb_session,
            [_source_pred("waiting_period", doc="policy.pdf", identity=raw_identity)],
            scope=scope,
            product_id="AXB001",
            product_version_id=version.id,
            source_context=raw_context,
        )
