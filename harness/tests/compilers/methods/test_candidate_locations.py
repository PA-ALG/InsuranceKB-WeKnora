"""SK-2d frozen RED: synthetic sources through actual candidate/compile entry points."""

from collections.abc import Sequence
from typing import Any

import pytest

from insurance_harness.compilers.methods.candidates import CandidateRun, method_candidates
from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.compilers.methods.copies import CopiesError, CopyBook, MethodCopy
from insurance_harness.compilers.wiki_pages.members import NativeChunk, NativePage
from insurance_harness.contracts.enums import LocatorKind
from insurance_harness.contracts.knowledge import Claim, Locator
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.office_pages import OfficeBlock, OfficePageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.raw_sources import RawListing
from tests.compilers.methods.helpers import FakeModel, method_use, unknown_answer
from tests.ingest.method_helpers import DeckPages, deck_pages, source, v2

SHA = "a" * 64
NAME = "合成需求访谈方法"
LONG = (
    "先了解家庭成员职业健康情况再核对现有保障责任期限随后讨论收入支出"
    "应急储备预算最后确认客户理解风险并约定下次复盘"
)
assert len(LONG) >= 50


class Scenario:
    """Synthetic fixed RAW revision and SK-1 record; only the reader is replaced."""

    def __init__(
        self, groups: Sequence[Sequence[str]], *, pdf: bool = False, recorded: int | None = None
    ) -> None:
        self.raw = source("raw-test", "synthetic.pdf" if pdf else "synthetic.pptx", SHA)
        if pdf:
            self.pages: list[PageText] = [
                PageText(self.raw.file_name, SHA, i, "\n".join(texts))
                for i, texts in enumerate(groups, 1)
            ]
        else:
            self.pages = list(deck_pages(self.raw.file_name, SHA, groups))
        segmented = SegmentedSource(self.pages)
        self.ids = tuple(s.id.removeprefix("D1") for s in segmented.segments)
        template = method_use(
            self.raw, deck_pages(self.raw.file_name, SHA,
                                 (("护理险销售方法讲解步骤关键句话术需求分析促成",),))
        )
        self.use = template.model_copy(update={"block_ids": self.ids[:recorded]})
        self.registry = v2()
        self.registry.method_uses = [self.use]
        self.reader = DeckPages({self.raw.knowledge_id: self.pages})
        self.copy = source("copy-test", self.raw.file_name, SHA)
        self.book = CopyBook(
            contract="method-copies.v1", space_id=self.registry.space_id,
            discovery_kb_id="discovery",
            copies=(MethodCopy(copy_knowledge_id=self.copy.knowledge_id,
                               knowledge_id=self.raw.knowledge_id, parse_attempt=1, sha256=SHA),),
        )
        self.listing = RawListing(completed=[self.copy], unfinished=[])

    def run(self, *chunks: str, repeat: int = 1) -> CandidateRun:
        page = NativePage(slug="method", title=NAME, page_type="entity", chunks=[
            NativeChunk(content=text, knowledge_id=self.copy.knowledge_id) for text in chunks
        ])
        return method_candidates(
            self.registry, self.book, self.listing, [page] * repeat, self.reader
        )


def found(run: CandidateRun) -> tuple[str, ...]:
    return tuple(block for item in run.candidates.candidates for block in item.block_ids)


@pytest.mark.parametrize("copy", [
    "| 访谈阶段 | 核对家庭责任 |\n| :--- | ---: |\n| 风险讨论 | 不保证收益 |",
    "<table><tr><td>访谈阶段</td><td>核对家庭责任</td></tr>"
    "<tr><td>风险讨论</td><td>不保证收益</td></tr></table>",
])
def test_table_representation_locates_only_actual_rows(copy: str) -> None:
    s = Scenario((("访谈阶段\t核对家庭责任", "风险讨论\t不保证收益", "无关内容不要扩展链接"),))
    run = s.run(copy)
    assert found(run) == s.ids[:2]
    assert "核对家庭责任" not in run.candidates.model_dump_json()
    assert "核对家庭责任" not in str(run.report)


