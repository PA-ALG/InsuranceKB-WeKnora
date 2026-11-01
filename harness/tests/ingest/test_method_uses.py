"""SK-1 acceptance (written by Claude): material-level method-use records and METHOD_MATERIAL.

Spec docs/design/slices/SK-1-方法用途登记与方法材料归属.md §2.3, §3.3, §3.4, §5,
§7 items 4, 5, 7, 8.
On a v2 registry a training material with method signals gets a method-use record keyed by its
source revision; without a version to attach to it is a METHOD_MATERIAL (not quarantined, judged
again every run, no product question); with a unique version both uses are recorded. Records expire
with their source revision. v1 registries refuse all of it; the product side never changes.
"""

from collections.abc import Mapping, Sequence

import pytest
from pydantic import ValidationError

from insurance_harness.identity.attribution import Attribution
from insurance_harness.ingest.detach import detach
from insurance_harness.ingest.method_use_model import MethodUse
from insurance_harness.ingest.raw_sources import UnfinishedSource
from insurance_harness.ingest.registry import (
    ConfirmationRef,
    DecisionEntry,
    MaterialEntry,
    ProductRegistry,
    RegistryError,
    record,
    registry_document,
)
from insurance_harness.ingest.uploads import attribute_uploads
from tests.ingest.method_helpers import (
    METHOD_SLIDES,
    PLAIN_SLIDES,
    DeckPages,
    deck_pages,
    held,
    nursing_entry,
    source,
    v1,
    v2,
)

DECK = "护理险销售方法课程.pptx"
BRAND_DECK = "智盈倍护销售方法课程.pptx"
BRAND_SLIDES = (("智盈倍护护理险销售方法课程", "2024年5月"), *METHOD_SLIDES[1:])


def judged(
    current: ProductRegistry,
    decks: Mapping[str, tuple[str, Sequence[Sequence[str]], str]],
    unfinished: list[UnfinishedSource] | None = None,
) -> ProductRegistry:
    """One `run` over the listed decks: knowledge id -> (file name, slides, sha256)."""
    sources = [source(kid, name, sha) for kid, (name, _, sha) in decks.items()]
    pages = DeckPages({
        kid: deck_pages(name, sha, slides) for kid, (name, slides, sha) in decks.items()
    })
    return attribute_uploads(current, sources, pages, unfinished=unfinished or []).registry


def only_use(current: ProductRegistry, kid: str = "k-deck") -> MethodUse:
    [use] = [u for u in current.method_uses if u.knowledge_id == kid and u.state != "invalidated"]
    return use


# 4. How the method use combines with the product attribution (Spec §3.3) ------------------------


def test_a_method_deck_without_a_version_is_a_method_material_not_quarantined() -> None:
    after = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    [pending] = after.pending
    assert (pending.attribution.outcome, pending.attribution.reason) == (
        "METHOD_MATERIAL",
        "method_material",
    )
    use = only_use(after)
    assert (use.knowledge_id, use.parse_attempt, use.sha256) == ("k-deck", 1, "d" * 64)
    assert use.role == "sales_method" and use.block_scheme == "segments.v1"
    assert use.state == "active" and use.decided_by == "machine"
    assert use.categories == ("nursing_care_insurance",)
    assert not hasattr(use, "method_id")  # no method identity at this stage (SK-0 §4.3 (a))


def test_a_method_material_is_judged_again_and_attaches_once_its_version_is_registered() -> None:
    deck = {"k-deck": (BRAND_DECK, BRAND_SLIDES, "d" * 64)}
    first = judged(v2(), deck)
    assert first.pending[0].attribution.outcome == "METHOD_MATERIAL"
    later = first.model_copy(deep=True)
    later.products["2635"] = nursing_entry()
    second = judged(later, deck)
    assert second.pending == []
    assert "k-deck" in {m.knowledge_id for m in second.products["2635"].materials}
    assert only_use(second) == only_use(first)  # the same record, not detected twice


