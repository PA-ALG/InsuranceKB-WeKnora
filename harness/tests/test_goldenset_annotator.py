"""spec G2.1/G2.6：标注 Agent 端到端（ReplayClient/桩客户端 + 小夹具）。"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from insurance_harness.goldenset import GoldenAnnotator, PageText, ReplayClient
from insurance_harness.goldenset.annotator import extract_json_array, request_key
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry

FIELDS = (
    FieldSpec(name="犹豫期", field_id="hesitation_period", source_sheet="t"),
    FieldSpec(name="等待期", field_id="waiting_period", risk_level="high", source_sheet="t"),
    FieldSpec(name="满期返还", field_id="maturity_benefit", source_sheet="t"),
)
LINE = ProductLineSchema(line_key="t", sheet_name="测试", fields=FIELDS)
REGISTRY = SchemaRegistry(version="v1.1+testtesttest", lines={"t": LINE}, glossary=())
PAGES = [
    PageText(page_no=1, text="犹豫期为20日。" * 20),
    PageText(page_no=2, text="等待期为90天。本产品无满期返还责任。" * 10),
]
CREATED = datetime(2026, 7, 11, tzinfo=UTC)

GOOD_RESPONSE = json.dumps(
    [
        {"field_id": "hesitation_period", "value": "20日", "tri_state": "present",
         "evidence": [{"page": 1, "quote": "犹豫期为20日"}], "reasoning": "条款明示"},
        {"field_id": "waiting_period", "value": "90天", "tri_state": "present",
         "evidence": [{"page": 2, "quote": "等待期为90天"}], "reasoning": "条款明示"},
        {"field_id": "maturity_benefit", "value": None, "tri_state": "absent_explicitly",
         "evidence": [{"page": 2, "quote": "本产品无满期返还责任"}], "reasoning": "明确排除"},
    ],
    ensure_ascii=False,
)


class QueueClient:
    """按队列返回响应的桩客户端（Protocol 鸭子实现）。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self._responses.pop(0)


def _annotator(client: QueueClient | ReplayClient) -> GoldenAnnotator:
    return GoldenAnnotator(client, REGISTRY, annotator_model="claude-test")


async def test_g2_1_normal_annotation() -> None:
    client = QueueClient([GOOD_RESPONSE])
    records = await _annotator(client).annotate_document(
        "P1", "测试产品", "条款.pdf", PAGES, LINE, CREATED
    )
    assert client.calls == 1  # 3 字段 ≤ 批大小，单次调用
    assert {r.field_id for r in records} == {f.field_id for f in FIELDS}
    hp = next(r for r in records if r.field_id == "hesitation_period")
    assert hp.tri_state == "present" and hp.value == "20日" and hp.evidence[0].page == 1
    assert hp.schema_version == "v1.1+testtesttest" and hp.annotator_model == "claude-test"
    mb = next(r for r in records if r.field_id == "maturity_benefit")
    assert mb.tri_state == "absent_explicitly" and mb.evidence  # G2.3：明确排除也要证据


async def test_g2_1_missing_field_marked_disputed() -> None:
    partial = json.dumps([json.loads(GOOD_RESPONSE)[0]], ensure_ascii=False)
    records = await _annotator(QueueClient([partial])).annotate_document(
        "P1", "测试产品", "条款.pdf", PAGES, LINE, CREATED
    )
    wp = next(r for r in records if r.field_id == "waiting_period")
    assert wp.tri_state == "unknown" and wp.disputed and wp.disputed_reason == "missing_in_response"


async def test_g2_6_parse_failure_retries_then_disputes() -> None:
    client = QueueClient(["不是 JSON", "还是不是 JSON"])
    records = await _annotator(client).annotate_document(
        "P1", "测试产品", "条款.pdf", PAGES, LINE, CREATED
    )
    assert client.calls == 2  # 重试一次
    assert all(r.tri_state == "unknown" and r.disputed_reason == "parse_failed" for r in records)


async def test_g2_6_retry_succeeds_on_second_attempt() -> None:
    client = QueueClient(["garbage", f"```json\n{GOOD_RESPONSE}\n```"])
    records = await _annotator(client).annotate_document(
        "P1", "测试产品", "条款.pdf", PAGES, LINE, CREATED
    )
    assert client.calls == 2
    assert not any(r.disputed for r in records)


def test_extract_json_array_adversarial() -> None:
    assert extract_json_array('前言```json\n[{"a": 1}]\n```后记') == [{"a": 1}]
    assert extract_json_array('[{"s": "含]括号[的字符串"}]') == [{"s": "含]括号[的字符串"}]
    assert extract_json_array("完全没有数组") is None
    assert extract_json_array('[{"未闭合": 1}') is None
    assert extract_json_array('"只是字符串"') is None


async def test_replay_client_roundtrip(tmp_path: Path) -> None:
    key = request_key("sys", "user")
    (tmp_path / f"{key}.txt").write_text(GOOD_RESPONSE, encoding="utf-8")
    client = ReplayClient(tmp_path)
    assert await client.complete("sys", "user") == GOOD_RESPONSE
    with pytest.raises(FileNotFoundError, match="缺少夹具"):
        await client.complete("sys", "其他 user")
