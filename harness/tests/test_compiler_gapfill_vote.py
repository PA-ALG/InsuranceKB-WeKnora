"""spec E4：补漏 pass（aliases 检索+判断题）与高风险字段 3 采样投票。"""

import json

from insurance_harness.compiler.gapfill import gapfill_field, gapfill_keywords, rank_sections
from insurance_harness.compiler.models import FieldCandidate
from insurance_harness.compiler.sections import split_sections
from insurance_harness.compiler.voting import vote_field
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.schemas import FieldSpec

PAGES = [
    PageText(
        page_no=1,
        text="第一条 投保范围\n投保年龄为出生满30日至65周岁。\n"
        "第二条 保费豁免\n投保人身故或全残的，免交保险费，本合同继续有效。",
    ),
    PageText(page_no=2, text="第三条 等待期\n本合同等待期为90天。"),
]
SECTIONS = [("条款.pdf", s) for s in split_sections(PAGES, target_chars=200, min_chars=0)]
PAGES_BY_DOC = {"条款.pdf": PAGES}

WAIVER = FieldSpec(
    name="投被保人豁免", field_id="premium_waiver", risk_level="high", source_sheet="t"
)
WAITING = FieldSpec(name="等待期", field_id="waiting_period", risk_level="high", source_sheet="t")


class QueueClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0
        self.prompts: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        self.prompts.append((system, user))
        return self._responses.pop(0)


def _resp(fid: str, value: str | None, tri: str, page: int = 0, quote: str = "") -> str:
    ev = [{"page": page, "quote": quote}] if quote else []
    return json.dumps(
        [{"field_id": fid, "value": value, "tri_state": tri, "evidence": ev}],
        ensure_ascii=False,
    )


def test_e4_1_alias_retrieval_ranks_relevant_sections() -> None:
    keywords = gapfill_keywords(WAIVER)
    assert "免交保险费" in keywords  # 06 A8 同义词库种子
    ranked = rank_sections(WAIVER, SECTIONS, top_n=3)
    assert ranked, "豁免同义词应命中候选章节"
    assert "免交保险费" in ranked[0][1].text  # 最相关章节排第一


async def test_e4_1_gapfill_present_with_verified_quote_is_medium() -> None:
    client = QueueClient(
        [_resp("premium_waiver", "投保人身故或全残豁免保费", "present", 1,
               "免交保险费，本合同继续有效")]
    )
    cand = await gapfill_field(client, "P", WAIVER, SECTIONS, PAGES_BY_DOC)
    assert cand.tri_state == "present" and cand.origin == "gapfill"
    assert cand.confidence == "medium"  # 补漏得出 = medium（proposal §7）


async def test_e4_1_all_not_mentioned_stays_unknown() -> None:
    """三态纪律：所有候选段落"未提及" → 维持 unknown，绝不输出"无豁免"。"""
    n = len(rank_sections(WAIVER, SECTIONS, top_n=3))
    client = QueueClient([_resp("premium_waiver", None, "unknown")] * n)
    cand = await gapfill_field(client, "P", WAIVER, SECTIONS, PAGES_BY_DOC)
    assert cand.tri_state == "unknown" and cand.unknown_reason == "not_found"


async def test_e4_1_no_candidate_sections_no_llm_call() -> None:
    field = FieldSpec(name="完全无关字段XYZ", field_id="nonexistent", source_sheet="t")
    client = QueueClient([])
    cand = await gapfill_field(client, "P", field, SECTIONS, PAGES_BY_DOC)
    assert client.calls == 0  # 无候选章节不调 LLM
    assert cand.unknown_reason == "no_candidate_sections"


async def test_e4_1_unverified_gapfill_quote_treated_as_no_clue() -> None:
    n = len(rank_sections(WAIVER, SECTIONS, top_n=3))
    responses = [_resp("premium_waiver", "有豁免", "present", 1, "编造的引文")] * n
    client = QueueClient(responses)
    cand = await gapfill_field(client, "P", WAIVER, SECTIONS, PAGES_BY_DOC)
    assert cand.tri_state == "unknown"  # E3.2：未验证引文不得出场


def _base_candidate() -> FieldCandidate:
    return FieldCandidate(
        field_id="waiting_period", field_name="等待期", group="basic_info",
        doc="条款.pdf", value="90天", tri_state="present",
        evidence=[{"page": 2, "quote": "等待期为90天"}],  # type: ignore[list-item]
    )


async def test_e4_2_vote_unanimous_high_confidence() -> None:
    resp = _resp("waiting_period", "90天", "present", 2, "等待期为90天")
    client = QueueClient([resp, resp, resp])
    out = await vote_field(client, "P", WAITING, _base_candidate(), PAGES)
    assert client.calls == 3  # 3 采样
    assert out.vote_agreement == 3 and out.confidence == "high"
    # 3 个 prompt 变体互不相同（独立采样的多样性来源）
    users = [u for _, u in client.prompts]
    assert len(set(users)) == 3


async def test_e4_2_vote_majority_medium() -> None:
    agree = _resp("waiting_period", "90天", "present", 2, "等待期为90天")
    differ = _resp("waiting_period", "180天", "present", 2, "等待期为90天")
    client = QueueClient([agree, differ, agree])
    out = await vote_field(client, "P", WAITING, _base_candidate(), PAGES)
    assert out.vote_agreement == 2 and out.confidence == "medium"
    assert out.value == "90天"


async def test_e4_2_three_way_disagreement_low_confidence_with_candidates() -> None:
    client = QueueClient(
        [
            _resp("waiting_period", "90天", "present", 2, "等待期为90天"),
            _resp("waiting_period", "180天", "present", 2, "等待期为90天"),
            _resp("waiting_period", "30天", "present", 2, "等待期为90天"),
        ]
    )
    out = await vote_field(client, "P", WAITING, _base_candidate(), PAGES)
    assert out.confidence == "low" and out.vote_agreement == 1
    assert set(out.metadata["vote_candidates"]) == {"90天", "180天", "30天"}  # E4.2 留痕


async def test_e4_2_vote_values_compared_after_normalization() -> None:
    """90天 与 90 天/90日？——归一化等价（数值/空白）不判分歧。"""
    client = QueueClient(
        [
            _resp("waiting_period", "90天", "present", 2, "等待期为90天"),
            _resp("waiting_period", "90 天", "present", 2, "等待期为90天"),
            _resp("waiting_period", "90天", "present", 2, "等待期为90天"),
        ]
    )
    out = await vote_field(client, "P", WAITING, _base_candidate(), PAGES)
    assert out.vote_agreement == 3 and out.confidence == "high"
