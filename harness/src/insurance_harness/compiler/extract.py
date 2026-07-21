"""分批定向抽取 + 确定性校验链（004 T5；spec E3；设计 04 Step 2/3/4）。

校验链每个候选值依次过：quote 回验（E3.2）→ 占位值清洗（E3.3）→ 类型校验（E3.4）；
失败字段打回定向重抽 1 次（附具体失败原因），再失败标 unknown+原因——绝不静默丢弃，
也绝不允许未验证引文出场（宁缺勿假）。
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from ..goldenset.normalize import _parse_date, _parse_number
from ..goldenset.pdf import PageText
from ..goldenset.records import Evidence, TriState
from ..schemas import FieldSpec
from .attempts import AttemptLedger, InMemoryAttemptLedger
from .cleaning import clean_value
from .compat import check_field_value
from .llm import ModelClient, TruncatedOutputError, request_key
from .models import FieldCandidate, UnknownReason
from .parsing import extract_json_array
from .prompts import (
    EXTRACTION_SYSTEM,
    PARSE_RETRY_SUFFIX,
    PROMPT_VERSION,
    build_extraction_user,
)
from .routing_data import group_of_field
from .verification import all_quotes_verified

MAX_FIELDS_PER_CALL = 10  # spec E3.1：单次 LLM 调用 ≤10 字段

Sleeper = Callable[[float], Awaitable[None]]


class TransportRetryError(Exception):
    """传输级失败超重试上限（进死信，E1.2）。"""


async def with_transport_retry[T](
    fn: Callable[[], Awaitable[T]],
    attempts: int = 3,
    base_delay_s: float = 1.0,
    sleep: Sleeper = asyncio.sleep,
) -> T:
    """指数退避重试（1s/4s/16s 系数 4，04 §2.1）；截断视为可重试的内容级失败。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await fn()
        except (TruncatedOutputError, httpx.HTTPError, OSError, ValueError) as exc:
            last = exc
            if i + 1 < attempts:
                await sleep(base_delay_s * (4**i))
    raise TransportRetryError(f"重试 {attempts} 次后仍失败：{last!r}") from last


class CallParseResult(BaseModel):
    """Parsed response plus the exact outbound attempt that produced it."""

    model_config = ConfigDict(frozen=True)

    items: list[dict[str, Any]] | None
    producing_attempt_id: str | None
    attempt_ids: tuple[str, ...]


async def call_and_parse(
    client: ModelClient,
    system: str,
    user: str,
    *,
    ledger: AttemptLedger | None = None,
    field_ids: Sequence[str] = (),
    stage: str = "",
    prompt_version: str = "",
    budget_scope: str | None = None,
    budget_limit: int | None = None,
) -> CallParseResult:
    """一次调用 + 对抗性解析；解析失败带反馈重试 1 次（E3.1）。

    Every real outbound call is reserved before ``complete``. Parse retry is a
    separate reservation and becomes the producer when it succeeds."""
    ledger = ledger if ledger is not None else InMemoryAttemptLedger()
    attempt_ids: list[str] = []

    async def one(call_stage: str, call_user: str) -> tuple[list[dict[str, Any]] | None, str]:
        key = request_key(system, call_user)
        attempt = ledger.reserve(
            stage=call_stage,
            prompt_version=prompt_version,
            request_key=key,
            field_ids=field_ids,
            budget_scope=budget_scope,
            budget_limit=budget_limit,
        )
        attempt_ids.append(attempt.attempt_id)
        try:
            raw = await client.complete(system, call_user)
        except asyncio.CancelledError:
            ledger.finish(attempt.attempt_id, "cancelled")
            raise
        except BaseException:
            ledger.finish(attempt.attempt_id, "transport_failed")
            raise
        parsed = extract_json_array(raw)
        ledger.finish(
            attempt.attempt_id, "parsed" if parsed is not None else "parse_failed"
        )
        return parsed, attempt.attempt_id

    parsed, producer = await one(stage, user)
    if parsed is not None:
        return CallParseResult(
            items=parsed,
            producing_attempt_id=producer,
            attempt_ids=tuple(attempt_ids),
        )
    parsed, retry_producer = await one(f"{stage}_retry", user + PARSE_RETRY_SUFFIX)
    return CallParseResult(
        items=parsed,
        producing_attempt_id=retry_producer if parsed is not None else None,
        attempt_ids=tuple(attempt_ids),
    )