def test_xlsx_row_with_html_and_nfkc_preserves_numbers_and_operators() -> None:
    raw = "演练规则\t预算≤１２．５％\t不得承诺收益"
    s = Scenario(((raw,),))
    s.pages = [OfficePageText(s.raw.file_name, SHA, 1, raw, (
        OfficeBlock(0, len(raw), Locator(kind=LocatorKind.XLSX_CELL_RANGE,
                                       sheet="演练", cell_range="A1:XFD1")),
    ))]
    s.reader.decks[s.raw.knowledge_id] = s.pages
    copied = "<tr><td>演练规则</td><td>预算≤12.5%</td><td>不得承诺收益</td></tr>"
    assert found(s.run(copied)) == s.ids


def test_quotes_and_width_are_display_differences() -> None:
    s = Scenario((("讲解时说‘先了解需求’再说明预算−５％",),))
    assert found(s.run("讲解时说'先了解需求'再说明预算-5%")) == s.ids


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("size,accepted", [(39, False), (40, True)])
def test_office_boundary_overlap_threshold_and_only_the_covered_block(
    reverse: bool, size: int, accepted: bool
) -> None:
    shared = LONG[:size]
    raw, copy = ("前文" + shared, shared + "后文")
    if reverse:
        raw, copy = copy, raw
    s = Scenario(((raw, "相邻但未被引用的访谈规则"),))
    assert found(s.run(copy)) == (s.ids[:1] if accepted else ())


@pytest.mark.parametrize("pdf", [False, True])
def test_complete_containment_eight_characters_and_short_boundary(pdf: bool) -> None:
    s = Scenario((("需求分析流程甲乙", "了解需求先听懂"),), pdf=pdf)
    assert found(s.run("需求分析流程甲乙")) == s.ids[:1]
    assert found(s.run("了解需求先听懂")) == ()


def test_pdf_does_not_gain_partial_overlap() -> None:
    s = Scenario((("前文" + LONG,),), pdf=True)
    assert found(s.run(LONG + "后文")) == ()


@pytest.mark.parametrize("location", ["other_page", "other_block", "same_block", "unrecorded"])
def test_ambiguous_normalized_raw_positions_are_not_selected(location: str) -> None:
    text = "访谈步骤\t了解家庭责任与预算"
    second = "访谈步骤 了解家庭责任与预算"
    groups: Sequence[Sequence[str]] = (
        ((text,), (second,)) if location == "other_page" else ((text, second),)
    )
    if location == "same_block":
        groups = ((text + "分隔说明" + second,),)
    s = Scenario(groups, recorded=1 if location == "unrecorded" else None)
    assert found(s.run(second)) == ()


def test_partial_match_is_unique_across_unrecorded_raw_positions_too() -> None:
    s = Scenario((("前文" + LONG,), ("另一前文" + LONG,)), recorded=1)
    assert found(s.run(LONG + "后文")) == ()


@pytest.mark.parametrize(
    "kind", ["copy_chunks", "raw_pages", "raw_blocks", "scattered", "internal"]
)
def test_matching_cannot_be_assembled_from_unrelated_fragments(kind: str) -> None:
    if kind == "copy_chunks":
        s = Scenario((("前文" + LONG,),))
        assert found(s.run("不同" + LONG[:25], LONG[25:] + "后文")) == ()
    elif kind == "raw_pages":
        s = Scenario((("前文" + LONG[:25],), (LONG[25:] + "后文",)))
        assert found(s.run(LONG)) == ()
    elif kind == "raw_blocks":
        s = Scenario((("前文" + LONG[:25], LONG[25:] + "后文"),))
        assert found(s.run(LONG)) == ()
    elif kind == "scattered":
        s = Scenario((("前文" + LONG[:25] + "中间原话" + LONG[25:],),))
        assert found(s.run(LONG[:25] + "不同中间话" + LONG[25:] + "后文")) == ()
    else:
        s = Scenario((("原前文" + LONG + "原后文",),))
        assert found(s.run("另前文" + LONG + "另后文")) == ()


@pytest.mark.parametrize("before,after", [
    ("预算12.5%", "预算13.5%"), ("预算12.5%", "预算125%"),
    ("不得承诺收益", "可以承诺收益"), ("预算12.5%", "预算12.5"),
    ("预算-5%", "预算+5%"), ("预算≤5%", "预算≥5%"),
    ("预算<5%", "预算>5%"), ("额度A1", "额度B1"),
])
def test_semantic_edits_cannot_be_normalized_or_partial_matched_away(
    before: str, after: str
) -> None:
    s = Scenario(((LONG + before + "结束",),))
    assert found(s.run(LONG + after + "结束")) == ()


