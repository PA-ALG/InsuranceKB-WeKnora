"""S12a acceptance (protected, written by Claude): the ruled segment scoring of 2026-10-26.

Spec docs/design/slices/S12a-段落评分口径.md §2, §4. Synthetic pages: near copies that differ by
"本" or a footnote mark credit each other (numbers never fold away); headings and reader-guide
lines, footnote blocks and the definitions section, and brochure restatements are neutral where the
rules say so. Without rules the scorer is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.engine import FieldResult
from insurance_harness.eval.segment_rules import ScoringRulesError, load_scoring_rules
from insurance_harness.eval.segment_score import GoldenV2, load_golden_v2, score_selection
from insurance_harness.evidence.segments import SegmentedSource


class Page:
    def __init__(self, document: str, sha: str, page: int, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = document, sha, page, text


TERMS = "保险条款.pdf"
BROCHURE = "产品说明书.pdf"
SOURCE = SegmentedSource(
    [
        Page(
            TERMS,
            "b" * 64,
            1,
            "阅读指引：这部分讲的是本合同的保障内容。\n"  # D1P1S1 reader guide
            "第一条 保险责任\n"  # D1P1S2 heading
            "1.1 等待期 本合同的等待期为90日，自合同生效之日起计算。\n"  # D1P1S3
            "1.2 犹豫期 投保人收到本合同后有15日的犹豫期，可以解除合同并退还保费。\n"  # D1P1S4
            "1.3 宽限期 自应交日起有60日的宽限期，期间发生保险事故我们仍承担保险责任。\n"  # D1P1S5
            "2 疾病 指被保险人在等待期后初次确诊的疾病。\n"  # D1P1S6 footnote block starts
            "3 意外伤害 是指外来的、突发的、非本意的、非疾病的客观事件。\n",  # D1P1S7
        ),
        Page(
            TERMS,
            "b" * 64,
            2,
            "8. 释义\n"  # D1P2S1 definitions section starts
            "8.1 重大疾病 指符合本合同约定的疾病，且须由专科医生确诊。\n"  # D1P2S2
            "8.2 专科医生 是指取得执业资格并在二级以上医院工作的医生。\n",  # D1P2S3
        ),
        Page(TERMS, "b" * 64, 3, "本合同终止。\n"),  # D1P3S1, too short to be a copy
        Page(
            BROCHURE,
            "a" * 64,
            1,
            "本说明书适用于示例保险产品。\n"  # D2P1S1
            "等待期 合同的等待期为90日，自合同生效之日起计算。\n"  # D2P1S2 differs by 本
            # D2P1S3 carries a footnote mark, D2P1S4 says 30 where the terms say 60
            "犹豫期 投保人收到合同1后有15日的犹豫期，可以解除合同并退还保费。\n"
            "宽限期 自应交日起有30日的宽限期，期间发生保险事故我们仍承担保险责任。\n"
            "本产品提供专属健康管理服务，包括在线问诊与就医绿通。\n"  # D2P1S5 brochure only
            "合同终止。\n",  # D2P1S6
        ),
    ]
)
TEXT = {s.id: s for s in SOURCE.segments}


def test_the_synthetic_pages_segment_as_the_rules_expect() -> None:
    assert TEXT["D1P1S2"].text.startswith("第一条 保险责任")
    assert TEXT["D1P2S1"].text == "8. 释义"
    assert TEXT["D2P1S6"].text == "合同终止。"


def cite(segment_id: str) -> dict[str, object]:
    segment = TEXT[segment_id]
    return {
        "document": segment.document,
        "document_sha256": segment.document_sha256,
        "page": segment.page,
        "quote": segment.text,
        "segment_id": segment.id,
    }


def golden(tmp_path: Path, fields: dict[str, list[str]]) -> GoldenV2:
    path = tmp_path / "9999.json"
    document = {
        "product_id": "9999",
        "cards_version": "test",
        "fields": [
            {
                "field_key": k,
                "state": "present",
                "value": "x",
                "reason": "r",
                "evidence": [cite(i) for i in v],
            }
            for k, v in fields.items()
        ],
    }
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return load_golden_v2(path)


def chose(key: str, ids: list[str]) -> FieldResult:
    return FieldResult(field_key=key, state="present", value="x", evidence=SOURCE.evidence(ids))


def both(
    tmp_path: Path, fields: dict[str, list[str]], chosen: dict[str, list[str]]
) -> tuple[
    dict[str, tuple[float | None, float | None]], dict[str, tuple[float | None, float | None]]
]:
    gold = golden(tmp_path, fields)
    predicted = [chose(k, v) for k, v in chosen.items()]
    ruled = score_selection(SOURCE, gold, predicted, rules=load_scoring_rules())
    legacy = score_selection(SOURCE, gold, predicted)
    pick = lambda report: {f.field_key: (f.recall, f.precision) for f in report.fields}  # noqa: E731
    return pick(ruled), pick(legacy)


def test_near_copies_differing_by_ben_or_a_footnote_mark_credit_each_other(tmp_path: Path) -> None:
    ruled, legacy = both(
        tmp_path,
        {"waiting_period": ["D2P1S2"], "cooling_off_period": ["D2P1S3"]},
        {"waiting_period": ["D1P1S3"], "cooling_off_period": ["D1P1S4"]},
    )
    assert ruled == {"waiting_period": (1.0, 1.0), "cooling_off_period": (1.0, 1.0)}
    assert legacy == {"waiting_period": (0.0, 0.0), "cooling_off_period": (0.0, 0.0)}


def test_numbers_and_short_passages_never_fold_into_a_copy(tmp_path: Path) -> None:
    ruled, _ = both(
        tmp_path,
        {"premium_grace_period": ["D2P1S4"], "contract_termination": ["D2P1S6"]},
        {"premium_grace_period": ["D1P1S5"], "contract_termination": ["D1P3S1"]},
    )
    assert ruled == {"premium_grace_period": (0.0, 0.0), "contract_termination": (0.0, 0.0)}


def test_headings_and_reader_guide_lines_are_neutral(tmp_path: Path) -> None:
    ruled, legacy = both(
        tmp_path,
        {"waiting_period": ["D1P1S2", "D1P1S3"]},
        {"waiting_period": ["D1P1S1", "D1P1S3"]},
    )
    assert ruled == {"waiting_period": (1.0, 1.0)}
    assert legacy == {"waiting_period": (0.5, 0.5)}


def test_footnotes_and_definitions_count_only_where_the_card_asks_for_them(tmp_path: Path) -> None:
    ruled, legacy = both(
        tmp_path,
        {
            "waiting_period": ["D1P1S3", "D1P1S6"],
            "disease_definitions_and_criteria": ["D1P2S2", "D1P2S3"],
        },
        {
            "waiting_period": ["D1P1S3", "D1P1S7", "D1P2S2"],
            "disease_definitions_and_criteria": ["D1P2S2", "D1P1S6"],
        },
    )
    assert ruled["waiting_period"] == (1.0, 1.0)
    assert legacy["waiting_period"] == (0.5, pytest.approx(1 / 3))
    assert ruled["disease_definitions_and_criteria"] == (0.5, 0.5)
    assert legacy["disease_definitions_and_criteria"] == (0.5, 0.5)


def test_brochure_restatements_are_neutral_only_beside_cited_terms(tmp_path: Path) -> None:
    ruled, legacy = both(
        tmp_path,
        {"waiting_period": ["D1P1S3"], "value_added_services": ["D2P1S5"]},
        {"waiting_period": ["D1P1S3", "D2P1S5"], "value_added_services": ["D2P1S5", "D2P1S1"]},
    )
    assert ruled == {"waiting_period": (1.0, 1.0), "value_added_services": (1.0, 0.5)}
    assert legacy == {"waiting_period": (1.0, 0.5), "value_added_services": (1.0, 0.5)}


def test_a_field_left_with_only_neutral_segments_has_no_score(tmp_path: Path) -> None:
    ruled, _ = both(tmp_path, {"waiting_period": ["D1P1S2"]}, {"waiting_period": ["D1P1S1"]})
    assert ruled == {"waiting_period": (None, None)}


def test_the_rules_are_versioned_and_never_fall_back_silently(tmp_path: Path) -> None:
    rules = load_scoring_rules()
    assert rules.version == "2026-10-26.1"
    broken = tmp_path / "rules.json"
    broken.write_text("{}", encoding="utf-8")
    with pytest.raises(ScoringRulesError):
        load_scoring_rules(broken)
    with pytest.raises(ScoringRulesError):
        load_scoring_rules(tmp_path / "missing.json")
