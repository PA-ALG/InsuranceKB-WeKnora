"""SK-2b Spec §4, §9.2 (RED, written by Claude): candidates from the discovery base's pages."""

from collections.abc import Sequence
from typing import Any

from insurance_harness.compilers.methods.candidates import CandidateRun, method_candidates
from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.compilers.methods.copies import CopyBook, empty_book, sync_copies
from insurance_harness.compilers.wiki_pages.members import NativePage
from tests.compilers.methods.discovery_helpers import (
    DISCOVERY_KB,
    DiscoveryWorld,
    FakePlatform,
    chunk,
    page,
)
from tests.compilers.methods.helpers import (
    DECK_A,
    DECK_C,
    METHOD_A,
    METHOD_C,
    FakeModel,
    full_answer,
)
from tests.ingest.upload_helpers import SPACE

ALL_A = [text for slide in DECK_A for text in slide]
STEPS = ("讲解步骤一：了解客户家庭结构", "讲解步骤二：分析家庭责任与缺口")


class Discovery:
    """The world, its copies in the discovery base, and the copies' IDs by original."""

    def __init__(self) -> None:
        self.world = DiscoveryWorld()
        self.platform = FakePlatform(self.world)
        empty = empty_book(SPACE, DISCOVERY_KB)
        self.book: CopyBook = sync_copies(self.world.registry, empty, self.platform, live=True).book
        self.copy = {c.knowledge_id: c.copy_knowledge_id for c in self.book.copies}

    def run(self, *pages: NativePage) -> CandidateRun:
        return method_candidates(
            self.world.registry,
            self.book,
            self.platform.listing(DISCOVERY_KB),
            pages,
            self.world.reader,
        )


def found(run: CandidateRun) -> list[tuple[str, str, tuple[str, ...]]]:
    return [(c.name, c.copy_knowledge_id, c.block_ids) for c in run.candidates.candidates]


def blocks(world: DiscoveryWorld, knowledge_id: str, needles: Sequence[str]) -> tuple[str, ...]:
    return tuple(world.block(knowledge_id, needle) for needle in needles)


def test_a_page_becomes_a_candidate_on_the_original_blocks() -> None:
    d = Discovery()
    run = d.run(page(METHOD_A, chunk(d.copy["k-deck-a"], *STEPS), aliases=["需求面谈"]))
    assert found(run) == [(METHOD_A, d.copy["k-deck-a"], blocks(d.world, "k-deck-a", STEPS))]
    assert run.candidates.candidates[0].aliases == ("需求面谈",)
    raw = d.world.raws["k-deck-a"]
    copies = {c.copy_knowledge_id: c for c in run.candidates.copies}
    listed = copies[d.copy["k-deck-a"]]
    assert (listed.knowledge_id, listed.parse_attempt, listed.sha256) == (
        raw.knowledge_id, raw.parse_attempt, raw.sha256,
    )
    assert listed.copy_sha256 == d.platform.items[d.copy["k-deck-a"]][1]
    assert run.candidates.discovery_kb_id == DISCOVERY_KB


def test_only_entity_and_concept_pages_are_candidates() -> None:
    d = Discovery()
    pages = [
        page(METHOD_A, chunk(d.copy["k-deck-a"], *STEPS), page_type=kind)
        for kind in ("summary", "index", "synthesis", "concept")
    ]
    assert [name for name, _, _ in found(d.run(*pages))] == [METHOD_A]


def test_only_recorded_blocks_are_located() -> None:
    d = Discovery()
    run = d.run(
        page(METHOD_A, chunk(d.copy["k-deck-a"], "主讲人：培训部", STEPS[0])),
        page("培训部介绍", chunk(d.copy["k-deck-a"], "主讲人：培训部")),
    )
    assert found(run) == [(METHOD_A, d.copy["k-deck-a"], blocks(d.world, "k-deck-a", STEPS[:1]))]
    assert run.report["counts"] == {"NO_RECORDED_BLOCKS": 1}


