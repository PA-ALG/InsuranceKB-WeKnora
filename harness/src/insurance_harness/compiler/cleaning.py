"""占位值/弱值清洗（004 T2；spec E3.3；设计 04 Step 4）。

来源（06-asset-migration.md A6，移植方式=数据翻译）：
- ``PLACEHOLDER_PATTERNS``：译自 LLM-wiki-black
  ``frontend/src/lib/product-catalog-extractor.ts:35``（PLACEHOLDER_REGEX，30+ 模式）；
- ``SOURCE_ONLY_PATTERNS``：译自同文件 ``:36``（SOURCE_ONLY_PLACEHOLDER_REGEX）。

语义变化（06 §3.4，master plan P0-3 硬要求）：旧系统占位值统一转空字符串；
新平台占位值必须转三态 ``unknown``（绝不等同 ``absent_explicitly``）。
"详见 X" 类命中额外记录指针，供定向补漏 pass（Step 6）消解。
"""

import re
from typing import Final

from pydantic import BaseModel, ConfigDict

# 占位值模式（行首锚定；数据化存储便于单测与扩展，spec E3.3）
PLACEHOLDER_PATTERNS: Final[tuple[str, ...]] = (
    "未明确",
    "未提及",
    "未提到",
    "未说明",
    "未在本",
    "未在证据",
    "未从证据",
    "证据片段未",
    "证据片段中未",
    "证据片段没有",
    "证据中未",
    "该字段未",
    "文中未",
    "原文未",
    "原文中未",
    "材料未",
    "未找到",
    "未见",
    "没有提到",
    "证据不足",
    "无明确",
    "不涉及",
    "暂无",
    "暂未",
    "无此信息",
    "无相关",
    "本章节未",
    "条款未",
    "不适用于本",
    "N/A",
    "n/a",
    "无$",
)

# "详见来源"类模式：命中转 unknown 且记录指针供补漏 pass 使用
SOURCE_ONLY_PATTERNS: Final[tuple[str, ...]] = (
    "详见来源文件",
    "详见费率表",
    r"详见(?:原文|附件|附表|条款|附录)",
    "参见来源文件",
    "请参见来源文件",
)

_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(
    "^(" + "|".join(p.replace("/", "\\/") for p in PLACEHOLDER_PATTERNS) + ")"
)
_SOURCE_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    "^(?:" + "|".join(SOURCE_ONLY_PATTERNS) + ")(?:[:：\\s]|$)",
    re.IGNORECASE,
)


class CleanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str | None  # 清洗后的值；占位值 → None（三态 unknown，不是空字符串）
    is_placeholder: bool = False
    source_pointer: str | None = None  # "详见费率表" 类指针，供补漏 pass 消解


def clean_value(raw: str | None) -> CleanResult:
    """占位值清洗：命中 → 值置 None 按 unknown/补漏流程处理（E3.3）。"""
    if raw is None:
        return CleanResult(value=None)
    text = raw.strip()
    if not text:
        return CleanResult(value=None, is_placeholder=True)
    if _SOURCE_ONLY_RE.match(text):
        return CleanResult(value=None, is_placeholder=True, source_pointer=text)
    if _PLACEHOLDER_RE.match(text):
        return CleanResult(value=None, is_placeholder=True)
    return CleanResult(value=text)
