"""定向补漏 pass（004 T6；spec E4.1；设计 04 Step 6——豁免问题的正解）。

只针对 extractable 且当前 unknown 的字段：用字段 aliases/证据关键词做确定性检索
取候选章节，改判断题式二次提问；所有候选段落都"未提及" → 维持 unknown，
**绝不因"没找到"输出"无豁免"**（三态纪律，坑清单 #5）。
"""

import re
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from ..goldenset.pdf import PageText
from ..schemas import FieldSpec
from .cleaning import clean_value
from .compat import check_field_value
from .experiment import Arm
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


def _variant_for(
    field: FieldSpec, registry: VariantRegistry, arm: "Arm | None"
) -> PromptVariant:
    """按 (组, field_id) 选变体（E2.1），注册表由管道注入（不取全局默认）。

    实验臂语义（E7）：``control`` 臂强制默认模板（即使字段已注册）；``treatment``
    与实验关闭（None）走注册表判定。首轮 baseline 抽取两臂完全一致，臂差异仅在此。
    """
    if arm == "control":
        return select_variant(registry, group="", field_id="__control__")
    group = FIELD_NAME_TO_GROUP.get(field.name, "")
    return select_variant(registry, group=group, field_id=field.field_id)


def _used_version(variant: PromptVariant) -> str:
    """实际使用标识（E7）：选中并真实用于组装 prompt 的变体版本（targeted@vN 或
    default@v1）——注册表 membership 不得冒充实际使用，此处 variant 即实际所用。"""
    return variant.version


def _stamp_variant(
    cand: FieldCandidate,
    variant: PromptVariant,
    arm: "Arm | None",
    pointer_terms: tuple[str, ...] = (),
) -> FieldCandidate:
    """E7：记录**实际经过**的模板、实验臂与指针检索词（020 D4 A/B 对账依据）。"""
    meta = {
        **cand.metadata,
        VARIANT_METADATA_KEY: _used_version(variant),
        "variant_assignment": arm,
    }
    if pointer_terms:
        meta["pointer_terms"] = list(pointer_terms)
    return cand.model_copy(update={"metadata": meta})


_POINTER_TERM_RE = re.compile(
    r"(第[0-9一二三四五六七八九十百.．、]+[条章节款]|附[表件录][一二三四五六七八九十0-9]*|费率表|现金价值表)"
)


def parse_pointer_terms(source_pointer: str | None) -> tuple[str, ...]:
    """E6/E3：从首轮 source_pointer（"见第5.3条/详见附表二"）解析定向检索词。

    被指向的正文（如附表）可能不再出现字段名——指针词条让检索能命中目标章节；
    字段关键词仍作 fallback（并集计分）。解析结果进 pred 审计（pointer_terms）。
    """
    if not source_pointer:
        return ()
    seen: dict[str, None] = {}
    for m in _POINTER_TERM_RE.findall(source_pointer):
        seen.setdefault(m)
    return tuple(seen)


class GapfillDecision(BaseModel):
    """E3 触发判定（纯函数产物）：eligible + 可审计原因。"""

    model_config = ConfigDict(frozen=True)

    eligible: bool
    reason: str


def gapfill_eligibility(
    field: FieldSpec,
    merged: FieldCandidate | None,
    *,
    budget_remaining: int | None,
) -> GapfillDecision:
    """E3：触发 = 字段属适用 schema（调用方已按 line 过滤）且 requiredness ∈
    {required, expected}，首轮为空/unknown/source_pointer，且预算允许。
    金标不参与（签名可证）；候选章节存在性由检索层裁定（无候选=零调用）。"""
    if field.requiredness == "optional":
        return GapfillDecision(eligible=False, reason="optional_field")
    if merged is not None and merged.tri_state != "unknown":
        return GapfillDecision(eligible=False, reason="already_resolved")
    if budget_remaining is not None and budget_remaining <= 0:
        return GapfillDecision(eligible=False, reason="budget_exhausted")
    return GapfillDecision(eligible=True, reason="required_or_expected_unknown")


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
    field: FieldSpec,
    sections: Sequence[tuple[str, DocSection]],
    top_n: int = 3,
    extra_terms: tuple[str, ...] = (),
) -> list[tuple[str, DocSection]]:
    """确定性检索：按关键词出现次数为 (doc, section) 打分，取 top-N（score>0）。

    ``extra_terms``（source_pointer 解析词条）与字段关键词并集计分——被指向的
    附表正文即使不含字段名也能命中（E6「供补漏 pass 定向追抽」的落地）。"""
    keywords = tuple(dict.fromkeys((*gapfill_keywords(field), *extra_terms)))
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
    *,
    registry: VariantRegistry | None = None,
    arm: "Arm | None" = None,
    source_pointer: str | None = None,
) -> FieldCandidate:
    """对单个 unknown 字段执行补漏：三态输出，present/absent 必须过 quote 回验。

    注册表/臂由管道注入（E7）；``source_pointer`` 解析词条参与检索（E6）。
    无候选章节 → 零 LLM 调用返回 unknown（E3 触发合同）。"""
    registry = registry if registry is not None else VariantRegistry.default()
    variant = _variant_for(field, registry, arm)
    pointer_terms = parse_pointer_terms(source_pointer)
    candidates = rank_sections(field, sections, top_n, extra_terms=pointer_terms)
    if not candidates:
        return _stamp_variant(
            _unknown(field, doc="", reason="no_candidate_sections"),
            variant, arm, pointer_terms,
        )

    keywords = gapfill_keywords(field)
    compat_reject_reason: str | None = None  # E6.3：补漏路径的兼容性拒绝原因（可审计）
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
                # 不兼容值不得入 pred（024 E6）：当作该段无线索，但记原因供审计
                compat_reject_reason = verdict.reason
                continue
        if not all_quotes_verified(cand.evidence, pages_by_doc.get(doc, ())):
            continue  # 未验证引文不得出场（E3.2），当作无线索处理
        out = cand.model_copy(update={"origin": "gapfill", "confidence": "medium"})
        return _stamp_variant(out, variant, arm, pointer_terms)

    if compat_reject_reason is not None:
        # 找到了值但因语义不兼容被拒（E6.3 可审计）——与 extract.py 校验链同构，
        # 不得笼统记 not_found（gauntlet F6：补漏路径拒绝原因此前丢失）。
        rejected = _unknown(field, doc="", reason="incompatible_value")
        rejected.metadata["compat_reject"] = compat_reject_reason
        return _stamp_variant(rejected, variant, arm, pointer_terms)
    return _stamp_variant(
        _unknown(field, doc="", reason="not_found"), variant, arm, pointer_terms
    )