def test_a_unique_version_attaches_and_the_method_use_is_recorded_beside_it() -> None:
    deck = {"k-deck": (BRAND_DECK, BRAND_SLIDES, "d" * 64)}
    after = judged(v2(**{"2635": nursing_entry()}), deck)
    assert "k-deck" in {m.knowledge_id for m in after.products["2635"].materials}
    material = next(m for m in after.products["2635"].materials if m.knowledge_id == "k-deck")
    use = only_use(after)
    assert material.role == "sales_training"  # the product use keeps its own role
    assert (use.knowledge_id, use.parse_attempt, use.sha256) == (
        material.knowledge_id,
        material.parse_attempt,
        material.sha256,
    )


def test_a_version_question_waits_and_the_method_use_is_recorded_meanwhile() -> None:
    other_terms = held().model_copy(update={"knowledge_id": "k-terms-2636", "sha256": "7" * 64})
    current = v2(**{
        "2635": nursing_entry(),
        "2636": nursing_entry("2636-1", "2024-04-23", "2024-09-01", [other_terms]),
    })
    after = judged(current, {"k-deck": (BRAND_DECK, BRAND_SLIDES, "d" * 64)})
    [pending] = after.pending
    assert (pending.attribution.outcome, pending.attribution.reason) == (
        "NEEDS_CONFIRM",
        "version_candidates",
    )
    assert only_use(after).state == "active"


def test_a_deck_without_method_signals_stays_quarantined_without_a_record() -> None:
    after = judged(v2(), {"k-deck": ("护理险产品介绍.pptx", PLAIN_SLIDES, "d" * 64)})
    assert after.pending[0].attribution.outcome == "QUARANTINE"
    assert after.method_uses == []


def test_terms_with_method_words_are_never_method_materials() -> None:
    slides = (("平安某某保险条款", "阅读指引"), ("销售方法", "讲解步骤 异议 促成"))
    after = judged(v2(), {"k-terms-x": ("平安某某保险条款.pdf", slides, "f" * 64)})
    assert after.method_uses == []
    assert all(p.attribution.outcome != "METHOD_MATERIAL" for p in after.pending)


# 5. Expiry (Spec §3.4) ----------------------------------------------------------------------


def test_a_new_revision_expires_the_old_record_and_is_detected_afresh() -> None:
    first = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    second = judged(first, {"k-deck": (DECK, METHOD_SLIDES, "9" * 64)})
    old = next(u for u in second.method_uses if u.sha256 == "d" * 64)
    assert (old.state, old.invalidated_reason) == ("invalidated", "source_revised")
    assert only_use(second).sha256 == "9" * 64


def test_a_material_no_longer_listed_expires_but_an_unfinished_one_does_not() -> None:
    first = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    reparsing = [UnfinishedSource(knowledge_id="k-deck", file_name=DECK, state="NOT_CAPTURED_YET")]
    kept = judged(first, {}, unfinished=reparsing)
    assert only_use(kept).state == "active"
    gone = judged(first, {})
    [use] = gone.method_uses
    assert (use.state, use.invalidated_reason) == ("invalidated", "withdrawn")


