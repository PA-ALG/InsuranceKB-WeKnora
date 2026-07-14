"""产品路由（spec P4）：确定性优先、fuzzy 一律进 unassigned。

匹配层级：
- exact：备案文号 / 注册号 / product_code（词边界）/ 产品全名（最长优先，
  解决“……终身寿险”是“……终身寿险（分红型）”前缀的包含歧义）
- alias：别名唯一命中；同一别名映射多个产品 = 歧义 → 不自动归属
- fuzzy：difflib 近似候选，只产出 unassigned 草稿，绝不自动归属（P4.2）
"""

import difflib
import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductAlias, UnassignedItem
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
from insurance_harness.goldenset.pdf import PageText

Confidence = Literal["exact", "alias", "fuzzy"]

_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """匹配用归一化：去全部空白。

    pdfplumber 会在中西文之间插空格（"平安e生保" → "平安 e 生保"），
    名称/文号匹配必须在原文与去空白文本上各扫一遍取并集（P5.1 归一化）。
    """
    return _WS_RE.sub("", text)


class ProductCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    product_code: str
    canonical_name: str
    confidence: Confidence
    basis: str
    page_first: int | None = None
    page_last: int | None = None
    section_ref: str | None = None


class UnassignedDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    space_id: str
    doc_ref: str
    section_ref: str | None
    excerpt: str
    candidates: tuple[ProductCandidate, ...]
    reason: str


class RouteResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    space_id: str
    candidates: tuple[ProductCandidate, ...]
    unassigned: tuple[UnassignedDraft, ...]


class _ProductRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    product_code: str
    canonical_name: str


