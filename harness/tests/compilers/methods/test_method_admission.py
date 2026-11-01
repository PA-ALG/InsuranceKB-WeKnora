"""SK-2 Spec §2.3, §3, §10.2 (RED, written by Claude): candidate admission and method identity."""

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compilers.methods.admission import (
    AdmissionError,
    CandidateFile,
    admit,
    load_candidates,
)
from insurance_harness.ingest.method_registry import MethodEntry, MethodLink, method_key
from tests.compilers.methods.helpers import (
    METHOD_A,
    SHA_A,
    SHA_B,
    World,
    candidate,
    candidate_file,
    copy_entry,
)


def run(world: World, *candidates: dict[str, Any], copies: Sequence[dict[str, Any]] = ()) -> Any:
    raws = (world.raw_a, world.raw_c, world.raw_p)
    listed = list(copies) or [copy_entry(raw) for raw in raws]
    result = admit(
        world.registry.methods,
        world.registry.method_uses,
        CandidateFile.model_validate_json(json.dumps(candidate_file(listed, candidates))),
    )
    world.registry.methods = list(result.methods)
    return result


def only(world: World) -> MethodEntry:
    assert len(world.registry.methods) == 1
    return world.registry.methods[0]


def by_name(world: World, name: str) -> MethodEntry:
    return next(m for m in world.registry.methods if m.names[0] == name)


def test_the_first_material_creates_a_method_and_its_link() -> None:
    world = World()
    steps = [world.block("k-deck-a", "讲解步骤二"), world.block("k-deck-a", "讲解步骤一")]
    result = run(world, candidate(METHOD_A, world.raw_a, steps))
    method = only(world)
    assert result.created == (method.method_id,) and result.merged == ()
    assert method.names == (METHOD_A,) and method.method_key == method_key(METHOD_A)
    assert method.links == (
        MethodLink(
            knowledge_id="k-deck-a", parse_attempt=1, sha256=SHA_A, block_ids=tuple(sorted(steps))
        ),
    )
    assert result.dropped == {}


