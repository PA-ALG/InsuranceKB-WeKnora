"""页面编译器（change 007；specs K5.1/K5.2）：published Claims → 产品限定页 Markdown。

页面是 Claim 的编译投影（03 §4）：分组渲染（组语义沿用 compiler GROUP_ORDER），
每字段带证据角标（footnote：文档+页码+引文）。只有 published Claim 参与编译（K4.3）；
快照回放（rollback 渲染）按 claim_ids 白名单取数、不看当前 status。
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.compiler.routing_data import GROUP_ORDER, group_of_field
from insurance_harness.db.base import utcnow
from insurance_harness.knowledge.merge import claim_evidence, claim_value_text
from insurance_harness.knowledge.tables import Claim
from insurance_harness.schemas import SchemaRegistry

GROUP_TITLES: dict[str, str] = {
    "basic_info": "基本信息",
    "coverage": "保险责任",
    "cost_rules": "费率与费用",
    "exclusion_uw": "免责与核保",
    "claim_service": "理赔与服务",
    "contract_admin": "合同管理",
    "disease_definition": "疾病释义",
}

ABSENT_TEXT = "无（文档明确说明）"


class EvidenceView(BaseModel):
    knowledge_id: str
    doc_title: str = ""
    chunk_id: str | None = None
    page: int | None = None
    quote: str


class PageClaimView(BaseModel):
    claim_id: str
    predicate: str
    field_name: str
    group: str
    value_state: str
    value: str | None = None
    confidence: float = 0.0
    evidence: list[EvidenceView] = Field(default_factory=list)


class RenderedPage(BaseModel):
    slug: str
    title: str
    content: str
    source_refs: list[str] = Field(default_factory=list)
    chunk_refs: list[str] = Field(default_factory=list)
    page_metadata: dict[str, Any] = Field(default_factory=dict)


def field_name_of(predicate: str, registry: SchemaRegistry | None) -> str:
    if registry is not None:
        for line in registry.lines.values():
            for field in line.fields:
                if field.field_id == predicate:
                    return field.name
    return predicate


def build_page_claims(
    session: Session,
    product_version_id: str,
    *,
    registry: SchemaRegistry | None = None,
    field_names: dict[str, str] | None = None,
    doc_titles: dict[str, str] | None = None,
    claim_ids: list[str] | None = None,
) -> list[PageClaimView]:
    """取参与编译的 Claim 视图。

    - 默认：只取 published（K4.3，发布门禁）；
    - ``claim_ids`` 给定（快照回放）：按白名单取数、不看当前 status（K5.4）。
    """
    stmt = select(Claim).where(Claim.product_version_id == product_version_id)
    if claim_ids is not None:
        stmt = select(Claim).where(Claim.id.in_(claim_ids))
    else:
        stmt = stmt.where(Claim.status == "published")
    views: list[PageClaimView] = []
    for claim in session.execute(stmt).scalars():
        if claim.value_state == "unknown":
            continue  # unknown 禁止发布为"无"（03 §2.3.1）
        name = (field_names or {}).get(claim.predicate) or field_name_of(
            claim.predicate, registry
        )
        views.append(
            PageClaimView(
                claim_id=claim.id,
                predicate=claim.predicate,
                field_name=name,
                group=group_of_field(name),
                value_state=claim.value_state,
                value=claim_value_text(claim),
                confidence=claim.confidence,
                evidence=[
                    EvidenceView(
                        knowledge_id=e.knowledge_id,
                        doc_title=(doc_titles or {}).get(e.knowledge_id, e.knowledge_id),
                        chunk_id=e.chunk_id,
                        page=e.page,
                        quote=e.quote,
                    )
                    for e in sorted(
                        claim_evidence(session, claim.id),
                        key=lambda e: (e.knowledge_id, e.page or 0, e.quote),
                    )
                ],
            )
        )
    views.sort(key=lambda v: (GROUP_ORDER.index(v.group), v.field_name, v.predicate))
    return views


def product_page_slug(product_code: str, version_label: str) -> str:
    """产品总览页 slug（03 §7）：slug 只做展示定位，身份靠 page_metadata 实体 ID。"""
    return f"product/{product_code}/{version_label}/overview"


def render_product_page(
    views: list[PageClaimView],
    *,
    product_code: str,
    version_label: str,
    product_name: str,
    product_id: str,
    product_version_id: str,
    snapshot_id: str,
    schema_version: str = "",
    harness_version: str = "insurance-harness/0.1.0",
) -> RenderedPage:
    """渲染 Markdown + 发布契约字段（03 §7：source_refs/chunk_refs/page_metadata）。"""
    lines: list[str] = [f"# {product_name}（{version_label}）", ""]
    footnotes: list[str] = []
    source_refs: list[str] = []
    chunk_refs: list[str] = []
    seen_sources: set[str] = set()
    seen_chunks: set[str] = set()

    grouped: dict[str, list[PageClaimView]] = {}
    for view in views:
        grouped.setdefault(view.group, []).append(view)

    for group in GROUP_ORDER:
        group_views = grouped.get(group)
        if not group_views:
            continue
        lines.append(f"## {GROUP_TITLES.get(group, group)}")
        lines.append("")
        for view in group_views:
            marks: list[str] = []
            for e in view.evidence:
                footnotes.append(
                    f"[^{len(footnotes) + 1}]: {e.doc_title}"
                    + (f" 第{e.page}页" if e.page is not None else "")
                    + f"：“{e.quote}”"
                )
                marks.append(f"[^{len(footnotes)}]")
                ref = f"{e.knowledge_id}|{e.doc_title}"
                if ref not in seen_sources:
                    seen_sources.add(ref)
                    source_refs.append(ref)
                if e.chunk_id and e.chunk_id not in seen_chunks:
                    seen_chunks.add(e.chunk_id)
                    chunk_refs.append(e.chunk_id)
            value_text = ABSENT_TEXT if view.value_state == "absent_explicitly" else (
                view.value or ""
            )
            lines.append(f"- **{view.field_name}**：{value_text}{''.join(marks)}")
        lines.append("")

    if footnotes:
        lines.append("## 证据")
        lines.append("")
        lines.extend(footnotes)
        lines.append("")

    return RenderedPage(
        slug=product_page_slug(product_code, version_label),
        title=f"{product_name}（{version_label}）产品总览",
        content="\n".join(lines),
        source_refs=source_refs,
        chunk_refs=chunk_refs,
        page_metadata={
            "entity_ids": {
                "product_id": product_id,
                "product_version_id": product_version_id,
            },
            "snapshot_id": snapshot_id,
            "claim_ids": [v.claim_id for v in views],
            "compiled_at": utcnow().isoformat(),
            "harness_version": harness_version,
            "schema_version": schema_version,
        },
    )
