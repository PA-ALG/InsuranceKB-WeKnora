"""SK-2 Spec §2.1, §10.1, §10.7 (RED, written by Claude): the registry's methods section."""

import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.ingest.method_registry import (
    MethodEntry,
    MethodLink,
    method_id_for,
    method_key,
    valid_links,
)
from insurance_harness.ingest.method_use_model import ScopeAnswer
from insurance_harness.ingest.registry import ProductRegistry, registry_document
from tests.compilers.methods.helpers import METHOD_A, METHOD_C, SHA_A, SHA_C, World
from tests.ingest.method_helpers import nursing_entry, v1


def entry(name: str, *links: MethodLink, **extra: Any) -> MethodEntry:
    key = method_key(name)
    return MethodEntry(
        method_id=method_id_for(key), method_key=key, names=(name,), links=links, **extra
    )


def revalidated(registry: ProductRegistry) -> ProductRegistry:
    return ProductRegistry.model_validate_json(registry.model_dump_json())


def link_a(world: World, *needles: str) -> MethodLink:
    blocks = tuple(world.block("k-deck-a", needle) for needle in needles)
    return MethodLink(knowledge_id="k-deck-a", parse_attempt=1, sha256=SHA_A, block_ids=blocks)


def test_method_key_folds_and_the_id_is_derived_from_it() -> None:
    assert method_key(" 家庭 保障[Ａｂ]需求　") == "家庭保障〔ab〕需求"
    key = method_key(METHOD_A)
    assert method_id_for(key) == "sm-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def test_a_method_links_blocks_of_an_admitted_record() -> None:
    world = World()
    world.registry.methods = [entry(METHOD_A, link_a(world, "讲解步骤一", "讲解步骤二"))]
    loaded = revalidated(world.registry)
    assert loaded.methods == world.registry.methods
    document = json.loads(registry_document(loaded))
    assert document["methods"][0]["links"][0]["knowledge_id"] == "k-deck-a"


def _wrong_id(world: World) -> list[MethodEntry]:
    good = entry(METHOD_A, link_a(world, "讲解步骤一"))
    return [good.model_copy(update={"method_id": "sm-" + "0" * 24})]


def _two_ids(world: World) -> list[MethodEntry]:
    return [entry(METHOD_A, link_a(world, "讲解步骤一"))] * 2


def _name_taken(world: World) -> list[MethodEntry]:
    first = entry(METHOD_A, link_a(world, "讲解步骤一"))
    second = entry(METHOD_C, aliases=(" 家庭保障需求 销售方法",))
    return sorted([first, second], key=lambda m: m.method_id)


def _no_record(world: World) -> list[MethodEntry]:
    link = MethodLink(knowledge_id="k-deck-a", parse_attempt=2, sha256=SHA_A, block_ids=("P2S1",))
    return [entry(METHOD_A, link)]


def _foreign_block(world: World) -> list[MethodEntry]:
    return [entry(METHOD_A, link_a(world, "主讲人"))]  # the speaker line shows no method signal


def _triple_twice(world: World) -> list[MethodEntry]:
    return [entry(METHOD_A, link_a(world, "讲解步骤一"), link_a(world, "讲解步骤二"))]


def _unsorted(world: World) -> list[MethodEntry]:
    methods = [entry(METHOD_A), entry(METHOD_C)]
    return sorted(methods, key=lambda m: m.method_id, reverse=True)


def _self_duplicate(world: World) -> list[MethodEntry]:
    first = entry(METHOD_A)
    return [first.model_copy(update={"possible_duplicates": (first.method_id,)})]


@pytest.mark.parametrize(
    "build",
    [
        _wrong_id,
        _two_ids,
        _name_taken,
        _no_record,
        _foreign_block,
        _triple_twice,
        _unsorted,
        _self_duplicate,
    ],
)
def test_the_registry_refuses_an_inconsistent_methods_section(build: Any) -> None:
    world = World()
    world.registry.methods = build(world)
    with pytest.raises(ValidationError):
        revalidated(world.registry)


def test_a_v1_registry_holds_no_methods_and_writes_none() -> None:
    registry = v1()
    assert "methods" not in json.loads(registry_document(registry))
    registry.methods = [entry(METHOD_A)]
    with pytest.raises(ValidationError):
        revalidated(registry)


def test_link_validity_follows_the_record_and_is_not_stored() -> None:
    world = World()
    method = entry(METHOD_A, link_a(world, "讲解步骤一"))
    world.registry.methods = [method]
    assert valid_links(method, world.registry.method_uses) == method.links
    before = json.loads(registry_document(world.registry))["methods"]

    world.set_use("k-deck-a", state="invalidated", invalidated_reason="withdrawn")
    loaded = revalidated(world.registry)
    assert valid_links(method, loaded.method_uses) == ()
    assert json.loads(registry_document(loaded))["methods"] == before


def test_an_edited_record_keeps_its_links_valid_and_an_ignored_one_does_not() -> None:
    world = World()
    block = world.block("k-deck-c", "讲解步骤")
    link = MethodLink(knowledge_id="k-deck-c", parse_attempt=1, sha256=SHA_C, block_ids=(block,))
    method = entry(METHOD_C, link)
    world.registry.methods = [method]
    world.set_use("k-deck-c", editing=True)  # a person is correcting the labels: still active
    assert valid_links(method, revalidated(world.registry).method_uses) == method.links
    answer = ScopeAnswer(item_id="item-1", answer_id="answer-1", option_key="ignore", answerer="u")
    world.set_use(
        "k-deck-c", state="ignored", categories=(), decided_by="person", confirmation=answer
    )
    assert valid_links(method, revalidated(world.registry).method_uses) == ()


def test_product_identity_is_unchanged_by_the_methods_section() -> None:
    world = World()
    world.registry.products = {"p-nursing": nursing_entry()}
    registered, source_map = world.registry.registered(), world.registry.source_map()
    world.registry.methods = [entry(METHOD_A, link_a(world, "讲解步骤一"))]
    loaded = revalidated(world.registry)
    assert loaded.registered() == registered
    assert loaded.source_map().model_dump_json() == source_map.model_dump_json()
