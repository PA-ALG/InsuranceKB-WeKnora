"""金标注 Agent（spec G2）：最强模型直读 PDF 文本，按字段组分批标注。

模型输出解析按对抗性任务处理（10 §3 / llm_wiki 经验）：容错提取 JSON、
失败重试一次、再失败该批字段全部记 unknown+disputed——绝不静默丢弃。
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from ..compiler.llm import LiteLLMClient as _GenericLiteLLMClient

# 对抗性解析 / 模型客户端已提升为 compiler 公共模块（004 T1），此处保留再导出以稳定 002 接口
from ..compiler.llm import ModelClient, ReplayClient, request_key
from ..compiler.parsing import extract_json_array
from ..config import HarnessSettings
from ..schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from .pdf import PageText
from .records import Evidence, GoldenRecord, TriState

__all__ = [
    "GoldenAnnotator",
    "LiteLLMClient",
    "ModelClient",
    "ReplayClient",
    "extract_json_array",
    "request_key",
]

_BATCH_SIZE = 10

_SYSTEM_PROMPT = """你是寿险产品条款标注专家，为知识抽取系统构建金标准（golden set）。
你收到一份产品文档的分页全文和一组字段定义，逐字段判定并输出 JSON 数组，每个元素：
{"field_id": "...", "value": "字符串或 null", "tri_state": "present|absent_explicitly|unknown",
 "evidence": [{"page": 页码整数, "quote": "原文逐字摘录"}], "reasoning": "一句话依据"}

判定规则（严格执行）：
- present：文档明确给出该字段取值。value 填规范化取值；evidence 至少 1 条，
  quote 必须逐字来自对应页（会做程序化回验，改写即废）。
- absent_explicitly：文档明确表示不含/排除该项（如免责条款明确排除）。也必须给 evidence。
- unknown：文档中找不到任何依据。value 为 null，evidence 为空。
  禁止把 unknown 写成"无/不含"。
- 只输出 JSON 数组，不要任何其他文字。"""


class LiteLLMClient:
    """金标注真实调用：compiler 通用 LiteLLMClient 的 settings 包装（004 T1 重构）。"""

    def __init__(self, settings: HarnessSettings) -> None:
        if not settings.goldenset_model:
            raise ValueError("缺少 HARNESS_GOLDENSET_MODEL 配置")
        self._inner = _GenericLiteLLMClient(
            model=settings.goldenset_model,
            api_base=settings.goldenset_api_base,
            api_key=settings.goldenset_api_key,
            temperature=0.0,
        )

    async def complete(self, system: str, user: str) -> str:  # pragma: no cover - 需真实网关
        return await self._inner.complete(system, user)


def _pages_block(pages: Sequence[PageText]) -> str:
    return "\n\n".join(f"【第{p.page_no}页】\n{p.text}" for p in pages)


def _select_pages(
    pages: Sequence[PageText], fields: Sequence[FieldSpec], budget: int
) -> Sequence[PageText]:
    """全文超预算时按字段关键词过滤页面（G2.6）；命中不足则回退前若干页。"""
    if sum(len(p.text) for p in pages) <= budget:
        return pages
    keywords = {f.name for f in fields} | {a for f in fields for a in f.aliases}
    hit = [p for p in pages if any(k in p.text for k in keywords)]
    selected = hit or list(pages)
    out: list[PageText] = []
    used = 0
    for p in selected:
        if used + len(p.text) > budget and out:
            break
        out.append(p)
        used += len(p.text)
    return out


def _field_block(fields: Sequence[FieldSpec]) -> str:
    lines = []
    for f in fields:
        desc = f"；说明：{f.description}" if f.description else ""
        src = f"；预期来源：{'/'.join(f.allowed_sources)}" if f.allowed_sources else ""
        lines.append(f"- field_id={f.field_id}｜字段名：{f.name}{desc}{src}")
    return "\n".join(lines)


class GoldenAnnotator:
    def __init__(
        self,
        model_client: ModelClient,
        registry: SchemaRegistry,
        annotator_model: str,
        doc_char_budget: int = 30_000,
    ) -> None:
        self._client = model_client
        self._registry = registry
        self._model = annotator_model
        self._budget = doc_char_budget

    async def annotate_document(
        self,
        product_id: str,
        product_name: str,
        doc_name: str,
        pages: list[PageText],
        line: ProductLineSchema,
        created_at: datetime | None = None,
    ) -> list[GoldenRecord]:
        created = created_at or datetime.now(UTC)
        fields = list(line.extractable_fields)
        records: list[GoldenRecord] = []
        for i in range(0, len(fields), _BATCH_SIZE):
            batch = fields[i : i + _BATCH_SIZE]
            records.extend(
                await self._annotate_batch(
                    product_id, product_name, doc_name, pages, batch, created
                )
            )
        return records

    async def _annotate_batch(
        self,
        product_id: str,
        product_name: str,
        doc_name: str,
        pages: list[PageText],
        batch: list[FieldSpec],
        created: datetime,
    ) -> list[GoldenRecord]:
        selected = _select_pages(pages, batch, self._budget)
        user = (
            f"产品：{product_name}\n文档：{doc_name}\n\n"
            f"## 待标注字段\n{_field_block(batch)}\n\n"
            f"## 文档全文（分页）\n{_pages_block(selected)}"
        )
        raw = await self._client.complete(_SYSTEM_PROMPT, user)
        parsed = extract_json_array(raw)
        if parsed is None:
            raw = await self._client.complete(
                _SYSTEM_PROMPT, user + "\n\n注意：上次输出无法解析。只输出 JSON 数组本身。"
            )
            parsed = extract_json_array(raw)
        if parsed is None:
            return [
                self._make_record(
                    product_id, product_name, doc_name, f, None, "unknown", [], created,
                    disputed_reason="parse_failed",
                )
                for f in batch
            ]
        by_id = {str(item.get("field_id")): item for item in parsed}
        out: list[GoldenRecord] = []
        for f in batch:
            item = by_id.get(f.field_id)
            if item is None:
                out.append(
                    self._make_record(
                        product_id, product_name, doc_name, f, None, "unknown", [], created,
                        disputed_reason="missing_in_response",
                    )
                )
                continue
            tri_raw = str(item.get("tri_state", "unknown"))
            tri: TriState = (
                cast(TriState, tri_raw)
                if tri_raw in ("present", "absent_explicitly", "unknown")
                else "unknown"
            )
            value_raw = item.get("value")
            value = None if value_raw is None else str(value_raw)
            evidence = [
                Evidence(page=int(e.get("page", 0)), quote=str(e.get("quote", "")))
                for e in item.get("evidence") or []
                if isinstance(e, dict)
            ]
            out.append(
                self._make_record(
                    product_id, product_name, doc_name, f, value, tri, evidence, created,
                    reasoning=str(item.get("reasoning", "")) or None,
                )
            )
        return out

    def _make_record(
        self,
        product_id: str,
        product_name: str,
        doc_name: str,
        field: FieldSpec,
        value: str | None,
        tri: TriState,
        evidence: list[Evidence],
        created: datetime,
        *,
        reasoning: str | None = None,
        disputed_reason: str | None = None,
    ) -> GoldenRecord:
        return GoldenRecord(
            product_id=product_id,
            product_name=product_name,
            doc=doc_name,
            field_id=field.field_id,
            field_name=field.name,
            value=value,
            tri_state=tri,
            evidence=evidence,
            disputed=disputed_reason is not None,
            disputed_reason=cast(Any, disputed_reason),
            reasoning=reasoning,
            annotator_model=self._model,
            schema_version=self._registry.version,
            created_at=created,
        )
