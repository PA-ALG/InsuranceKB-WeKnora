"""S6c acceptance: a native Wiki page becomes a wiki_page member (Spec §3.2, §3.3).

Protected file: written by Claude. Only concept and entity pages are kept; links between pages
are rewritten to member slugs of the same product, or reduced to their text; evidence is a
segment of the product's own source pages that lies whole inside a cited chunk, in chunk order,
at most three, never guessed; assemble makes a wiki_page member whose evidence refs pin the
cited sources.
"""

from __future__ import annotations

from typing import Any

from insurance_harness.bundle.assemble import assemble
from insurance_harness.compilers.wiki_pages.members import NativePage, wiki_page
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

SHA = "a" * 64
TERMS = "保险条款.pdf"


class Page:
    def __init__(self, document: str, page: int, text: str, sha: str = SHA) -> None:
        self.document, self.document_sha256, self.page, self.text = document, sha, page, text


# Two pages of the product's terms; each line is its own segment (S4i segmentation).
SOURCE = SegmentedSource(
    [
        Page(TERMS, 1, "等待期为90日。\n被保险人因意外伤害发生保险事故的，无等待期。\n短句。"),
        Page(TERMS, 2, "宽限期为60日。\n宽限期内发生保险事故的，我们承担保险责任。"),
    ]
)
SOURCES = {TERMS: SourceRevision(knowledge_id="k-terms", parse_attempt=2)}
TITLES = {
    "concept/deng-dai-qi": "等待期",
    "concept/kuan-xian-qi": "宽限期",
    "entity/an-you-fu": "安佑福",
}


def native(**changes: Any) -> NativePage:
    data: dict[str, Any] = {
        "slug": "concept/deng-dai-qi",
        "title": "等待期",
        "page_type": "concept",
        "summary": "等待期说明。",
        "content": "等待期见 [[concept/kuan-xian-qi|宽限期规则]]。",
        "aliases": ["观察期"],
        "chunks": [{"content": "条款：等待期为90日。被保险人因意外伤害发生保险事故的，无等待期。"}],
    }
    data.update(changes)
    return NativePage.model_validate(data)


def convert(page: NativePage) -> Any:
    return wiki_page(
        page,
        entity_id="1828",
        titles=TITLES,
        source=SOURCE,
        sources=SOURCES,
        model="deepseek-v4-flash",
    )


def test_only_concept_and_entity_pages_are_kept() -> None:
    assert convert(native(page_type="summary")) is None
    assert convert(native(page_type="index")) is None
    kept = convert(native(page_type="entity", slug="entity/an-you-fu"))
    assert kept is not None and kept.page_type == "entity"


def test_fields_are_carried_and_marked_model_generated() -> None:
    page = convert(native())
    assert page.page_key == "concept/deng-dai-qi"
    assert page.entity_refs == ["1828"]
    assert (page.title, page.summary, page.aliases) == ("等待期", "等待期说明。", ["观察期"])
    assert (page.origin, page.generator, page.model) == (
        "MODEL_GENERATED",
        "weknora-native-wiki",
        "deepseek-v4-flash",
    )


def test_links_are_rewritten_to_member_slugs_or_reduced_to_text() -> None:
    content = (
        "A [[concept/kuan-xian-qi|宽限期规则]] B [[concept/kuan-xian-qi]] "
        "C [[concept/missing|别处]] D [[concept/missing-page]]"
    )
    page = convert(native(content=content))
    assert page.content == (
        "A [[wiki/1828/concept/kuan-xian-qi|宽限期规则]] "
        "B [[wiki/1828/concept/kuan-xian-qi|宽限期]] "
        "C 别处 D missing-page"
    )


def test_evidence_is_the_first_unused_whole_segment_of_each_chunk_in_order() -> None:
    page = convert(
        native(
            chunks=[
                {"content": "条款：等待期为90日。被保险人因意外伤害发生保险事故的，无等待期。"},
                {"content": "等待期为90日。宽限期为60日。"},  # its first segment is already used
                {"content": "短句。"},  # shorter than 8 characters: never evidence
                {"content": "与材料无关的文字。"},
            ]
        )
    )
    assert [item.quote for item in page.evidence] == ["等待期为90日。", "宽限期为60日。"]
    first, second = page.evidence
    assert first.source_ref == f"source:v1:k-terms:2:{SHA}"
    assert (first.locator.page, second.locator.page) == (1, 2)
    assert first.file_sha256 == SHA
    assert (first.locator.start, first.locator.end) == (0, len("等待期为90日。"))


def test_evidence_stops_at_three_and_may_be_empty() -> None:
    many = convert(
        native(
            chunks=[
                {"content": "等待期为90日。被保险人因意外伤害发生保险事故的，无等待期。"},
                {"content": "被保险人因意外伤害发生保险事故的，无等待期。宽限期为60日。"},
                {"content": "宽限期为60日。宽限期内发生保险事故的，我们承担保险责任。"},
                {"content": "宽限期内发生保险事故的，我们承担保险责任。"},
            ]
        )
    )
    assert len(many.evidence) == 3
    assert convert(native(chunks=[{"content": "与材料无关。"}])).evidence == []
    assert convert(native(chunks=[])).evidence == []


def test_assemble_makes_a_wiki_page_member_pinning_its_sources() -> None:
    page = convert(native())
    bundle = assemble([], compiler_identity="harness/wiki_pages@test", wiki_pages=[page])
    (member,) = bundle.members
    assert member.kind == "wiki_page"
    assert member.logical_slug == "wiki/1828/concept/deng-dai-qi"
    assert member.evidence_refs == [f"source:v1:k-terms:2:{SHA}"]
    assert member.access_scope == "space"
