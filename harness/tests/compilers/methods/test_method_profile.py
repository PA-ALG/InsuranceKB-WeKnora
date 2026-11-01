"""SK-3 acceptance: the method presentation profile and when a compile carries it (Spec
docs/design/slices/SK-3-销售方法阅读与问答.md §1, §2.2).

Protected file: written by Claude. The profile is generated from the method cards: it serves the
cards' entity type, declares method knowledge, carries the reading copy and titles the five cards
in order. A compile that publishes method claims or entities carries it unless the Active release
already holds the same profile; removal-only candidates never do.
"""

from __future__ import annotations

import hashlib
import json

from insurance_harness.bundle.client import Release
from insurance_harness.catalog.method_cards import load_method_cards
from insurance_harness.compilers.methods.profile import method_profile
from insurance_harness.contracts.knowledge import PresentationProfile
from tests.compilers.methods.helpers import (
    METHOD_A,
    METHOD_C,
    FakeModel,
    World,
    candidate,
    compiled,
    full_answer,
    release_from,
    unknown_answer,
)

SLUG = "presentation/sales_method"


def test_the_profile_is_generated_from_the_cards() -> None:
    cards = load_method_cards()
    profile = method_profile(cards)
    assert (profile.profile_id, profile.profile_version, profile.schema_pack_id) == (
        cards.entity_type,
        cards.version,
        cards.review_pack,
    )
    assert profile.entity_types == [cards.entity_type] and profile.knowledge_class == "method"
    assert profile.classification_labels == []
    assert profile.display_name == cards.presentation.display_name == "销售方法"
    assert profile.reading_note == cards.presentation.reading_note
    assert "非产品事实" in (profile.reading_note or "")
    assert set(profile.notices) == {"product_info"}
    (section,) = profile.sections
    assert [(f.field_key, f.short_title, f.description) for f in section.fields] == [
        (card.predicate, card.title, card.definition) for card in cards.cards
    ]
    content = profile.model_dump(mode="json", exclude={"profile_sha256"})
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert profile.profile_sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert method_profile(cards) == profile  # deterministic


def profile_payload(release_or_bundle: object) -> dict[str, object] | None:
    members = getattr(release_or_bundle, "members", [])
    return next((m.payload for m in members if m.logical_slug == SLUG), None)


def test_a_compile_carries_the_profile_until_the_active_release_holds_it() -> None:
    world = World()
    first = compiled(
        world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))], FakeModel({METHOD_A: full_answer})
    )
    assert first.bundle is not None
    payload = profile_payload(first.bundle)
    assert payload == method_profile(load_method_cards()).model_dump(mode="json")
    (member,) = [m for m in first.bundle.members if m.logical_slug == SLUG]
    assert member.kind == "presentation_profile" and member.evidence_refs == []
    PresentationProfile.model_validate(member.payload)

    active = release_from(first.bundle)
    second = compiled(
        world,
        [
            candidate(METHOD_A, world.raw_a, world.hits("k-deck-a")),
            candidate(METHOD_C, world.raw_c, world.hits("k-deck-c")),
        ],
        FakeModel({METHOD_A: full_answer, METHOD_C: unknown_answer}),
        active,
    )
    assert second.bundle is not None and profile_payload(second.bundle) is None

    stripped = Release(
        id=active.id, epoch=active.epoch, members=[m for m in active.members if m.logical_slug != SLUG]
    )
    third = compiled(
        world,
        [candidate(METHOD_C, world.raw_c, world.hits("k-deck-c"))],
        FakeModel({METHOD_C: full_answer}),
        stripped,
    )
    assert third.bundle is not None and profile_payload(third.bundle) is not None
