"""spec F2：模板归纳器（确定性锚点挖掘 + 全产品回放验证 + 草案自验 + 润色 stub）。"""

from pathlib import Path

import pytest

from insurance_harness.compiler.templates import (
    InductionError,
    ProductDocInput,
    TableGrid,
    dump_template_yaml,
    induce_template,
    parse_template,
    render_induction_report,
    write_polish_queue,
)
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import Evidence, GoldenRecord

DOC = "费率表.pdf"
FAMILY = "fam-0123456789ab"

_RATE_TEXT_A = (
    "《产品A终身寿险》年交费率表\n（每万元基本保险金额）\n男性\n单位：人民币元\n"
    "交费期间\n趸交 3年 6年\n投保年龄\n0 11389 3943 1979\n"
    "生效日期：2026年1月1日\n注：若本主险合同被保险人为两人，按年龄较小被保人计算保费。"
)
_RATE_TEXT_B = (
    "《产品B终身寿险》年交费率表\n（每万元基本保险金额）\n男性\n单位：人民币元\n"
    "交费期间\n趸交 3年 6年\n投保年龄\n0 11541 3955 2012\n"
    "生效日期：2027年3月5日\n注：若本主险合同被保险人为两人，按年龄较小被保人计算保费。"
)

_GRID = TableGrid(
    rows=(
        ("交费期间\n投保年龄", "趸交", "3年", "6年"),
        ("0", "11389", "3943", "1979"),
    )
)


class FakeProvider:
    """注入式表格 provider（F5.1 协议）：按 pdf 路径返回固定表格。"""

    def __init__(self, grids_by_path: dict[Path, list[TableGrid]]) -> None:
        self._grids = grids_by_path

    def extract_tables(self, pdf_path: Path, page_no: int) -> list[TableGrid]:
        return self._grids.get(pdf_path, []) if page_no == 1 else []


def _golden(
    product: str, field_id: str, field_name: str, value: str, quote: str, page: int = 1
) -> GoldenRecord:
    from datetime import UTC, datetime

    return GoldenRecord(
        product_id=product,
        product_name=product,
        doc=DOC,
        field_id=field_id,
        field_name=field_name,
        value=value,
        tri_state="present",
        evidence=[Evidence(page=page, quote=quote)],
        annotator_model="gs",
        schema_version="v1.1",
        created_at=datetime.now(UTC),
    )


def _inputs() -> list[ProductDocInput]:
    def build(product: str, text: str, effective: str) -> ProductDocInput:
        return ProductDocInput(
            product_name=product,
            pages=[PageText(page_no=1, text=text)],
            goldens=[
                _golden(product, "zh_pay", "交费期限", "趸交、3年、6年", "趸交 3年 6年"),
                _golden(product, "zh_main", "主附加险", "主险",
                        "注：若本主险合同被保险人为两人，按年龄较小被保人计算保费。"),
                _golden(product, "zh_eff", "条款生效日期", effective,
                        f"生效日期：{effective}"),
                # 长文本总结值（不是原文子串）→ not_anchorable
                _golden(product, "zh_feat", "产品特色",
                        f"{product}的三大特色：保障高、现价稳、可贷款", "年交费率表"),
            ],
            pdf_path=Path(f"/fake/{product}/{DOC}"),
        )

    return [
        build("产品A", _RATE_TEXT_A, "2026年1月1日"),
        build("产品B", _RATE_TEXT_B, "2027年3月5日"),
    ]


def _provider() -> FakeProvider:
    return FakeProvider(
        {
            Path(f"/fake/产品A/{DOC}"): [_GRID],
            Path(f"/fake/产品B/{DOC}"): [
                TableGrid(
                    rows=(
                        ("交费期间\n投保年龄", "趸交", "3年", "6年"),
                        ("0", "11541", "3955", "2012"),
                    )
                )
            ],
        }
    )


def test_f2_1_requires_two_products() -> None:
    with pytest.raises(InductionError, match="≥2"):
        induce_template(DOC, _inputs()[:1], family_id=FAMILY)


