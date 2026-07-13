"""spec G2.4/G2.5：产品级编排——险种推断、断点续跑、meta 比对接线。"""

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.goldenset import GoldenAnnotator, PageText, annotate_product
from insurance_harness.goldenset.runner import UnknownProductLineError, infer_line_key
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry

FIELDS = (
    FieldSpec(name="险种代码", field_id="plan_code", source_sheet="t"),
    FieldSpec(name="犹豫期", field_id="hesitation_period", source_sheet="t"),
)
LINE = ProductLineSchema(line_key="medical", sheet_name="医疗保险（医疗险）", fields=FIELDS)
REGISTRY = SchemaRegistry(version="v1.1+cachetest00", lines={"medical": LINE}, glossary=())

RESPONSE = json.dumps(
    [
        {"field_id": "plan_code", "value": "1847H", "tri_state": "present",
         "evidence": [{"page": 1, "quote": "产品代码 1847H"}]},
        {"field_id": "hesitation_period", "value": "20日", "tri_state": "present",
         "evidence": [{"page": 1, "quote": "犹豫期为20日"}]},
    ],
    ensure_ascii=False,
)


class CountingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return RESPONSE


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("平安e生保（惠享版）长期医疗保险（费率可调）", "medical"),
        ("平安盛世金越（尊享版26）终身寿险（分红型）", "whole-life"),
        ("平安盛世金越养老年金保险（分红型）", "annuity"),
        ("平安附加（2026）失能收入损失保险", "disability-income"),
        ("平安守护百分百（2026）两全保险", "endowment"),
        ("平安附加（2026）意外伤害保险", "accident"),
    ],
)
def test_infer_line_key(name: str, expected: str) -> None:
    assert infer_line_key(name) == expected


def test_infer_line_key_unknown_raises() -> None:
    with pytest.raises(UnknownProductLineError, match="人工指定"):
        infer_line_key("某来路不明材料")


def _fake_pages(_: Path) -> list[PageText]:
    return [PageText(page_no=1, text="产品代码 1847H。犹豫期为20日。" * 10)]


async def test_g2_5_cache_skips_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("insurance_harness.goldenset.runner.extract_pages", _fake_pages)
    product_dir = tmp_path / "平安测试医疗保险"
    product_dir.mkdir()
    (product_dir / "保险条款.pdf").write_bytes(b"%PDF-fake")
    meta: dict[str, Any] = {"planCode": "1847H"}
    (product_dir / "product_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    cache_dir = tmp_path / ".cache"

    client = CountingClient()
    annotator = GoldenAnnotator(client, REGISTRY, annotator_model="claude-test")
    first = await annotate_product(product_dir, REGISTRY, annotator, cache_dir)
    assert client.calls == 1
    assert first and first[0].product_id == "1847H"  # meta planCode 作为 product_id
    assert not any(r.disputed for r in first)  # 引文回验 + meta 比对通过

    second = await annotate_product(product_dir, REGISTRY, annotator, cache_dir)
    assert client.calls == 1  # G2.5：缓存命中，零模型调用
    assert [r.field_id for r in second] == [r.field_id for r in first]


async def test_meta_mismatch_wired_into_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("insurance_harness.goldenset.runner.extract_pages", _fake_pages)
    product_dir = tmp_path / "平安测试医疗保险"
    product_dir.mkdir()
    (product_dir / "保险条款.pdf").write_bytes(b"%PDF-fake")
    (product_dir / "product_meta.json").write_text(
        json.dumps({"planCode": "9999Z"}), encoding="utf-8"
    )
    annotator = GoldenAnnotator(CountingClient(), REGISTRY, annotator_model="claude-test")
    records = await annotate_product(product_dir, REGISTRY, annotator, tmp_path / ".cache")
    pc = next(r for r in records if r.field_id == "plan_code")
    assert pc.disputed and pc.disputed_reason == "meta_mismatch"  # G2.4