def test_an_ignored_material_loses_its_method_use() -> None:
    first = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    ignored = first.model_copy(deep=True)
    ignored.decisions.append(
        DecisionEntry(
            knowledge_id="k-deck",
            parse_attempt=1,
            sha256="d" * 64,
            attribution=Attribution(
                outcome="IGNORED", reason="confirmed_ignore", policy_ref="attribution-policy@x"
            ),
            confirmation=ConfirmationRef(
                item_id="i-1", answer_id="a-1", option_key="ignore", answerer="user:alice"
            ),
        )
    )
    after = judged(ignored, {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    [use] = after.method_uses
    assert (use.state, use.invalidated_reason) == ("invalidated", "ignored")


def test_detaching_a_product_material_expires_its_method_use_too() -> None:
    deck = {"k-deck": (BRAND_DECK, BRAND_SLIDES, "d" * 64)}
    after = judged(v2(**{"2635": nursing_entry()}), deck)
    detached = detach(after, "k-deck", "wrong_version")
    [use] = detached.method_uses
    assert (use.state, use.invalidated_reason) == ("invalidated", "detached")


def test_detaching_a_method_only_material_ends_it_for_good() -> None:
    first = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    detached = detach(first, "k-deck", "not_product_material")
    assert detached.pending == []
    [use] = detached.method_uses
    assert (use.state, use.invalidated_reason) == ("invalidated", "detached")
    decision = detached.decisions[-1]
    assert decision.attribution.outcome == "DETACHED"
    assert (decision.attribution.product_id, decision.attribution.role) == (None, "sales_method")
    again = judged(detached, {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    assert again.pending == [] and len(again.method_uses) == 1  # not judged or detected again


# 7. v1 registries refuse it all; 8. the product side is unchanged (Spec §5, §7) ----------------


def test_a_v1_registry_is_never_detected_nor_converted() -> None:
    after = judged(v1(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    assert after.method_uses == []
    assert all(p.attribution.outcome != "METHOD_MATERIAL" for p in after.pending)
    assert b"method_uses" not in registry_document(after)


def test_a_v1_registry_refuses_method_uses_and_method_materials() -> None:
    method = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    document = method.model_dump()
    document.update(contract="product-registry.v1", metadata_basis=None)
    with pytest.raises(ValidationError):
        ProductRegistry.model_validate(document)
    document["method_uses"] = []
    with pytest.raises(ValidationError):  # the METHOD_MATERIAL pending entry and decision
        ProductRegistry.model_validate(document)
    legacy = v1()
    with pytest.raises(RegistryError) as refused:
        record(legacy, source("k-deck", DECK), method.pending[0].attribution)
    assert refused.value.code == "RECORD_INVALID"


def test_method_uses_never_change_the_product_side() -> None:
    before = v2(**{"2635": nursing_entry()})
    after = judged(before, {"k-other": (DECK, METHOD_SLIDES, "d" * 64)})
    assert after.method_uses
    assert after.source_map() == before.source_map()
    assert after.registered() == before.registered()
    assert after.products == before.products


def test_one_record_per_revision_and_one_live_record_per_material() -> None:
    first = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    document = first.model_dump()
    document["method_uses"] = document["method_uses"] * 2
    with pytest.raises(ValidationError):
        ProductRegistry.model_validate(document)
    second = dict(document["method_uses"][0], sha256="9" * 64)
    document["method_uses"] = [document["method_uses"][0], second]
    with pytest.raises(ValidationError):  # two live records for one knowledge id
        ProductRegistry.model_validate(document)


def test_a_machine_decision_is_exactly_the_labels_hit() -> None:
    first = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    document = first.model_dump()
    document["method_uses"][0]["categories"] = ("medical_insurance",)  # not what the blocks hit
    with pytest.raises(ValidationError):
        ProductRegistry.model_validate(document)


# 3.1 Registered sales materials are detected too (Spec §3.1, added after the RED) ---------------


def test_a_sales_material_attached_before_sk1_gets_its_method_use() -> None:
    deck = MaterialEntry(
        knowledge_id="k-deck",
        parse_attempt=1,
        sha256="d" * 64,
        role="sales_training",
        file_name=BRAND_DECK,
    )
    current = v2(**{"2635": nursing_entry(materials=[held(), deck])})
    after = judged(current, {"k-deck": (BRAND_DECK, BRAND_SLIDES, "d" * 64)})
    use = only_use(after)
    assert (use.knowledge_id, use.sha256, use.state) == ("k-deck", "d" * 64, "active")
    assert after.products == current.products  # the product side is unchanged
    again = judged(after, {"k-deck": (BRAND_DECK, BRAND_SLIDES, "d" * 64)})
    assert again.method_uses == after.method_uses  # recorded once


def test_a_registered_terms_material_is_never_backfilled() -> None:
    slides = (("平安某某保险条款", "阅读指引"), ("销售方法", "讲解步骤 异议 促成"))
    terms = held().model_copy(update={"knowledge_id": "k-terms", "file_name": "条款.pdf"})
    current = v2(**{"2635": nursing_entry(materials=[terms])})
    after = judged(current, {"k-terms": ("条款.pdf", slides, "e" * 64)})
    assert after.method_uses == []