def _unmapped(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"), copy_id="copy-x"), []


def _mapped_twice(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    copies = [copy_entry(world.raw_a), copy_entry(world.raw_a)]
    return candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")), copies


def _other_bytes(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    copies = [copy_entry(world.raw_a, copy_sha="f" * 64)]
    return candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")), copies


def _no_record(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    copies = [{**copy_entry(world.raw_a), "parse_attempt": 2}]
    return candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")), copies


def _invalidated(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    world.set_use("k-deck-a", state="invalidated", invalidated_reason="detached")
    return candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")), []


def _foreign_block(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blocks = [world.block("k-deck-a", "讲解步骤一"), world.block("k-deck-a", "主讲人")]
    return candidate(METHOD_A, world.raw_a, blocks), []


def _malformed_block(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return candidate(METHOD_A, world.raw_a, ["D1P2S1"]), []


def _no_blocks(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return candidate(METHOD_A, world.raw_a, []), []


def _blank_name(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return candidate(" 　 ", world.raw_a, world.hits("k-deck-a")), []


def _blank_alias(world: World) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"), aliases=["  "]), []


@pytest.mark.parametrize(
    ("build", "code"),
    [
        (_unmapped, "COPY_UNMAPPED"),
        (_mapped_twice, "COPY_UNMAPPED"),
        (_other_bytes, "COPY_MISMATCH"),
        (_no_record, "METHOD_USE_NOT_ACTIVE"),
        (_invalidated, "METHOD_USE_NOT_ACTIVE"),
        (_foreign_block, "BLOCKS_OUTSIDE_RECORD"),
        (_malformed_block, "BLOCKS_OUTSIDE_RECORD"),
        (_no_blocks, "BLOCKS_OUTSIDE_RECORD"),
        (_blank_name, "NAME_INVALID"),
        (_blank_alias, "NAME_INVALID"),
    ],
)
def test_a_failing_candidate_is_dropped_with_its_code(
    build: Callable[[World], tuple[dict[str, Any], list[dict[str, Any]]]], code: str
) -> None:
    world = World()
    item, copies = build(world)
    result = run(world, item, copies=copies)
    assert result.dropped == {code: 1}
    assert world.registry.methods == [] and result.created == ()


def test_a_copy_with_other_bytes_leaves_its_blocks_unlinked() -> None:
    world = World()
    pdf = world.hits("k-pdf-a")
    copies = [copy_entry(world.raw_a), copy_entry(world.raw_p, copy_sha="f" * 64)]
    run(
        world,
        candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")),
        candidate(METHOD_A, world.raw_p, pdf),
        copies=copies,
    )
    assert [link.knowledge_id for link in only(world).links] == ["k-deck-a"]


@pytest.mark.parametrize(
    "variant",
    ["家庭保障需求 销售方法", "家庭保障需求销售方法　", "家庭保障需求销售方法"],
)
def test_the_same_name_after_folding_merges(variant: str) -> None:
    world = World()
    run(world, candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")))
    result = run(world, candidate(variant, world.raw_p, world.hits("k-pdf-a")))
    method = only(world)
    assert result.merged == (method.method_id,) and result.created == ()
    assert [link.knowledge_id for link in method.links] == ["k-deck-a", "k-pdf-a"]
    assert method.names == (METHOD_A,)  # the same key adds no name


def test_brackets_width_and_case_fold_the_same_way() -> None:
    world = World()
    run(world, candidate("ABC[进阶]需求法", world.raw_a, world.hits("k-deck-a")))
    run(world, candidate("ａｂｃ〔进阶〕需求法", world.raw_p, world.hits("k-pdf-a")))
    assert len(only(world).links) == 2


def test_an_alias_hit_merges_and_appends_the_new_name() -> None:
    world = World()
    run(world, candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")))
    run(world, candidate("家庭需求面谈", world.raw_p, world.hits("k-pdf-a"), aliases=[METHOD_A]))
    assert only(world).names == (METHOD_A, "家庭需求面谈")


def test_aliases_hitting_two_methods_make_a_new_possible_duplicate() -> None:
    world = World()
    run(
        world,
        candidate("需求分析法", world.raw_a, world.hits("k-deck-a")),
        candidate("保障缺口法", world.raw_c, world.hits("k-deck-c")),
    )
    first, second = by_name(world, "需求分析法"), by_name(world, "保障缺口法")
    result = run(
        world,
        candidate("家庭需求面谈", world.raw_p, world.hits("k-pdf-a"), ["需求分析法", "保障缺口法"]),
    )
    new = by_name(world, "家庭需求面谈")
    assert result.created == (new.method_id,)
    assert new.aliases == ()  # both aliases belong to other methods
    assert new.possible_duplicates == tuple(sorted([first.method_id, second.method_id]))
    assert by_name(world, "需求分析法").possible_duplicates == (new.method_id,)
    assert by_name(world, "保障缺口法").possible_duplicates == (new.method_id,)
    pairs = [tuple(sorted((new.method_id, old.method_id))) for old in (first, second)]
    assert result.duplicates == tuple(sorted(pairs))


def test_a_name_hit_merges_and_an_alias_of_another_method_marks_a_duplicate() -> None:
    world = World()
    run(
        world,
        candidate("需求分析法", world.raw_a, world.hits("k-deck-a")),
        candidate("保障缺口法", world.raw_c, world.hits("k-deck-c")),
    )
    result = run(world, candidate("需求分析法", world.raw_p, world.hits("k-pdf-a"), ["保障缺口法"]))
    first, second = by_name(world, "需求分析法"), by_name(world, "保障缺口法")
    assert result.merged == (first.method_id,)
    assert first.aliases == () and len(first.links) == 2
    assert first.possible_duplicates == (second.method_id,)
    assert second.possible_duplicates == (first.method_id,)


def test_a_contained_key_marks_a_possible_duplicate_when_long_enough() -> None:
    world = World()
    run(
        world,
        candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")),
        candidate("促成", world.raw_c, world.hits("k-deck-c")),
    )
    run(
        world,
        candidate(METHOD_A + "进阶", world.raw_p, world.hits("k-pdf-a")),
        candidate("促成话术技巧", world.raw_p, world.hits("k-pdf-a")),
    )
    longer = by_name(world, METHOD_A + "进阶")
    assert longer.possible_duplicates == (by_name(world, METHOD_A).method_id,)
    assert by_name(world, "促成话术技巧").possible_duplicates == ()  # "促成" is too short to tell
    assert len(world.registry.methods) == 4


def test_readmission_unions_blocks_and_then_changes_nothing() -> None:
    world = World()
    one, two = world.block("k-deck-a", "讲解步骤一"), world.block("k-deck-a", "促成")
    run(world, candidate(METHOD_A, world.raw_a, [two]))
    run(world, candidate(METHOD_A, world.raw_a, [one, two]))
    assert only(world).links[0].block_ids == tuple(sorted([one, two]))
    before = [m.model_dump_json() for m in world.registry.methods]
    run(world, candidate(METHOD_A, world.raw_a, [one]))
    assert [m.model_dump_json() for m in world.registry.methods] == before


def test_blocks_are_kept_in_reading_order_once() -> None:
    world = World()
    deck = world.use("k-deck-a").block_ids
    run(world, candidate(METHOD_A, world.raw_a, [*reversed(deck), deck[0]]))
    assert only(world).links[0].block_ids == deck  # the record's reading order


def test_copies_never_enter_the_registry() -> None:
    world = World()
    run(world, candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")))
    assert "copy-" not in world.registry.model_dump_json()
    assert SHA_B not in only(world).model_dump_json()


def test_a_malformed_candidate_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    for text in (
        "not json",
        json.dumps({**candidate_file([], []), "contract": "method-candidates.v2"}),
        json.dumps({**candidate_file([], []), "extra": 1}),
        '{"contract": "method-candidates.v1", "contract": "method-candidates.v1"}',
    ):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(AdmissionError) as raised:
            load_candidates(path)
        assert raised.value.code == "CANDIDATES_INVALID"
    path.write_text(json.dumps(candidate_file([], [])), encoding="utf-8")
    assert load_candidates(path).candidates == ()
