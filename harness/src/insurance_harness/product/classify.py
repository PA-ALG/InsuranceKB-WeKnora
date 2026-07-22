"""文档分类器（spec P3）：确定性特征优先，LLM 只兜底。

确定性信号有两路——文件名关键词与内容特征。两路一致 → high；
只有一路 → medium；两路冲突 → 以内容为准（medium，basis 记录冲突）；
全部落空且提供了 model_client → LLM 兜底；否则 unknown（不猜测，P3.3）。
"""

import json
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from insurance_harness.goldenset.annotator import ModelClient
from insurance_harness.goldenset.pdf import PageText


class DocumentType(StrEnum):
    TERMS = "条款"
    BROCHURE = "产品说明书"
    RATE_TABLE = "费率表"
    FAQ = "FAQ"
    MARKETING = "宣传材料"
    UNKNOWN = "未知"


class Classification(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_type: DocumentType
    product_line: str | None  # schema 注册表 line_key
    confidence: str  # high / medium / low
    basis: tuple[str, ...]
    used_llm: bool = False


class ClassificationModelBoundaryError(PermissionError):
    """Typed refusal for a raw classifier client outside an explicit offline lane."""

    def __init__(self, reason_code: str = "offline_profile_required") -> None:
        self.reason_code = reason_code
        super().__init__("raw classification model clients require an offline profile")


_FILENAME_RULES: tuple[tuple[str, DocumentType], ...] = (
    ("条款", DocumentType.TERMS),
    ("说明书", DocumentType.BROCHURE),
    ("费率", DocumentType.RATE_TABLE),
    ("FAQ", DocumentType.FAQ),
    ("问答", DocumentType.FAQ),
    ("常见问题", DocumentType.FAQ),
    ("宣传", DocumentType.MARKETING),
    ("彩页", DocumentType.MARKETING),
)

# 注册号：如 "平安人寿〔2026〕年金保险013号"
_REGISTRATION_RE = re.compile(r"[〔\[]\s*\d{4}\s*[〕\]][^号\n]{0,20}\d+\s*号")

# 险种关键词 → schema 注册表 line_key（顺序敏感：更具体的在前）
_LINE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("意外医疗", "accident-medical"),
    ("医疗意外", "accident-medical"),
    ("失能收入", "disability-income"),
    ("补充养老", "supplementary-pension"),
    ("护理保险", "long-term-care"),
    ("重大疾病", "critical-illness"),
    ("重疾", "critical-illness"),
    ("终身寿险", "whole-life"),
    ("定期寿险", "term-life"),
    ("两全保险", "endowment"),
    ("年金保险", "annuity"),
    ("医疗保险", "medical"),
    ("意外伤害", "accident"),
)


def detect_product_line(text: str) -> str | None:
    for keyword, line_key in _LINE_KEYWORDS:
        if keyword in text:
            return line_key
    return None


def doc_type_from_filename(file_name: str) -> DocumentType | None:
    """按文件名关键词判型（也用作样本自评的真值来源，P3.2/P4.5）。"""
    hit = _classify_by_filename(file_name)
    return hit[0] if hit else None


def _classify_by_filename(file_name: str) -> tuple[DocumentType, str] | None:
    for keyword, doc_type in _FILENAME_RULES:
        if keyword.lower() in file_name.lower():
            return doc_type, f"文件名含“{keyword}”"
    return None


def _classify_by_content(head_text: str) -> tuple[DocumentType, str] | None:
    if "产品说明书" in head_text:
        return DocumentType.BROCHURE, "内容含“产品说明书”"
    if _REGISTRATION_RE.search(head_text) and ("条款" in head_text or "阅读指引" in head_text):
        return DocumentType.TERMS, "内容含注册号且出现“条款/阅读指引”"
    if ("费率表" in head_text or "金额表" in head_text) and (
        "投保年龄" in head_text or "单位：人民币" in head_text or "每万元" in head_text
    ):
        return DocumentType.RATE_TABLE, "内容含费率/金额表特征"
    if "常见问题" in head_text or "Q&A" in head_text or "Ｑ＆Ａ" in head_text:
        return DocumentType.FAQ, "内容含常见问题特征"
    return None


_LLM_SYSTEM = (
    "你是保险文档分类器。只输出 JSON：{\"doc_type\": \"条款|产品说明书|费率表|FAQ|宣传材料|未知\","
    " \"reason\": \"...\"}。不确定时输出 未知。"
)


async def classify_document(
    file_name: str,
    pages: list[PageText],
    *,
    model_client: ModelClient | None = None,
    model_profile: str | None = None,
) -> Classification:
    if model_client is not None and model_profile not in {"offline-eval", "replay"}:
        raise ClassificationModelBoundaryError()

    head_text = "\n".join(p.text for p in pages[:2])
    line = detect_product_line(file_name + "\n" + head_text)

    by_name = _classify_by_filename(file_name)
    by_content = _classify_by_content(head_text)

    if by_name and by_content:
        if by_name[0] is by_content[0]:
            return Classification(
                doc_type=by_name[0],
                product_line=line,
                confidence="high",
                basis=(by_name[1], by_content[1]),
            )
        return Classification(
            doc_type=by_content[0],
            product_line=line,
            confidence="medium",
            basis=(f"冲突：{by_name[1]} vs {by_content[1]}，以内容为准", by_content[1]),
        )
    hit = by_content or by_name
    if hit:
        return Classification(
            doc_type=hit[0], product_line=line, confidence="medium", basis=(hit[1],)
        )

    if model_client is not None:
        raw = await model_client.complete(_LLM_SYSTEM, head_text[:3000])
        try:
            data = json.loads(raw)
            doc_type = DocumentType(data.get("doc_type", "未知"))
            reason = str(data.get("reason", ""))
        except (json.JSONDecodeError, ValueError):
            doc_type, reason = DocumentType.UNKNOWN, "LLM 输出不可解析"
        return Classification(
            doc_type=doc_type,
            product_line=line,
            confidence="low",
            basis=(f"LLM 兜底：{reason}",),
            used_llm=True,
        )

    return Classification(
        doc_type=DocumentType.UNKNOWN,
        product_line=line,
        confidence="low",
        basis=("无确定性特征命中",),
    )
