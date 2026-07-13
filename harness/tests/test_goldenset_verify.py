"""spec G2.2 / G2.4：引文回验与 meta 比对。"""

from datetime import UTC, datetime

from insurance_harness.goldenset import (
    Evidence,
    GoldenRecord,
    PageText,
    compare_with_meta,
    verify_quotes,
)
from insurance_harness.goldenset.normalize import quote_in_page, values_equal


def _rec(field_id: str, value: str | None, tri: str, evidence: list[Evidence]) -> GoldenRecord:
    return GoldenRecord(
        product_id="1847H",
        product_name="平安盛世金越养老年金保险（分红型）",
        doc="保险条款.pdf",
        field_id=field_id,
        field_name={"zh_x": "犹豫期", "regulatory_filing_no": "条款备案/批复文号",
                    "zh_code": "险种代码"}.get(field_id, field_id),
        value=value,
        tri_state=tri,  # type: ignore[arg-type]
        evidence=evidence,
        annotator_model="test",
        schema_version="v1.1+test",
        created_at=datetime.now(UTC),
    )


PAGES = [
    PageText(page_no=1, text="犹豫期为 20 日。自本合同生效之日起。"),
    PageText(page_no=2, text="其他内容"),
]


def test_g2_2_quote_matches_with_normalization() -> None:
    # 引文与原文的空白/全角差异不影响回验
    assert quote_in_page("犹豫期为20日", PAGES[0].text)
    rec = _rec("zh_x", "20日", "present", [Evidence(page=1, quote="犹豫期为 20日。")])
    verify_quotes([rec], PAGES)
    assert rec.disputed is False


def test_g2_2_quote_mismatch_marks_disputed() -> None:
    rec = _rec("zh_x", "30日", "present", [Evidence(page=1, quote="犹豫期为 30 日")])
    verify_quotes([rec], PAGES)
    assert rec.disputed and rec.disputed_reason == "quote_mismatch"


def test_g2_2_wrong_page_marks_disputed() -> None:
    rec = _rec("zh_x", "20日", "present", [Evidence(page=9, quote="犹豫期为 20 日")])
    verify_quotes([rec], PAGES)
    assert rec.disputed and rec.disputed_reason == "quote_mismatch"


def test_g2_2_present_without_evidence_marks_disputed() -> None:
    rec = _rec("zh_x", "20日", "present", [])
    verify_quotes([rec], PAGES)
    assert rec.disputed and rec.disputed_reason == "no_evidence"


def test_g2_2_unknown_needs_no_evidence() -> None:
    rec = _rec("zh_x", None, "unknown", [])
    verify_quotes([rec], PAGES)
    assert rec.disputed is False


def test_g2_4_meta_mismatch() -> None:
    meta = {"planCode": "1847H", "reportPreparedFileCode": "平保寿发〔2026〕45号"}
    ok = _rec("zh_code", "1847H", "present", [Evidence(page=1, quote="犹豫期")])
    ok.field_name = "险种代码"
    bad = _rec(
        "regulatory_filing_no", "平保寿发〔2025〕1号", "present", [Evidence(page=1, quote="犹豫期")]
    )
    bad.field_name = "条款备案/批复文号"
    compare_with_meta([ok, bad], meta)
    assert ok.disputed is False
    assert bad.disputed and bad.disputed_reason == "meta_mismatch"


def test_values_equal_normalization() -> None:
    assert values_equal("30万", "300000")
    assert values_equal("2026年4月8日", "2026-04-08")
    assert values_equal("是", "有")
    assert values_equal("85%", "0.85")
    assert not values_equal("20日", "10日")
    assert values_equal(None, None)
    assert not values_equal("x", None)