def test_a_chunk_inside_a_block_locates_it_when_long_enough() -> None:
    d = Discovery()
    run = d.run(
        page(METHOD_A, chunk(d.copy["k-deck-a"], "分析家庭责任与缺口")),
        page("家庭结构", chunk(d.copy["k-deck-a"], "家庭结构")),
    )
    assert found(run) == [(METHOD_A, d.copy["k-deck-a"], blocks(d.world, "k-deck-a", STEPS[1:]))]
    assert run.report["counts"] == {"NO_RECORDED_BLOCKS": 1}


def test_a_page_citing_two_materials_makes_one_candidate_each() -> None:
    d = Discovery()
    cited = page(
        METHOD_A,
        chunk(d.copy["k-deck-a"], STEPS[0]),
        chunk(d.copy["k-deck-c"], "讲解步骤：对比新旧保障差异"),
        chunk(d.copy["k-deck-a"], STEPS[1]),
    )
    assert found(d.run(cited)) == [
        (METHOD_A, d.copy["k-deck-a"], blocks(d.world, "k-deck-a", STEPS)),
        (METHOD_A, d.copy["k-deck-c"], blocks(d.world, "k-deck-c", ["讲解步骤："])),
    ]


def test_chunks_without_a_usable_copy_make_no_candidate() -> None:
    d = Discovery()
    d.platform.items[d.copy["k-deck-c"]] = (*d.platform.items[d.copy["k-deck-c"]][:2], False)
    run = d.run(
        page(METHOD_A, chunk("copy-unknown", *STEPS)),
        page(METHOD_C, chunk(d.copy["k-deck-c"], "讲解步骤：对比新旧保障差异")),  # still parsing
    )
    assert found(run) == []
    assert run.report["counts"] == {"CHUNK_UNMAPPED": 2}
    assert d.copy["k-deck-c"] not in {c.copy_knowledge_id for c in run.candidates.copies}


def test_an_invalidated_record_makes_no_candidate() -> None:
    d = Discovery()
    d.world.set_use("k-deck-a", state="invalidated", invalidated_reason="source_revised")
    run = d.run(page(METHOD_A, chunk(d.copy["k-deck-a"], *STEPS)))
    assert found(run) == []
    assert run.report["counts"] == {"METHOD_USE_NOT_ACTIVE": 1}


def test_the_candidate_file_holds_no_text() -> None:
    d = Discovery()
    run = d.run(page(METHOD_A, chunk(d.copy["k-deck-a"], *ALL_A)))
    text = run.candidates.model_dump_json()
    for needle in ("了解客户家庭结构", "模型写的正文", "模型写的摘要"):
        assert needle not in text
    assert "了解客户家庭结构" not in str(run.report)


def test_candidates_are_admitted_and_compiled_end_to_end() -> None:
    d = Discovery()
    texts_c = [text for slide in DECK_C for text in slide]
    run = d.run(
        page(METHOD_A, chunk(d.copy["k-deck-a"], *ALL_A)),
        page(METHOD_C, chunk(d.copy["k-deck-c"], *texts_c)),
    )
    answers: dict[str, Any] = {METHOD_A: full_answer}
    compiled = compile_methods(
        d.world.registry, run.candidates, pages=d.world.reader, port=FakeModel(answers),
        active=None,
    )
    by_name = {m.names[0]: m for m in compiled.registry.methods}
    assert set(by_name) == {METHOD_A, METHOD_C}
    assert [link.knowledge_id for link in by_name[METHOD_A].links] == ["k-deck-a"]
    assert by_name[METHOD_A].links[0].block_ids == d.world.use("k-deck-a").block_ids
    statuses = {m["method_id"]: m["status"] for m in compiled.report["methods"]}
    assert statuses[by_name[METHOD_A].method_id] == "compiled"
    assert compiled.report["candidates"]["dropped"] == {}