def test_f2_2_table_anchor_mined_for_column_field() -> None:
    result = induce_template(DOC, _inputs(), FAMILY, provider=_provider())
    by_id = {f.field_id: f for f in result.template.fields}
    pay = by_id["zh_pay"]
    assert pay.anchors.table_columns is not None
    assert pay.anchors.table_columns.header_contains == "趸交"
    assert pay.anchors.pages == (1,)
    report = {r.field_id: r for r in result.report}
    assert report["zh_pay"].anchor_type == "table_columns"
    assert report["zh_pay"].hit_rate == 1.0 and report["zh_pay"].published


def test_f2_2_regex_anchor_with_context_and_digit_generalization() -> None:
    result = induce_template(DOC, _inputs(), FAMILY, provider=_provider())
    by_id = {f.field_id: f for f in result.template.fields}
    # 枚举值：前文上下文 + 值捕获
    assert by_id["zh_main"].anchors.regex is not None
    # 数字泛化：产品 A 的日期模式必须在产品 B 上捕获出 B 的金标值
    import re

    eff = by_id["zh_eff"].anchors.regex
    assert eff is not None
    m = re.search(eff, _RATE_TEXT_B)
    assert m is not None and m.group(1) == "2027年3月5日"


def test_f2_2_unanchorable_field_reported_not_published() -> None:
    result = induce_template(DOC, _inputs(), FAMILY, provider=_provider())
    report = {r.field_id: r for r in result.report}
    assert not report["zh_feat"].published
    assert "not_anchorable" in report["zh_feat"].note
    assert "zh_feat" not in {f.field_id for f in result.template.fields}


def test_f2_3_anchor_must_hit_all_products() -> None:
    # 产品 B 无该字段的可复原表格（provider 只给产品 A）→ 表格锚点命中率 <1.0，
    # 正则也无法复原（值不在 B 文本中）→ 不发布
    inputs = _inputs()
    inputs[1] = inputs[1].model_copy(
        update={
            "goldens": [
                g if g.field_id != "zh_pay" else g.model_copy(update={"value": "月交、季交"})
                for g in inputs[1].goldens
            ]
        }
    )
    result = induce_template(DOC, inputs, FAMILY, provider=_provider())
    report = {r.field_id: r for r in result.report}
    assert not report["zh_pay"].published


def test_f2_2_support_below_min_not_induced() -> None:
    inputs = _inputs()
    inputs[1] = inputs[1].model_copy(
        update={"goldens": [g for g in inputs[1].goldens if g.field_id != "zh_main"]}
    )
    result = induce_template(DOC, inputs, FAMILY, provider=_provider())
    report = {r.field_id: r for r in result.report}
    assert not report["zh_main"].published and "产品数 1" in report["zh_main"].note


def test_f2_4_draft_yaml_roundtrip_passes_loader(tmp_path: Path) -> None:
    result = induce_template(DOC, _inputs(), FAMILY, provider=_provider())
    assert result.template.status == "draft"
    assert result.template.induced_from.products == ("产品A", "产品B")
    text = dump_template_yaml(result.template)
    import yaml

    reparsed = parse_template(yaml.safe_load(text), "draft.yaml")
    assert reparsed == result.template
    # few_shots 来自金标真实 (page, quote, value)
    pay = {f.field_id: f for f in reparsed.fields}["zh_pay"]
    assert pay.few_shots[0].quote == "趸交 3年 6年"
    # 归纳报告可渲染
    md = render_induction_report(result)
    assert "族内命中率" in md and "not_anchorable" in md


def test_f2_5_polish_stub_writes_queue_without_model_call(tmp_path: Path) -> None:
    result = induce_template(DOC, _inputs(), FAMILY, provider=_provider())
    path = write_polish_queue(tmp_path / "polish-queue.jsonl", result)
    import json

    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["template_id"] == result.template.template_id
    assert "zh_feat" in row["not_anchorable"]
    from insurance_harness.compiler.templates import apply_polish

    # 无回写文件 → 草案原样返回（stub）
    assert apply_polish(result, None) == result.template
    assert apply_polish(result, tmp_path / "missing.yaml") == result.template