class MatchIndex:
    """从产品主数据构建的内存匹配索引。"""

    def __init__(
        self,
        space_id: str,
        products: list[_ProductRef],
        exact_keys: dict[str, tuple[_ProductRef, str]],
        alias_map: dict[str, set[str]],
        refs_by_id: dict[str, _ProductRef],
    ) -> None:
        self._space_id = space_id
        self._products = products
        self._exact_keys = exact_keys  # 文号/注册号 → (product, 依据)
        self._alias_map = alias_map  # alias → product_id 集合
        self._refs_by_id = refs_by_id
        # 全名按长度降序：最长匹配优先
        self._names_desc = sorted(products, key=lambda p: len(p.canonical_name), reverse=True)

    @classmethod
    def from_session(cls, session: Session, scope: KnowledgeScope) -> "MatchIndex":
        require_current_scope(session, scope)
        products: list[_ProductRef] = []
        exact_keys: dict[str, tuple[_ProductRef, str]] = {}
        refs_by_id: dict[str, _ProductRef] = {}
        for row in session.execute(
            select(InsuranceProduct).where(InsuranceProduct.space_id == scope.space_id)
        ).scalars():
            ref = _ProductRef(
                product_id=row.id, product_code=row.product_code, canonical_name=row.canonical_name
            )
            products.append(ref)
            refs_by_id[row.id] = ref
            if row.filing_no:
                exact_keys[row.filing_no] = (ref, "备案文号")
        alias_map: dict[str, set[str]] = defaultdict(set)
        for alias_row in session.execute(
            select(ProductAlias)
            .join(
                InsuranceProduct,
                ProductAlias.product_id == InsuranceProduct.id,
            )
            .where(InsuranceProduct.space_id == scope.space_id)
        ).scalars():
            alias_ref = refs_by_id.get(alias_row.product_id)
            if alias_ref is None:
                continue
            if alias_row.alias_type == "registration_no":
                exact_keys[alias_row.alias] = (alias_ref, "注册号")
            else:
                alias_map[alias_row.alias].add(alias_row.product_id)
        return cls(scope.space_id, products, exact_keys, dict(alias_map), refs_by_id)

    # --- 匹配 ---

    def _scan_exact(self, text: str) -> dict[str, tuple[_ProductRef, str]]:
        hits: dict[str, tuple[_ProductRef, str]] = {}
        # 原文与去空白文本各扫一遍取并集（PDF 提取会在中西文间插空格）
        for variant in (text, normalize_text(text)):
            for key, (ref, kind) in self._exact_keys.items():
                if key and normalize_text(key) in variant:
                    hits.setdefault(ref.product_id, (ref, f"{kind}命中：{key}"))
            for ref in self._products:
                if re.search(
                    rf"(?<![0-9A-Za-z]){re.escape(ref.product_code)}(?![0-9A-Za-z])", variant
                ):
                    hits.setdefault(ref.product_id, (ref, f"product_code 命中：{ref.product_code}"))
            # 全名最长优先：记录被更长名字覆盖的区间，短名不得在其中命中
            taken: list[tuple[int, int]] = []
            for ref in self._names_desc:
                for m in re.finditer(re.escape(normalize_text(ref.canonical_name)), variant):
                    span = m.span()
                    if any(span[0] >= s and span[1] <= e for s, e in taken):
                        continue  # 完全落在更长匹配内 → 属于包含歧义，跳过
                    taken.append(span)
                    hits.setdefault(ref.product_id, (ref, f"产品全名命中：{ref.canonical_name}"))
        return hits

    def _scan_alias(self, text: str) -> tuple[dict[str, tuple[_ProductRef, str]], list[str]]:
        hits: dict[str, tuple[_ProductRef, str]] = {}
        ambiguous: list[str] = []
        norm_text = normalize_text(text)
        for alias, pids in self._alias_map.items():
            if alias not in text and normalize_text(alias) not in norm_text:
                continue
            if len(pids) == 1:
                pid = next(iter(pids))
                hits.setdefault(pid, (self._refs_by_id[pid], f"别名命中：{alias}"))
            else:
                ambiguous.append(alias)
        return hits, ambiguous

    def _fuzzy_candidates(self, text: str, limit: int = 3) -> list[_ProductRef]:
        head = text[:500]
        scored = [
            (difflib.SequenceMatcher(None, head, p.canonical_name).ratio(), p)
            for p in self._products
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        return [p for score, p in scored[:limit] if score > 0.1]


class Section(BaseModel):
    """文档章节（拼接/多产品文档的路由单元，P4.3）。"""

    model_config = ConfigDict(frozen=True)

    section_ref: str
    pages: tuple[PageText, ...]


def route_document(index: MatchIndex, doc_ref: str, pages: list[PageText]) -> RouteResult:
    """整文档路由：视作单一章节（section_ref=None）。"""
    return _route_pages(index, doc_ref, None, pages)


def route_sections(index: MatchIndex, doc_ref: str, sections: list[Section]) -> RouteResult:
    """章节级路由：同一文档的不同章节可归属不同产品（一对多，P4.3）；

    无 exact/alias 命中的章节各自进 unassigned（带 section_ref），绝不错挂。
    """
    candidates: list[ProductCandidate] = []
    unassigned: list[UnassignedDraft] = []
    for section in sections:
        result = _route_pages(index, doc_ref, section.section_ref, list(section.pages))
        candidates.extend(result.candidates)
        unassigned.extend(result.unassigned)
    return RouteResult(
        space_id=index._space_id,
        candidates=tuple(candidates),
        unassigned=tuple(unassigned),
    )


def persist_unassigned(
    session: Session,
    scope: KnowledgeScope,
    drafts: tuple[UnassignedDraft, ...],
) -> int:
    """把 unassigned 草稿落 unassigned_pool 表（P4.4）；返回写入条数。"""
    require_current_scope(session, scope)
    if any(draft.space_id != scope.space_id for draft in drafts):
        raise ScopeViolation("scope mismatch")

    candidates = [candidate for draft in drafts for candidate in draft.candidates]
    candidate_ids = {candidate.product_id for candidate in candidates}
    if candidate_ids:
        scoped_products = {
            product.id: (product.product_code, product.canonical_name)
            for product in session.execute(
                select(InsuranceProduct).where(
                    InsuranceProduct.space_id == scope.space_id,
                    InsuranceProduct.id.in_(candidate_ids),
                )
            ).scalars()
        }
        if any(
            scoped_products.get(candidate.product_id)
            != (candidate.product_code, candidate.canonical_name)
            for candidate in candidates
        ):
            raise ScopeViolation("scope mismatch")

    for draft in drafts:
        session.add(
            UnassignedItem(
                space_id=scope.space_id,
                doc_ref=draft.doc_ref,
                section_ref=draft.section_ref,
                excerpt=draft.excerpt,
                candidates=[c.model_dump() for c in draft.candidates] or None,
                reason=draft.reason,
            )
        )
    session.flush()
    return len(drafts)


def _route_pages(
    index: MatchIndex, doc_ref: str, section_ref: str | None, pages: list[PageText]
) -> RouteResult:
    per_product_pages: dict[str, list[int]] = defaultdict(list)
    basis_map: dict[str, tuple[_ProductRef, str, Confidence]] = {}
    ambiguous_aliases: set[str] = set()

    for page in pages:
        exact = index._scan_exact(page.text)
        for pid, (ref, basis) in exact.items():
            per_product_pages[pid].append(page.page_no)
            basis_map.setdefault(pid, (ref, basis, "exact"))
        alias_hits, ambiguous = index._scan_alias(page.text)
        ambiguous_aliases.update(ambiguous)
        for pid, (ref, basis) in alias_hits.items():
            if pid in basis_map:
                per_product_pages[pid].append(page.page_no)
                continue
            per_product_pages[pid].append(page.page_no)
            basis_map.setdefault(pid, (ref, basis, "alias"))

    # 歧义别名若其候选集与已确认归属相交，视为被该归属解释（如短别名是已命中全名的子串），
    # 不再另立歧义草稿；仅剩余的"无法被解释"的歧义才需要人工确认。
    resolved_pids = set(basis_map)
    ambiguous_aliases = {
        alias
        for alias in ambiguous_aliases
        if not (index._alias_map.get(alias, set()) & resolved_pids)
    }

    candidates = tuple(
        ProductCandidate(
            product_id=pid,
            product_code=ref.product_code,
            canonical_name=ref.canonical_name,
            confidence=conf,
            basis=basis,
            page_first=min(per_product_pages[pid]),
            page_last=max(per_product_pages[pid]),
            section_ref=section_ref,
        )
        for pid, (ref, basis, conf) in basis_map.items()
    )

    unassigned: list[UnassignedDraft] = []
    if not candidates:
        full_text = "\n".join(p.text for p in pages)
        if ambiguous_aliases:
            # 唯一信号是歧义别名（同分候选）→ 带候选进 unassigned，不得自动归属（P4.2）
            amb_candidates = tuple(
                ProductCandidate(
                    product_id=pid,
                    product_code=index._refs_by_id[pid].product_code,
                    canonical_name=index._refs_by_id[pid].canonical_name,
                    confidence="alias",
                    basis=f"歧义别名命中：{alias}（映射多个产品，不自动归属）",
                )
                for alias in sorted(ambiguous_aliases)
                for pid in sorted(index._alias_map.get(alias, ()))
            )
            unassigned.append(
                UnassignedDraft(
                    space_id=index._space_id,
                    doc_ref=doc_ref,
                    section_ref=section_ref,
                    excerpt=full_text[:300],
                    candidates=amb_candidates,
                    reason="别名歧义（映射多个产品），需人工确认",
                )
            )
        else:
            fuzzy = tuple(
                ProductCandidate(
                    product_id=p.product_id,
                    product_code=p.product_code,
                    canonical_name=p.canonical_name,
                    confidence="fuzzy",
                    basis="近似候选（不自动归属）",
                )
                for p in index._fuzzy_candidates(full_text)
            )
            unassigned.append(
                UnassignedDraft(
                    space_id=index._space_id,
                    doc_ref=doc_ref,
                    section_ref=section_ref,
                    excerpt=full_text[:300],
                    candidates=fuzzy,
                    reason="无 exact/alias 命中",
                )
            )
    elif ambiguous_aliases:
        unassigned.append(
            UnassignedDraft(
                space_id=index._space_id,
                doc_ref=doc_ref,
                section_ref=section_ref,
                excerpt="；".join(sorted(ambiguous_aliases))[:300],
                candidates=(),
                reason="别名歧义（映射多个产品），需人工确认",
            )
        )

    return RouteResult(
        space_id=index._space_id,
        candidates=candidates,
        unassigned=tuple(unassigned),
    )
