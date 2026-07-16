"""定向补漏 pass（004 T6；spec E4.1；设计 04 Step 6——豁免问题的正解）。

只针对 extractable 且当前 unknown 的字段：用字段 aliases/证据关键词做确定性检索
取候选章节，改判断题式二次提问；所有候选段落都"未提及" → 维持 unknown，
**绝不因"没找到"输出"无豁免"**（三态纪律，坑清单 #5）。
"""

from collections.abc import Mapping, Sequence

from ..goldenset.pdf import PageText
from ..schemas import FieldSpec
from .cleaning import clean_value
from .compat import check_field_value
from .extract import _candidate_from_item, _unknown, call_and_parse
from .llm import ModelClient
from .models import FieldCandidate
from .prompts import GAPFILL_SYSTEM, build_gapfill_user, build_targeted_gapfill_user
from .routing_data import FIELD_EVIDENCE_KEYWORDS, FIELD_NAME_ALIASES, FIELD_NAME_TO_GROUP
from .sections import DocSection
from .variants import (
    TARGETED_SHORT_ANSWER,
    VARIANT_METADATA_KEY,
    PromptVariant,
    VariantRegistry,
    select_variant,
)
from .verification import all_quotes_verified


def _variant_for(field: FieldSpec) -> PromptVariant:
    """按 (组, field_id) 选变体（E2.1）；组由字段名经 routing_data 桥接解析。"""
    group = FIELD_NAME_TO_GROUP.get(field.name, "")
    return select_variant(VariantRegistry.default(), group=group, field_id=field.field_id)


def _stamp_variant(cand: FieldCandidate, variant: PromptVariant) -> FieldCandidate:
    """E2.2：pred 元数据记录所用变体的版本化标识（020 D4 A/B 对账钩子）。"""
    return cand.model_copy(
        update={"metadata": {**cand.metadata, VARIANT_METADATA_KEY: variant.version}}
    )


def gapfill_keywords(field: FieldSpec) -> tuple[str, ...]:
    """补漏检索关键词：schema aliases + 06 A8 同义词库种子 + 字段名本身。"""
    seen: dict[str, None] = {}
    for kw in (
        field.name,
        *field.aliases,
        *FIELD_NAME_ALIASES.get(field.name, ()),
        *FIELD_EVIDENCE_KEYWORDS.get(field.name, ()),
    ):
        if kw:
            seen.setdefault(kw)
    return tuple(seen)


def rank_sections(
    field: FieldSpec, sections: Sequence[tuple[str, DocSection]], top_n: int = 3
) -> list[tuple[str, DocSection]]:
    """确定性检索：按关键词出现次数为 (doc, section) 打分，取 top-N（score>0）。"""
    keywords = gapfill_keywords(field)
    scored: list[tuple[int, int, tuple[str, DocSection]]] = []
    for idx, (doc, sec) in enumerate(sections):
        text = sec.text
        score = sum(text.count(kw) for kw in keywords)
        if score > 0:
            scored.append((-score, idx, (doc, sec)))
    scored.sort()
    return [item for _, _, item in scored[:top_n]]


async def gapfill_field(
    client: ModelClient,
    product_name: str,
    field: FieldSpec,
    sections: Sequence[tuple[str, DocSection]],  # (doc, section) 全文档池
    pages_by_doc: Mapping[str, Sequence[PageText]],
    top_n: int = 3,
) -> FieldCandidate:
    """对单个 unknown 字段执行补漏：三态输出，present/absent 必须过 quote 回验。"""
    variant = _variant_for(field)
    candidates = rank_sections(field, sections, top_n)
    if not candidates:
        return _stamp_variant(_unknown(field, doc="", reason="no_candidate_sections"), variant)

    keywords = gapfill_keywords(field)
    for doc, sec in candidates:
        if variant.targeted_template == TARGETED_SHORT_ANSWER:
            user = build_targeted_gapfill_user(
                product_name, doc, field, sec.fragments, keywords,
                guidance=variant.guidance,
            )
        else:  # 未注册字段：既有组装零漂移（E2.3）
            user = build_gapfill_user(product_name, doc, field, sec.fragments, keywords)
        parsed = await call_and_parse(client, GAPFILL_SYSTEM, user)
        if not parsed:
            continue  # 解析失败视作该段无线索，换下一个候选段落
        item = next(
            (i for i in parsed if str(i.get("field_id")) == field.field_id), parsed[0]
        )
        cand = _candidate_from_item(item, field, doc)
        if cand.tri_state == "unknown":
            continue
        cleaned = clean_value(cand.value)
        if cand.tri_state == "present" and cleaned.is_placeholder:
            continue  # 占位值不算线索
        if cand.tri_state == "present" and cand.value is not None:
            verdict = check_field_value(field, cand.value)
            if not verdict.compatible:
                continue  # 不兼容值不得入 pred（024 E6）：当作该段无线索
        if not all_quotes_verified(cand.evidence, pages_by_doc.get(doc, ())):
            continue  # 未验证引文不得出场（E3.2），当作无线索处理
        out = cand.model_copy(update={"origin": "gapfill", "confidence": "medium"})
        return _stamp_variant(out, variant)

    return _stamp_variant(_unknown(field, doc="", reason="not_found"), variant)
