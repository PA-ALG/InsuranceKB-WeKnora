"""005 spec V5/V6：漏抽归因工具（纯确定性）+ 零成本路由修复 + 清洗行为锁定。"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from insurance_harness.compiler.extract import Window, WindowExtractor
from insurance_harness.compiler.llm import ReplayClient, request_key
from insurance_harness.compiler.models import PredRecord
from insurance_harness.compiler.recall_attribution import (
    CLEANING_KILL,
    EXTRACT_EMPTY,
    NO_EVIDENCE_PAGE,
    ROUTING_MISS,
    attribute_misses,
    dataset_routing_lookup,
    render_attribution,
)
from insurance_harness.compiler.routing_data import (
    GROUP_KEYWORD_SUPPLEMENTS_005,
    GROUP_KEYWORDS,
    GROUP_KEYWORDS_004,
    compile_group_keywords,
)
from insurance_harness.compiler.sections import DocSection, route_groups, split_sections
from insurance_harness.goldenset.pdf import PageText, extract_pages
from insurance_harness.goldenset.records import Evidence, GoldenRecord
from insurance_harness.schemas import FieldSpec

DATASET = Path(__file__).resolve().parents[2] / "dataset/shouxian_product"
CREATED = datetime(2026, 7, 12, tzinfo=UTC)


def _golden(
    field_id: str,
    field_name: str,
    *,
    doc: str = "保险条款.pdf",
    pages: tuple[int, ...] = (1,),
    tri: str = "present",
) -> GoldenRecord:
    return GoldenRecord(
        product_id="P1",
        product_name="产品P1",
        doc=doc,
        field_id=field_id,
        field_name=field_name,
        value="值" if tri == "present" else None,
        tri_state=tri,  # type: ignore[arg-type]
        evidence=[Evidence(page=p, quote="证据") for p in pages],
        annotator_model="t",
        schema_version="v1.1+t",
        created_at=CREATED,
    )


def _pred_unknown(field_id: str, unknown_reason: str | None = None) -> PredRecord:
    return PredRecord(
        product_id="P1",
        product_name="产品P1",
        doc="保险条款.pdf",
        field_id=field_id,
        field_name=field_id,
        value=None,
        tri_state="unknown",
        annotator_model="t",
        schema_version="v1.1+t",
        created_at=CREATED,
        unknown_reason=unknown_reason,  # type: ignore[arg-type]
    )


def _section(section_id: str, page: int) -> DocSection:
    return DocSection(
        section_id=section_id,
        title=f"第{section_id}节",
        headings=(f"第{section_id}节",),
        fragments=(PageText(page_no=page, text="正文"),),
    )


# --- V5.1/V5.2/V5.4 归因分类（注入式路由查询，无 PDF） ---


def test_v5_1_categories_routing_miss_extract_empty_cleaning_kill() -> None:
    sections = [_section("s001", 1), _section("s002", 5)]
    by_group = {"basic_info": ("s001",), "claim_service": ()}

    def lookup(
        product: str, doc: str
    ) -> tuple[list[DocSection], dict[str, tuple[str, ...]]]:
        return sections, by_group

    golden = [
        _golden("f_route", "犹豫期", pages=(5,)),  # basic_info 组未路由到第 5 页 → routing_miss
        _golden("f_empty", "犹豫期", pages=(1,)),  # 已路由仍空 → extract_empty
        _golden("f_clean", "犹豫期", pages=(1,)),  # unknown_reason=placeholder → cleaning_kill
        _golden("f_noev", "犹豫期", pages=()),  # 金标无证据页 → no_evidence_page（V5.4）
        _golden("f_hit", "犹豫期", pages=(1,)),  # 预测 present → 不进归因
        _golden("f_disp", "犹豫期", pages=(1,)),  # disputed → 不进归因
    ]
    golden[-1] = golden[-1].model_copy(update={"disputed": True})
    pred = [
        _pred_unknown("f_route"),
        _pred_unknown("f_empty"),
        _pred_unknown("f_clean", unknown_reason="placeholder"),
        _pred_unknown("f_noev"),
        _pred_unknown("f_hit").model_copy(update={"tri_state": "present", "value": "20日"}),
        # f_disp：pred 缺行也不进归因（disputed 金标排除）
    ]
    report = attribute_misses(golden, pred, lookup)
    by_id = {i.field_id: i for i in report.items}
    assert by_id["f_route"].category == ROUTING_MISS
    assert by_id["f_empty"].category == EXTRACT_EMPTY
    assert by_id["f_clean"].category == CLEANING_KILL
    assert by_id["f_noev"].category == NO_EVIDENCE_PAGE
    assert "f_hit" not in by_id and "f_disp" not in by_id
    assert report.stats == {
        ROUTING_MISS: 1, EXTRACT_EMPTY: 1, CLEANING_KILL: 1, NO_EVIDENCE_PAGE: 1,
    }
    md = render_attribution(report)
    assert "routing_miss" in md and "犹豫期(f_route)" in md  # V5.3 逐条清单


def test_v5_1_missing_pred_row_counts_as_miss() -> None:
    def lookup(
        product: str, doc: str
    ) -> tuple[list[DocSection], dict[str, tuple[str, ...]]]:
        return [_section("s001", 1)], {"basic_info": ("s001",)}

    report = attribute_misses([_golden("f1", "犹豫期", pages=(1,))], [], lookup)
    assert len(report.items) == 1 and report.items[0].category == EXTRACT_EMPTY


def test_v5_2_dataset_lookup_recomputes_routing_when_no_manifest_record() -> None:
    pdf = DATASET / "平安守护百分百（2026）两全保险/保险条款.pdf"
    if not pdf.exists():
        pytest.skip(f"样本缺失：{pdf}")
    lookup = dataset_routing_lookup(DATASET)
    routed = lookup("平安守护百分百（2026）两全保险", "保险条款.pdf")
    assert routed is not None
    sections, by_group = routed
    assert sections and set(by_group) == {
        "basic_info", "coverage", "cost_rules", "exclusion_uw",
        "claim_service", "contract_admin", "disease_definition",
    }
    assert lookup("产品不存在", "保险条款.pdf") is None


# --- V6.1/V6.2 零成本路由修复 ---


def test_v6_1_supplements_fix_rate_table_payment_term_routing() -> None:
    """修复前（004 关键词）交费期限的费率表首页不在 basic_info 路由；修复后进入。"""
    pdf = DATASET / "平安盛世金越（尊享版26）终身寿险/费率表.pdf"
    if not pdf.exists():
        pytest.skip(f"样本缺失：{pdf}")
    sections = split_sections(extract_pages(pdf))

    def covered(keywords: dict[str, re.Pattern[str] | None]) -> bool:
        routing = route_groups(sections, keywords=keywords)
        routed = set(routing.by_group["basic_info"])
        return any(
            s.section_id in routed and s.page_first <= 1 <= s.page_last for s in sections
        )

    assert not covered(GROUP_KEYWORDS_004)  # before：漏抽归因 routing_miss 的现场
    assert covered(GROUP_KEYWORDS)  # after：005 补充生效


def test_v6_1_supplements_fix_claim_filing_routing() -> None:
    """e生保条款 P24 保险金申请材料章节：修复后进入 claim_service 路由。"""
    pdf = DATASET / "平安e生保（尊享版）医疗保险/保险条款.pdf"
    if not pdf.exists():
        pytest.skip(f"样本缺失：{pdf}")
    sections = split_sections(extract_pages(pdf))
    for keywords, expect in ((GROUP_KEYWORDS_004, False), (GROUP_KEYWORDS, True)):
        routing = route_groups(sections, keywords=dict(keywords))
        routed = set(routing.by_group["claim_service"])
        got = any(
            s.section_id in routed and s.page_first <= 24 <= s.page_last for s in sections
        )
        assert got is expect


def test_v6_1_supplement_data_shape() -> None:
    """补充词独立存放且叠加编译正确（before/after 可复算）。"""
    assert set(GROUP_KEYWORD_SUPPLEMENTS_005) <= {
        "basic_info", "coverage", "cost_rules", "exclusion_uw",
        "claim_service", "contract_admin", "disease_definition",
    }
    plain = compile_group_keywords()
    patched = compile_group_keywords(GROUP_KEYWORD_SUPPLEMENTS_005)
    pattern = patched["basic_info"]
    assert pattern is not None and pattern.search("趸交") and pattern.search("费率表")
    base = plain["basic_info"]
    assert base is not None and not base.search("趸交")
    assert patched["coverage"] is None  # coverage 语义不变：扫描全部章节


# --- V6.3 清洗行为 ReplayClient 锁定（cleaning_kill=0 → 不改正则，锁现状） ---


PAGES = [PageText(page_no=1, text="犹豫期为20日。免赔额为1万元。等待期为90天。")]
WINDOW = Window(ref="s001", fragments=tuple(PAGES))
FIELDS = [
    FieldSpec(name="免赔额", field_id="deductible", source_sheet="t"),
    FieldSpec(name="犹豫期", field_id="hesitation", source_sheet="t"),
]


class _Recording:
    """录制包装：把 ScriptedResponse 写为 ReplayClient 夹具。"""

    def __init__(self, fixtures: Path, response: str) -> None:
        self._fixtures = fixtures
        self._response = response

    async def complete(self, system: str, user: str) -> str:
        (self._fixtures / f"{request_key(system, user)}.txt").write_text(
            self._response, encoding="utf-8"
        )
        return self._response


async def test_v6_3_replay_client_locks_cleaning_behavior(tmp_path: Path) -> None:
    """占位值→unknown（placeholder），真值不误杀——ReplayClient 回放验证（零模型）。"""
    response = json.dumps(
        [
            {"field_id": "deductible", "value": "详见费率表", "tri_state": "present",
             "evidence": [{"page": 1, "quote": "免赔额为1万元"}]},
            {"field_id": "hesitation", "value": "20日", "tri_state": "present",
             "evidence": [{"page": 1, "quote": "犹豫期为20日"}]},
        ],
        ensure_ascii=False,
    )
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    # 先录制（确定性 ScriptedResponse），再用 ReplayClient 复放
    await WindowExtractor(_Recording(fixtures, response), "P", "条款.pdf", PAGES).extract(
        WINDOW, FIELDS
    )
    replay = ReplayClient(fixtures)
    out = await WindowExtractor(replay, "P", "条款.pdf", PAGES).extract(WINDOW, FIELDS)
    by_id = {c.field_id: c for c in out}
    dedu = by_id["deductible"]  # "详见费率表" 占位值 → unknown + 指针（不是 absent）
    assert dedu.tri_state == "unknown" and dedu.unknown_reason == "placeholder"
    assert dedu.source_pointer == "详见费率表"
    hes = by_id["hesitation"]  # 真值不误杀
    assert hes.tri_state == "present" and hes.value == "20日"
    assert replay.calls == 1
