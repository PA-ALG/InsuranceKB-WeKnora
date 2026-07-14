"""K5.1/K5.2：页面编译（分组渲染 + 证据角标 + 发布契约字段）。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge import (
    MergeEngine,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    build_page_claims,
    product_page_slug,
    render_product_page,
)
from insurance_harness.knowledge.tables import ClaimEvidence
from tests.kbhelpers import green_gate, seed_bound_scope, seed_product


def _scope(session: Session) -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id="tenant-pages",
        raw_kb_id="raw-pages",
        wiki_kb_id="wiki-pages",
    )


def _prop(
    scope: KnowledgeScope,
    version_id: str,
    predicate: str,
    field_name: str,
    value: str | None,
    *,
    value_state: str = "present",
    knowledge_id: str = "k-brochure",
    doc_title: str = "产品说明书",
    page: int = 3,
    quote: str = "原文引文",
    chunk_id: str | None = None,
) -> ProposedClaim:
    return ProposedClaim(
        space_id=scope.space_id,
        product_version_id=version_id,
        predicate=predicate,
        field_name=field_name,
        value_state=value_state,  # type: ignore[arg-type]
        value=value,
        confidence=0.9,
        evidence=[
            ProposedEvidence(
                knowledge_id=knowledge_id, doc_title=doc_title, chunk_id=chunk_id,
                quote=quote, page=page, doc_role="official_desc", authority_level=2,
            )
        ],
    )


def _publish_all(
    session: Session,
    scope: KnowledgeScope,
    version_id: str,
    props: list[ProposedClaim],
) -> None:
    gate, fp = green_gate([p.predicate for p in props])
    engine = MergeEngine(
        session,
        scope=scope,
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=gate,
        run_fingerprint=fp,
    )
    change_set, _ = engine.open_change_set(source_kind="document")
    engine.apply_batch(change_set, props)


def test_k5_1_grouped_render_with_evidence_footnotes(kb_session: Session) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_all(
        kb_session,
        scope,
        version.id,
        [
            _prop(
                scope,
                version.id, "waiting_period", "等待期", "90天",
                quote="等待期为90天", chunk_id="c-1",
            ),
            _prop(
                scope,
                version.id, "death_benefit", "身故保险金", "已交保费与现金价值较大者",
                quote="身故给付……", page=5, chunk_id="c-2",
            ),
            _prop(
                scope,
                version.id, "premium_waiver", "投被保人豁免", None,
                value_state="absent_explicitly", quote="本产品无豁免责任", page=7,
            ),
        ],
    )
    views = build_page_claims(
        kb_session,
        scope,
        version.id,
        doc_titles={"k-brochure": "产品说明书"},
        field_names={
            "waiting_period": "等待期",
            "death_benefit": "身故保险金",
            "premium_waiver": "投被保人豁免",
        },
        legacy_replay=True,
    )
    page = render_product_page(
        views,
        product_code=product.product_code,
        version_label=version.version_label,
        product_name=product.canonical_name,
        product_id=product.id,
        product_version_id=version.id,
        snapshot_id="snap-1",
        schema_version="v1.1+test",
    )
    # 分组标题（等待期/豁免 → 基本信息组；身故保险金 → 保险责任组）
    assert "## 基本信息" in page.content and "## 保险责任" in page.content
    assert page.content.index("## 基本信息") < page.content.index("## 保险责任")
    # 证据角标 + footnote 带文档与页码
    assert "**等待期**：90天[^" in page.content
    assert "产品说明书 第3页：“等待期为90天”" in page.content
    # absent_explicitly 渲染为明确"无"并引用证据（03 §2.3.1）
    assert "**投被保人豁免**：无（文档明确说明）[^" in page.content
    assert "第7页：“本产品无豁免责任”" in page.content


def test_k5_2_publish_contract_fields(kb_session: Session) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_all(
        kb_session,
        scope,
        version.id,
        [
            _prop(
                scope,
                version.id,
                "waiting_period",
                "等待期",
                "90天",
                chunk_id="c-1",
            ),
            _prop(
                scope,
                version.id, "grace_period", "宽限期", "60天",
                quote="宽限期60日", page=4, chunk_id="c-1",  # 同 chunk 去重
            ),
        ],
    )
    views = build_page_claims(
        kb_session,
        scope,
        version.id,
        doc_titles={"k-brochure": "产品说明书"},
        legacy_replay=True,
    )
    page = render_product_page(
        views,
        product_code=product.product_code,
        version_label=version.version_label,
        product_name=product.canonical_name,
        product_id=product.id,
        product_version_id=version.id,
        snapshot_id="snap-9",
        schema_version="v1.1+test",
    )
    assert page.slug == product_page_slug(product.product_code, version.version_label)
    assert page.slug == f"product/{product.product_code}/{version.version_label}/overview"
    assert page.source_refs == ["k-brochure|产品说明书"]  # knowledge_id|标题 去重
    assert page.chunk_refs == ["c-1"]  # 去重
    meta = page.page_metadata
    assert meta["entity_ids"] == {
        "product_id": product.id,
        "product_version_id": version.id,
    }
    assert meta["snapshot_id"] == "snap-9"
    assert set(meta["claim_ids"]) == {v.claim_id for v in views}
    assert meta["schema_version"] == "v1.1+test"
    assert meta["compiled_at"] and meta["harness_version"]


def test_t6_production_refs_only_include_validated_non_stale_lineage(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(kb_session, scope=scope)

    def source_prop(
        predicate: str,
        knowledge_id: str,
        *,
        stale: bool = False,
        lineage_status: str = "linked",
    ) -> ProposedClaim:
        return ProposedClaim(
            space_id=scope.space_id,
            product_version_id=version.id,
            predicate=predicate,
            field_name=predicate,
            value_state="present",
            value="value",
            confidence=0.9,
            evidence=[
                ProposedEvidence(
                    knowledge_id=knowledge_id,
                    doc_title=knowledge_id,
                    quote="可信原文",
                    page=1,
                    doc_role="terms",
                    authority_level=1,
                    raw_kb_id=scope.raw_kb_id,
                    source_revision="a" * 64,
                    file_hash="b" * 32,
                    original_digest="c" * 64,
                    parser_version="pdfplumber@0.11:text-v1",
                    chunk_id="chunk-fresh" if lineage_status == "linked" else None,
                    chunk_hash="d" * 64 if lineage_status == "linked" else None,
                    lineage_status=lineage_status,  # type: ignore[arg-type]
                    stale_at=datetime.now(UTC) if stale else None,
                )
            ],
        )

    _publish_all(
        kb_session,
        scope,
        version.id,
        [
            source_prop("waiting_period", "knowledge-fresh"),
            source_prop("grace_period", "knowledge-stale", stale=True),
            source_prop(
                "hesitation_period",
                "knowledge-page-only",
                lineage_status="page_only",
            ),
            _prop(
                scope,
                version.id,
                "premium_waiver",
                "保费豁免",
                "无",
                knowledge_id="legacy-policy.pdf",
                chunk_id="legacy-chunk",
            ),
        ],
    )

    production_views = build_page_claims(kb_session, scope, version.id)
    production = render_product_page(
        production_views,
        product_code=product.product_code,
        version_label=version.version_label,
        product_name=product.canonical_name,
        product_id=product.id,
        product_version_id=version.id,
        snapshot_id="snapshot-production",
    )
    assert production.source_refs == [
        "knowledge-page-only|knowledge-page-only",
        "knowledge-fresh|knowledge-fresh",
    ] or set(production.source_refs) == {
        "knowledge-page-only|knowledge-page-only",
        "knowledge-fresh|knowledge-fresh",
    }
    assert production.chunk_refs == ["chunk-fresh"]
    assert all("legacy-policy.pdf" not in ref for ref in production.source_refs)
    assert all("knowledge-stale" not in ref for ref in production.source_refs)

    replay_views = build_page_claims(
        kb_session,
        scope,
        version.id,
        legacy_replay=True,
    )
    replay = render_product_page(
        replay_views,
        product_code=product.product_code,
        version_label=version.version_label,
        product_name=product.canonical_name,
        product_id=product.id,
        product_version_id=version.id,
        snapshot_id="snapshot-replay",
    )
    assert any("legacy-policy.pdf" in ref for ref in replay.source_refs)
    assert "legacy-chunk" in replay.chunk_refs
    assert all("knowledge-stale" not in ref for ref in replay.source_refs)


def test_t6_corrupt_source_audit_is_omitted_from_refs_without_breaking_page(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    prop = ProposedClaim(
        space_id=scope.space_id,
        product_version_id=version.id,
        predicate="waiting_period",
        field_name="等待期",
        value_state="present",
        value="90天",
        confidence=0.9,
        evidence=[
            ProposedEvidence(
                knowledge_id="knowledge-corrupt",
                quote="等待期为90天",
                page=1,
                raw_kb_id=scope.raw_kb_id,
                source_revision="a" * 64,
                file_hash="b" * 32,
                original_digest="c" * 64,
                parser_version="parser-v1",
                chunk_id="chunk-corrupt",
                chunk_hash="d" * 64,
                lineage_status="linked",
            )
        ],
    )
    _publish_all(kb_session, scope, version.id, [prop])
    evidence = kb_session.execute(select(ClaimEvidence)).scalar_one()
    evidence.raw_kb_id = "wrong-raw-kb"
    evidence.source_revision = "not-a-sha256"
    evidence.original_digest = "also-invalid"
    evidence.chunk_hash = "invalid"
    kb_session.flush()

    views = build_page_claims(kb_session, scope, version.id)
    page = render_product_page(
        views,
        product_code=product.product_code,
        version_label=version.version_label,
        product_name=product.canonical_name,
        product_id=product.id,
        product_version_id=version.id,
        snapshot_id="snapshot-corrupt",
    )

    assert "等待期为90天" in page.content
    assert page.source_refs == []
    assert page.chunk_refs == []