def validate_typed_value(field: FieldSpec, value: str) -> str | None:
    """类型校验（E3.4）：返回错误消息；None = 通过。"""
    if field.value_type == "number" and _parse_number(value) is None:
        return f"字段 {field.field_id} 要求数值型，实得 {value!r}"
    if field.value_type == "date" and _parse_date(value) is None:
        return f"字段 {field.field_id} 要求日期型（YYYY-MM-DD 或 YYYY年M月D日），实得 {value!r}"
    return None


class Window(BaseModel):
    """抽取窗口：同组若干连续路由命中章节合并成一次调用的上下文（≤window_chars）。"""

    model_config = ConfigDict(frozen=True)

    ref: str  # 如 "s001+s003"
    fragments: tuple[PageText, ...]


def build_windows(
    sections: Sequence[tuple[str, tuple[PageText, ...]]], window_chars: int = 4_000
) -> list[Window]:
    """把 (section_id, fragments) 序列贪心合并为 ≤window_chars 的调用窗口。"""
    windows: list[Window] = []
    ids: list[str] = []
    frags: list[PageText] = []
    size = 0
    for sec_id, fragments in sections:
        sec_size = sum(len(f.text) for f in fragments)
        if frags and size + sec_size > window_chars:
            windows.append(Window(ref="+".join(ids), fragments=tuple(frags)))
            ids, frags, size = [], [], 0
        ids.append(sec_id)
        frags.extend(fragments)
        size += sec_size
    if frags:
        windows.append(Window(ref="+".join(ids), fragments=tuple(frags)))
    return windows


def _candidate_from_item(
    item: dict[str, Any], field: FieldSpec, doc: str
) -> FieldCandidate:
    tri_raw = str(item.get("tri_state", "unknown"))
    tri: TriState = (
        tri_raw  # type: ignore[assignment]
        if tri_raw in ("present", "absent_explicitly", "unknown")
        else "unknown"
    )
    value_raw = item.get("value")
    evidence = [
        Evidence(page=int(e.get("page", 0)), quote=str(e.get("quote", "")))
        for e in item.get("evidence") or []
        if isinstance(e, dict)
    ]
    return FieldCandidate(
        field_id=field.field_id,
        field_name=field.name,
        group=group_of_field(field.name),
        doc=doc,
        value=None if value_raw is None else str(value_raw),
        tri_state=tri,
        evidence=evidence,
    )


def _unknown(field: FieldSpec, doc: str, reason: UnknownReason) -> FieldCandidate:
    return FieldCandidate(
        field_id=field.field_id,
        field_name=field.name,
        group=group_of_field(field.name),
        doc=doc,
        tri_state="unknown",
        unknown_reason=reason,
    )


def run_validation_chain(
    cand: FieldCandidate, field: FieldSpec, pages: Sequence[PageText]
) -> tuple[FieldCandidate, str | None]:
    """确定性校验链（04 Step 3/4）。返回 (候选值, 打回原因)；打回原因 None = 通过。"""
    if cand.tri_state == "unknown":
        return cand, None
    # 1) quote 回验：present/absent_explicitly 必须全部证据可回验（E3.2）
    if not all_quotes_verified(cand.evidence, pages):
        return cand, (
            f"字段 {cand.field_id} 的引文在所引页原文中不存在（必须逐字摘录并给准页码）"
        )
    # 2) 占位值清洗（E3.3）：命中转 unknown（不是失败，不打回；"详见X"记录指针给补漏）
    cleaned = clean_value(cand.value)
    if cand.tri_state == "present" and cleaned.is_placeholder:
        out = cand.model_copy(
            update={
                "value": None,
                "tri_state": "unknown",
                "evidence": [],
                "unknown_reason": "placeholder",
                "source_pointer": cleaned.source_pointer,
            }
        )
        return out, None
    # 2.5) 字段-值语义兼容性（024 E6）：不兼容转 unknown（可审计，不打回不重试）
    if cand.tri_state == "present" and cand.value is not None:
        verdict = check_field_value(field, cand.value)
        if not verdict.compatible:
            out = cand.model_copy(
                update={
                    "value": None,
                    "tri_state": "unknown",
                    "evidence": [],
                    "unknown_reason": "incompatible_value",
                    "metadata": {**cand.metadata, "compat_reject": verdict.reason},
                }
            )
            return out, None
    # 3) Pydantic/类型校验（E3.4）
    if cand.tri_state == "present" and cand.value is not None:
        err = validate_typed_value(field, cand.value)
        if err is not None:
            return cand, err
    return cand, None


