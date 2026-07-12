"""K5.1/K5.2：页面编译（分组渲染 + 证据角标 + 发布契约字段）。"""

from sqlalchemy.orm import Session

from insurance_harness.knowledge import (
    MergeEngine,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    build_page_claims,
    product_page_slug,
    render_product_page,
)
from tests.kbhelpers import seed_product


def _prop(
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


def _publish_all(session: Session, version_id: str, props: list[ProposedClaim]) -> None:
    engine = MergeEngine(session, policy=MergePolicy(auto_apply_add=True))
    change_set, _ = engine.open_change_set(source_kind="document")
    engine.apply_batch(change_set, props)


def test_k5_1_grouped_render_with_evidence_footnotes(kb_session: Session) -> None:
    product, version = seed_product(kb_session)
    _publish_all(
        kb_session,
        version.id,
        [
            _prop(
                version.id, "waiting_period", "等待期", "90天",
                quote="等待期为90天", chunk_id="c-1",
            ),
            _prop(
                version.id, "death_benefit", "身故保险金", "已交保费与现金价值较大者",
                quote="身故给付……", page=5, chunk_id="c-2",
            ),
            _prop(
                version.id, "premium_waiver", "投被保人豁免", None,
                value_state="absent_explicitly", quote="本产品无豁免责任", page=7,
            ),
        ],
    )
    views = build_page_claims(
        kb_session,
        version.id,
        doc_titles={"k-brochure": "产品说明书"},
        field_names={
            "waiting_period": "等待期",
            "death_benefit": "身故保险金",
            "premium_waiver": "投被保人豁免",
        },
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
    product, version = seed_product(kb_session)
    _publish_all(
        kb_session,
        version.id,
        [
            _prop(version.id, "waiting_period", "等待期", "90天", chunk_id="c-1"),
            _prop(
                version.id, "grace_period", "宽限期", "60天",
                quote="宽限期60日", page=4, chunk_id="c-1",  # 同 chunk 去重
            ),
        ],
    )
    views = build_page_claims(
        kb_session, version.id, doc_titles={"k-brochure": "产品说明书"}
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
