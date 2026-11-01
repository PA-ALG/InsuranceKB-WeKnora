"""SK-2b Spec §5, §9.4 (RED, written by Claude): a record's invalidation reaches every method step.

The material side (SK-1) invalidates a record; the method side only follows it: the copy leaves the
discovery base, no candidate is made from it, and the method that rested on it leaves Active.
"""

from collections.abc import Callable

import pytest

from insurance_harness.bundle.client import Release
from insurance_harness.compilers.methods.candidates import method_candidates
from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.compilers.methods.copies import CopyBook, empty_book, sync_copies
from insurance_harness.ingest.detach import detach
from insurance_harness.ingest.method_uses import expire_method_uses
from insurance_harness.ingest.registry import ProductRegistry
from tests.compilers.methods.discovery_helpers import (
    DISCOVERY_KB,
    DiscoveryWorld,
    FakePlatform,
    chunk,
    page,
)
from tests.compilers.methods.helpers import DECK_A, METHOD_A, FakeModel, full_answer, release_from
from tests.ingest.upload_helpers import SPACE

CARDS = ("method_summary", "method_steps", "key_phrases", "applicable_scenario", "cautions")
ALL_A = [text for slide in DECK_A for text in slide]


def detached(world: DiscoveryWorld) -> ProductRegistry:
    return detach(world.registry, "k-deck-a", "not_product_material")


def withdrawn(world: DiscoveryWorld) -> ProductRegistry:
    registry = world.registry.model_copy(deep=True)
    expire_method_uses(registry, [world.raws["k-deck-c"]])  # deck A is no longer listed
    return registry


@pytest.mark.parametrize("invalidate", [detached, withdrawn])
def test_an_invalidated_material_leaves_discovery_candidates_and_active(
    invalidate: Callable[[DiscoveryWorld], ProductRegistry],
) -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    book: CopyBook = sync_copies(
        world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True
    ).book
    copy_a = next(c.copy_knowledge_id for c in book.copies if c.knowledge_id == "k-deck-a")
    pages = [page(METHOD_A, chunk(copy_a, *ALL_A))]
    first = method_candidates(
        world.registry, book, platform.listing(DISCOVERY_KB), pages, world.reader
    )
    run = compile_methods(
        world.registry, first.candidates, pages=world.reader,
        port=FakeModel({METHOD_A: full_answer}), active=None,
    )
    assert run.bundle is not None
    active: Release = release_from(run.bundle)
    world.registry = run.registry  # the admitted method, then SK-1 invalidates deck A's record
    world.registry = invalidate(world)
    (method,) = world.registry.methods

    plan = sync_copies(world.registry, book, platform, live=False)
    assert plan.report["counts"] == {"kept": 1, "stale": 1}

    again = method_candidates(
        world.registry, book, platform.listing(DISCOVERY_KB), pages, world.reader
    )
    assert again.candidates.candidates == ()
    assert again.report["counts"] == {"METHOD_USE_NOT_ACTIVE": 1}

    later = compile_methods(
        world.registry, again.candidates, pages=world.reader, port=FakeModel({}), active=active
    )
    assert later.bundle is not None and later.bundle.members == []
    assert later.bundle.removals == sorted(
        [*(f"{method.method_id}/{card}" for card in CARDS), f"entity/{method.method_id}"]
    )
    assert later.registry.methods[0].links == method.links  # links are never rewritten