class WindowExtractor:
    """对一个 (文档, 字段组, 窗口) 执行分批抽取 + 校验链 + 打回流程。"""

    def __init__(
        self,
        client: ModelClient,
        product_name: str,
        doc: str,
        pages: Sequence[PageText],
        max_fields_per_call: int = MAX_FIELDS_PER_CALL,
        ledger: AttemptLedger | None = None,
    ) -> None:
        self._client = client
        self._product = product_name
        self._doc = doc
        self._pages = pages
        self._batch_size = min(max_fields_per_call, MAX_FIELDS_PER_CALL)
        self._ledger = ledger if ledger is not None else InMemoryAttemptLedger()

    async def extract(
        self, window: Window, fields: Sequence[FieldSpec]
    ) -> list[FieldCandidate]:
        out: list[FieldCandidate] = []
        for i in range(0, len(fields), self._batch_size):
            out.extend(await self._extract_batch(window, fields[i : i + self._batch_size]))
        return out

    async def _extract_batch(
        self, window: Window, batch: Sequence[FieldSpec]
    ) -> list[FieldCandidate]:
        user = build_extraction_user(self._product, self._doc, batch, window.fragments)
        call = await call_and_parse(
            self._client, EXTRACTION_SYSTEM, user,
            ledger=self._ledger, field_ids=tuple(f.field_id for f in batch),
            stage="extract",
            prompt_version=f"baseline@{PROMPT_VERSION}",
        )
        parsed = call.items
        if parsed is None:  # 解析重试仍失败：该批全部 unknown+原因（E3.1）
            failed_batch = [_unknown(f, self._doc, "parse_failed") for f in batch]
            for fb in failed_batch:
                fb.metadata["attempts"] = [
                    a.model_dump() for a in self._ledger.attempts_for_field(fb.field_id)
                ]
            return failed_batch

        by_id = {str(item.get("field_id")): item for item in parsed}
        results: dict[str, FieldCandidate] = {}
        rejects: list[tuple[FieldSpec, str]] = []  # (字段, 失败反馈)
        for f in batch:
            item = by_id.get(f.field_id)
            if item is None:
                results[f.field_id] = _unknown(f, self._doc, "missing_in_response")
                continue
            cand, err = run_validation_chain(
                _candidate_from_item(item, f, self._doc), f, self._pages
            )
            if err is None:
                results[f.field_id] = cand
                if cand.tri_state != "unknown" and call.producing_attempt_id is not None:
                    cand.metadata["winning_attempt_id"] = call.producing_attempt_id
            else:
                rejects.append((f, err))
                results[f.field_id] = cand  # 占位，打回成功后覆盖

        if rejects:  # 打回定向重抽 1 次（E3.2/E3.4），再失败标 unknown+原因
            feedback = "\n".join(err for _, err in rejects)
            retry_fields = [f for f, _ in rejects]
            user2 = build_extraction_user(
                self._product, self._doc, retry_fields, window.fragments, feedback=feedback
            )
            retry_call = await call_and_parse(
                self._client, EXTRACTION_SYSTEM, user2,
                ledger=self._ledger,
                field_ids=tuple(f.field_id for f in retry_fields),
                stage="extract_validation_retry",
                prompt_version=f"baseline@{PROMPT_VERSION}",
            )
            parsed2 = retry_call.items
            by_id2 = {str(i.get("field_id")): i for i in parsed2 or []}
            for f, first_err in rejects:
                reason: UnknownReason = (
                    "quote_mismatch" if "引文" in first_err else "validation_failed"
                )
                item2 = by_id2.get(f.field_id)
                if item2 is None:
                    results[f.field_id] = _unknown(f, self._doc, reason)
                    continue
                cand2, err2 = run_validation_chain(
                    _candidate_from_item(item2, f, self._doc), f, self._pages
                )
                if err2 is None:
                    results[f.field_id] = cand2
                    if (
                        cand2.tri_state != "unknown"
                        and retry_call.producing_attempt_id is not None
                    ):
                        cand2.metadata["winning_attempt_id"] = (
                            retry_call.producing_attempt_id
                        )
                else:  # 不得带着未验证引文出场：值/证据一律清空
                    failed = _unknown(f, self._doc, reason)
                    failed.metadata["rejected_value"] = cand2.value
                    failed.metadata["rejected_evidence"] = [
                        e.model_dump() for e in cand2.evidence
                    ]
                    results[f.field_id] = failed
        # Standalone callers receive the same field-scoped projection that finalize
        # later reconstructs from the durable run ledger.
        for f in batch:
            out_cand = results[f.field_id]
            out_cand.metadata["attempts"] = [
                a.model_dump() for a in self._ledger.attempts_for_field(f.field_id)
            ]
        return [results[f.field_id] for f in batch]
