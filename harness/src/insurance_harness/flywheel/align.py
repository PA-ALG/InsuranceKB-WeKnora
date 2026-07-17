"""F2.1 实体对齐（复用 003 路由器）：question → AlignedEntity。

产品级对齐复用 003 `route_document`（把问题当单页文档路由）；exact/alias 命中方
可开单，fuzzy/无命中/多产品歧义 → None（观察队列，**置信不足不开单**，fail-safe）。
字段级用注入式 field_names（DI，避免硬耦合 schema）；概念级（009 词表）候依赖 → None。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..goldenset.pdf import PageText
from ..product.routing import MatchIndex, ProductCandidate, route_document
from .gaps import AlignedEntity

#: 可自动归属的置信层（fuzzy/歧义别名进 unassigned，不入 candidates）。
_ACTIONABLE = frozenset({"exact", "alias"})

#: 别名命中依据前缀（003 routing `_scan_alias` 产出 f"别名命中：{alias}"）。
_ALIAS_BASIS_PREFIX = "别名命中："


def _match_field(question: str, field_names: Mapping[str, str]) -> str | None:
    """最长优先扫描已知字段名，命中返回 field_id。

    同长冲突以字典序决胜（确定性，非插入序）——歧义词表应由调用方避免。
    调用前须先剔除产品名/别名表面串（见 align_question），否则字段名与产品名子串误配。
    """
    for name in sorted(field_names, key=lambda n: (-len(n), n)):
        if name and name in question:
            return field_names[name]
    return None


def align_question(
    index: MatchIndex,
    question: str,
    *,
    field_names: Mapping[str, str] | None = None,
) -> AlignedEntity | None:
    """对齐问题到 (product_id?, field_id?)；置信不足或歧义 → None（不开单）。

    复用 003 `route_document`：candidates 只含 exact/alias（可自动归属），fuzzy/歧义
    别名一律进 unassigned（不入 candidates）。故：
    - candidates 空（fuzzy/歧义/无命中）→ None（观察队列）。
    - **全部 actionable 命中唯一产品** → 对齐；≥2 个不同产品 → 歧义 → None（fail-safe 不误挂）。
      不按置信层"取最强"再判唯一——那样"A 全名 + B 别名"会误挂 A，与"两个全名→None"不对称。
    字段级：先剔除已命中的产品名/别名表面串，再用注入词表匹配（否则字段名与产品名子串误配）；
    概念级（009 词表）暂缺 → concept_id 恒 None。
    """
    result = route_document(index, "flywheel-question", [PageText(page_no=1, text=question)])
    actionable = [c for c in result.candidates if c.confidence in _ACTIONABLE]
    products = {c.product_id for c in actionable}
    if len(products) != 1:
        return None  # 空=置信不足；≥2=歧义。皆进观察队列不开单。
    field_id = (
        _match_field(_scrub_product_surface(question, actionable), field_names)
        if field_names
        else None
    )
    return AlignedEntity(product_id=next(iter(products)), field_id=field_id)


def _scrub_product_surface(question: str, candidates: Iterable[ProductCandidate]) -> str:
    """剔除已命中的产品全名与别名表面串，避免字段名与产品名子串误配。

    只删整段 span（如全名"…养老年金保险"），故正文里独立出现的"养老金"仍保留、可命中字段。
    """
    scrubbed = question
    for c in candidates:
        scrubbed = scrubbed.replace(c.canonical_name, " ")
        if c.basis.startswith(_ALIAS_BASIS_PREFIX):
            alias = c.basis[len(_ALIAS_BASIS_PREFIX) :]
            if alias:
                scrubbed = scrubbed.replace(alias, " ")
    return scrubbed
