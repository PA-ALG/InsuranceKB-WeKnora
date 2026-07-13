"""spec F4：文档可喂性评分（确定性检查项、阈值、隔离区目录机制）。"""

import json
from pathlib import Path

from insurance_harness.compiler.feedability import (
    FeedabilityReport,
    render_feedability,
    score_feedability,
    write_quarantine,
)
from insurance_harness.compiler.templates import TableGrid
from insurance_harness.goldenset.pdf import PageText

GOOD_PAGES = [
    PageText(page_no=1, text="第一条 保险责任\n被保险人身故，我们按基本保险金额给付身故保险金。"),
    PageText(page_no=2, text="第二条 责任免除\n因下列情形之一身故的，我们不承担给付责任。"),
]


def _checks(report: FeedabilityReport) -> dict[str, bool]:
    return {c.name: c.ok for c in report.checks}


def test_f4_1_good_doc_scores_full_and_feedable() -> None:
    report = score_feedability("条款.pdf", GOOD_PAGES)
    assert report.score == 1.0 and report.feedable
    assert not report.quarantine_suggested
    assert set(_checks(report)) == {"garbled", "empty_pages", "oversized_page", "truncated_tail"}


def test_f4_1_garbled_and_empty_and_oversized_detected() -> None:
    garbled = [PageText(page_no=1, text="(cid:123)(cid:456)" * 50 + "正文")]
    assert not _checks(score_feedability("g.pdf", garbled))["garbled"]

    empties = [PageText(page_no=1, text="正常页面文本" * 5)] + [
        PageText(page_no=i, text="") for i in range(2, 6)
    ]
    assert not _checks(score_feedability("e.pdf", empties))["empty_pages"]

    oversized = [PageText(page_no=1, text="字" * 20_000 + "。")]
    assert not _checks(score_feedability("o.pdf", oversized))["oversized_page"]


def test_f4_1_truncated_tail_detected() -> None:
    truncated = [PageText(page_no=1, text="给付条件包括：被保险人于合同生效后，")]
    assert not _checks(score_feedability("t.pdf", truncated))["truncated_tail"]
    assert _checks(score_feedability("ok.pdf", GOOD_PAGES))["truncated_tail"]


def test_f4_1_table_header_legality_when_tables_given() -> None:
    ok_grid = TableGrid(rows=(("年龄", "保费"), ("0", "100")))
    bad_grid = TableGrid(rows=(("", ""), ("0", "100")))
    report = score_feedability("r.pdf", GOOD_PAGES, tables=[ok_grid, bad_grid])
    checks = _checks(report)
    assert "table_headers" in checks and not checks["table_headers"]
    assert _checks(score_feedability("r.pdf", GOOD_PAGES, tables=[ok_grid]))["table_headers"]


def test_f4_2_threshold_drives_quarantine_suggestion() -> None:
    garbled_truncated = [PageText(page_no=1, text="(cid:1)" * 100 + "所交保费的，")]
    report = score_feedability("bad.pdf", garbled_truncated, threshold=0.75)
    assert report.score < 0.75 and report.quarantine_suggested
    # 阈值可配：放低阈值则不建议隔离
    lax = score_feedability("bad.pdf", garbled_truncated, threshold=0.4)
    assert lax.feedable


def test_f4_3_quarantine_write_keeps_audit_trail(tmp_path: Path) -> None:
    report = score_feedability(
        "费率表.pdf", [PageText(page_no=1, text="(cid:1)" * 100 + "，")]
    )
    path = write_quarantine(tmp_path / ".rejections", "产品X", "费率表.pdf", report)
    assert path == tmp_path / ".rejections" / "产品X" / "费率表.pdf.rejection.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["product"] == "产品X" and data["report"]["score"] < 1.0
    assert data["report"]["checks"], "审计痕迹必须保留逐项检查明细（可救回）"


def test_f4_2_render_report_marks_failures() -> None:
    good = score_feedability("好.pdf", GOOD_PAGES)
    bad = score_feedability("坏.pdf", [PageText(page_no=1, text="(cid:1)" * 100 + "，")])
    md = render_feedability([good, bad])
    assert "好.pdf" in md and "✅" in md
    assert "坏.pdf" in md and "建议隔离" in md