def test_comparison_expression_is_not_an_html_tag() -> None:
    s = Scenario((("预算条件<5%并且>1%时仍不得承诺收益",),))
    assert found(s.run("预算条件并且时仍不得承诺收益")) == ()
    assert found(s.run("预算条件&lt;5%并且&gt;1%时仍不得承诺收益")) == s.ids


def test_plain_pipes_are_not_removed_as_table_formatting() -> None:
    s = Scenario((("演练逻辑A|B不同于同时满足两个选项",),))
    assert found(s.run("演练逻辑AB不同于同时满足两个选项")) == ()


def test_recall_has_two_columns_uses_eligible_only_and_deduplicates() -> None:
    s = Scenario((("需求分析流程甲乙", "确认家庭责任顺序", "了解需求先听懂"),))
    run = s.run("需求分析流程甲乙", "了解需求先听懂", repeat=3)
    assert run.report["recall"] == {
        "eligible": {"total": 2, "covered": 1, "ratio": 0.5},
        "short": {"total": 1, "covered": 0}, "gate": {"minimum": 0.5, "passed": True},
    }
    assert len(s.reader.calls) == 1


def test_unmapped_active_signals_stay_in_recall_denominator() -> None:
    s = Scenario((("需求分析流程甲乙",),))
    s.book = s.book.model_copy(update={"copies": ()})
    run = s.run("需求分析流程甲乙")
    assert run.report["recall"]["eligible"] == {"total": 1, "covered": 0, "ratio": 0.0}
    assert run.report["recall"]["gate"]["passed"] is False


def test_short_only_has_no_eligible_denominator_and_cannot_pass() -> None:
    s = Scenario((("了解需求先听懂",),))
    run = s.run("了解需求先听懂")
    assert found(run) == ()
    assert run.report["recall"] == {
        "eligible": {"total": 0, "covered": 0, "ratio": None},
        "short": {"total": 1, "covered": 0}, "gate": {"minimum": 0.5, "passed": False},
    }


def test_inactive_records_are_not_read_or_counted() -> None:
    s = Scenario((("需求分析流程甲乙",),))
    s.registry.method_uses = [s.use.model_copy(update={
        "state": "invalidated", "invalidated_reason": "detached",
    })]
    run = s.run("需求分析流程甲乙")
    assert s.reader.calls == []
    assert run.report["recall"]["eligible"]["total"] == 0


def test_missing_recorded_block_cannot_silently_shrink_denominator() -> None:
    s = Scenario((("需求分析流程甲乙",),))
    s.registry.method_uses = [s.use.model_copy(update={"block_ids": ("P1S99",)})]
    with pytest.raises(CopiesError, match="RECORDED_BLOCKS_MISSING"):
        s.run()


def test_material_sha_check_precedes_recall() -> None:
    s = Scenario((("需求分析流程甲乙",),))
    s.reader.decks[s.raw.knowledge_id] = [PageText(s.raw.file_name, "b" * 64, 1, "其他内容")]
    with pytest.raises(SourcePagesError, match="PARSE_ARTIFACT_INTEGRITY"):
        s.run("需求分析流程甲乙")


def test_candidate_normalization_does_not_weaken_verbatim_evidence() -> None:
    raw = "访谈关键句\t不承诺收益"
    s = Scenario(((raw,),))
    run = s.run("<tr><td>访谈关键句</td><td>不承诺收益</td></tr>")
    assert found(run) == s.ids

    def answer(payload: dict[str, Any]) -> dict[str, Any]:
        response = unknown_answer(payload)
        response["predicates"][2] = {
            "predicate": "key_phrases", "state": "present", "items": [
                {"text": "不承诺收益", "refs": ["M1" + s.ids[0]]},
                {"text": "承诺收益5%", "refs": ["M1" + s.ids[0]]},
            ],
        }
        return response

    compiled = compile_methods(s.registry, run.candidates, pages=s.reader,
                               port=FakeModel({NAME: answer}), active=None)
    assert compiled.bundle is not None
    claims = [Claim.model_validate(m.payload) for m in compiled.bundle.members if m.kind == "claim"]
    claim = next(c for c in claims if c.predicate == "key_phrases")
    assert claim.value == ["不承诺收益"]
    assert len(claim.evidence) == 1 and claim.evidence[0].quote == raw
    assert "copy-test" not in claim.evidence[0].source_ref
    assert compiled.report["methods"][0]["dropped"]["PHRASE_NOT_VERBATIM"] == 1
