"""spec E3：分批抽取 ≤10 字段、对抗性解析、回验打回、清洗、类型校验。"""

import json

import pytest

from insurance_harness.compiler.extract import (
    MAX_FIELDS_PER_CALL,
    TransportRetryError,
    Window,
    WindowExtractor,
    build_windows,
    validate_typed_value,
    with_transport_retry,
)
from insurance_harness.compiler.llm import TruncatedOutputError
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.schemas import FieldSpec

PAGES = [
    PageText(page_no=1, text="犹豫期为20日。等待期为90天。免赔额为1万元。生效日期2026年1月1日。"),
]
WINDOW = Window(ref="s001", fragments=tuple(PAGES))


def _field(fid: str, name: str, **kw: object) -> FieldSpec:
    return FieldSpec(name=name, field_id=fid, source_sheet="t", **kw)  # type: ignore[arg-type]


class QueueClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0
        self.prompts: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        self.prompts.append((system, user))
        return self._responses.pop(0)


def _resp(*items: dict[str, object]) -> str:
    return json.dumps(list(items), ensure_ascii=False)


def _ok_item(fid: str, value: str, quote: str) -> dict[str, object]:
    return {
        "field_id": fid, "value": value, "tri_state": "present",
        "evidence": [{"page": 1, "quote": quote}],
    }


async def test_e3_1_batches_capped_at_10_fields_per_call() -> None:
    fields = [_field(f"f{i:02d}", f"字段{i}") for i in range(23)]
    unknown_items: list[dict[str, object]] = [
        {"field_id": f.field_id, "value": None, "tri_state": "unknown", "evidence": []}
        for f in fields
    ]
    responses = [_resp(*unknown_items[i : i + 10]) for i in range(0, 23, 10)]
    client = QueueClient(responses)
    extractor = WindowExtractor(client, "测试产品", "条款.pdf", PAGES)
    out = await extractor.extract(WINDOW, fields)
    assert client.calls == 3  # ceil(23/10)
    assert len(out) == 23
    for _system, user in client.prompts:
        assert user.count("field_id=") <= MAX_FIELDS_PER_CALL
    assert MAX_FIELDS_PER_CALL == 10


async def test_e3_1_parse_failure_retries_once_then_unknown_with_reason() -> None:
    f = _field("hesitation", "犹豫期")
    client = QueueClient(["不是JSON", "还不是JSON"])
    out = await WindowExtractor(client, "P", "条款.pdf", PAGES).extract(WINDOW, [f])
    assert client.calls == 2
    assert out[0].tri_state == "unknown" and out[0].unknown_reason == "parse_failed"


async def test_e3_2_quote_mismatch_rejected_then_retry_then_unknown() -> None:
    """回验失败 → 打回重抽 1 次 → 再失败判 unknown，不得带未验证引文出场。"""
    f = _field("hesitation", "犹豫期")
    bad = _resp({"field_id": "hesitation", "value": "20日", "tri_state": "present",
                 "evidence": [{"page": 1, "quote": "这句话不在原文里"}]})
    client = QueueClient([bad, bad])
    out = await WindowExtractor(client, "P", "条款.pdf", PAGES).extract(WINDOW, [f])
    assert client.calls == 2  # 第二次是带失败反馈的打回重抽
    assert "引文" in client.prompts[1][1]  # 反馈包含失败原因
    rec = out[0]
    assert rec.tri_state == "unknown" and rec.unknown_reason == "quote_mismatch"
    assert rec.value is None and not rec.evidence  # 未验证引文被清空
    assert rec.metadata["rejected_value"] == "20日"  # 裁决线索留痕


async def test_e3_2_quote_mismatch_recovers_on_retry() -> None:
    f = _field("hesitation", "犹豫期")
    bad = _resp({"field_id": "hesitation", "value": "20日", "tri_state": "present",
                 "evidence": [{"page": 1, "quote": "编造的引文"}]})
    good = _resp(_ok_item("hesitation", "20日", "犹豫期为20日"))
    client = QueueClient([bad, good])
    out = await WindowExtractor(client, "P", "条款.pdf", PAGES).extract(WINDOW, [f])
    assert out[0].tri_state == "present" and out[0].value == "20日"


async def test_e3_2_present_without_evidence_is_rejected() -> None:
    f = _field("hesitation", "犹豫期")
    no_ev = _resp({"field_id": "hesitation", "value": "20日", "tri_state": "present",
                   "evidence": []})
    client = QueueClient([no_ev, no_ev])
    out = await WindowExtractor(client, "P", "条款.pdf", PAGES).extract(WINDOW, [f])
    assert out[0].tri_state == "unknown"  # 不得带着无证据的 present 出场（E3.2）


async def test_e3_3_placeholder_cleaned_to_unknown() -> None:
    f = _field("deductible", "免赔额")
    resp = _resp(_ok_item("deductible", "详见费率表", "免赔额为1万元"))
    client = QueueClient([resp])
    out = await WindowExtractor(client, "P", "条款.pdf", PAGES).extract(WINDOW, [f])
    rec = out[0]
    assert client.calls == 1  # 清洗命中不打回（走补漏流程）
    assert rec.tri_state == "unknown" and rec.unknown_reason == "placeholder"
    assert rec.source_pointer == "详见费率表"


async def test_e3_4_type_validation_rejects_then_unknown() -> None:
    f = _field("deductible", "免赔额", value_type="number")
    bad = _resp(_ok_item("deductible", "详见合同约定条款内容", "免赔额为1万元"))
    client = QueueClient([bad, bad])
    out = await WindowExtractor(client, "P", "条款.pdf", PAGES).extract(WINDOW, [f])
    assert client.calls == 2
    assert out[0].tri_state == "unknown" and out[0].unknown_reason == "validation_failed"


def test_e3_4_typed_value_rules() -> None:
    num = _field("d", "免赔额", value_type="number")
    assert validate_typed_value(num, "1万") is None
    assert validate_typed_value(num, "85%") is None
    assert validate_typed_value(num, "以条款为准") is not None
    date = _field("e", "生效日期", value_type="date")
    assert validate_typed_value(date, "2026年1月1日") is None
    assert validate_typed_value(date, "生效即算") is not None


def test_build_windows_greedy_merge() -> None:
    frag = (PageText(page_no=1, text="x" * 300),)
    sections = [(f"s{i}", frag) for i in range(5)]
    windows = build_windows(sections, window_chars=700)
    assert [w.ref for w in windows] == ["s0+s1", "s2+s3", "s4"]


async def test_transport_retry_exponential_then_dead() -> None:
    delays: list[float] = []

    async def fake_sleep(s: float) -> None:
        delays.append(s)

    attempts = 0

    async def always_truncated() -> str:
        nonlocal attempts
        attempts += 1
        raise TruncatedOutputError("截断")

    with pytest.raises(TransportRetryError):
        await with_transport_retry(
            always_truncated, attempts=3, base_delay_s=1.0, sleep=fake_sleep
        )
    assert attempts == 3
    assert delays == [1.0, 4.0]  # 指数退避（可配次数）
