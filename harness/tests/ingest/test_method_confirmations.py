"""SK-1 acceptance (written by Claude): the method-scope question and how its answer is applied.

Spec docs/design/slices/SK-1-方法用途登记与方法材料归属.md §4, §7 item 6. A method use whose
insurance category the machine could not decide is asked on the confirmation page under its own
subject; the revision covers the evidence, so changed evidence is a new question and an answer to
the old one is stale. An answer is saved before its item is closed and executed afterwards, so an
interrupted run completes it. Ignoring ends a method-only material, but only the method use of a
material that also belongs to a product. Texts are invented.
"""

from collections.abc import Callable

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.ingest.method_confirmations import (
    SUBJECT_PREFIX,
    MethodConfirmationRun,
    method_choices,
    method_question,
    sync_methods,
)
from insurance_harness.ingest.registry import ProductRegistry
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import BASE, Crash, Saves
from tests.ingest.method_helpers import METHOD_SLIDES, nursing_entry, v2
from tests.ingest.test_method_uses import BRAND_DECK, BRAND_SLIDES, judged, only_use

TWO_CATEGORIES = (("重疾险与医疗险销售方法",), *METHOD_SLIDES[1:])
DECK = "保障销售方法课程.pptx"


def waiting_method() -> ProductRegistry:
    current = judged(v2(), {"k-deck": (DECK, TWO_CATEGORIES, "d" * 64)})
    assert only_use(current).state == "awaiting_scope"
    return current


def sync(
    current: ProductRegistry,
    platform: FakePlatform,
    save: Callable[[ProductRegistry], None] | None = None,
    *,
    write: bool = True,
) -> MethodConfirmationRun:
    client = PlatformClient(BASE, "key", transport=platform.transport())
    return sync_methods(current, client, write=write, save=save if save is not None else Saves())


def item_of(platform: FakePlatform) -> str:
    found = platform.find(SUBJECT_PREFIX + "k-deck")
    [item] = [i for i in found if i["id"] not in platform.closures]
    return str(item["id"])


# The question (Spec §4.1) -------------------------------------------------------------------------


def test_the_question_has_its_own_subject_source_and_single_choices() -> None:
    current = waiting_method()
    use = only_use(current)
    question = method_question(use)
    assert question.subject == "method:k-deck"
    assert question.source_ref is not None and "d" * 64 in question.source_ref
    keys = [option.key for option in question.options]
    assert keys[0] == "scope:suggested"  # two categories hit: their combination first
    assert "scope:general" in keys and keys[-1] == "ignore"
    assert {"scope:critical_illness_insurance", "scope:medical_insurance"} <= set(keys)
    assert len(keys) == len(set(keys))
    assert [c.key for c in method_choices(use)] == keys


def test_changed_evidence_is_a_new_revision() -> None:
    use = only_use(waiting_method())
    other = use.model_copy(update={"evidence_digest": "f" * 64})
    assert method_question(use).revision != method_question(other).revision
    assert method_question(use).revision == method_question(use).revision


def test_machine_decided_and_settled_uses_are_not_asked() -> None:
    platform = FakePlatform()
    decided = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    report = sync(decided, platform).report
    assert report.pushed == [] and platform.find(SUBJECT_PREFIX + "k-deck") == []


# Applying an answer (Spec §4.2–§4.4) ----------------------------------------------------------


def test_an_answer_is_applied_as_a_persons_decision() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    assert first.report.pushed == ["k-deck"]
    platform.answer(item_of(platform), "scope:suggested")
    second = sync(first.registry, platform)
    use = only_use(second.registry)
    assert use.state == "active" and use.decided_by == "person"
    assert use.categories == ("critical_illness_insurance", "medical_insurance")
    assert use.confirmation is not None and use.confirmation.option_key == "scope:suggested"
    assert use.settlement is None
    assert second.report.applied == ["k-deck"]
    assert [reason for _, reason, _ in platform.closed] == ["applied"]


def test_a_single_category_answer_records_that_category_only() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    platform.answer(item_of(platform), "scope:medical_insurance")
    use = only_use(sync(first.registry, platform).registry)
    assert use.categories == ("medical_insurance",)


def test_an_answer_to_a_question_whose_evidence_changed_is_stale() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    platform.answer(item_of(platform), "scope:general")
    changed = first.registry.model_copy(deep=True)
    changed.method_uses = [
        u.model_copy(update={"evidence_digest": "f" * 64}) for u in changed.method_uses
    ]
    second = sync(changed, platform)
    use = only_use(second.registry)
    assert use.state == "awaiting_scope" and use.categories == ()
    assert second.report.skipped.get("CHOICE_STALE") == 1
    assert ("obsolete" in {reason for _, reason, _ in platform.closed})
    assert second.report.pushed == ["k-deck"]  # asked again with the new evidence


def test_an_interrupted_application_is_completed_from_its_saved_settlement() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    platform.answer(item_of(platform), "scope:general")
    platform.fail_closures_after = 0  # the close fails after the settlement is saved
    crashed = Saves()
    try:
        sync(first.registry, platform, crashed)
    except Exception:  # noqa: BLE001 — a lost close, as an interrupted run sees it
        pass
    saved = crashed[-1]
    assert only_use(saved).settlement is not None
    assert only_use(saved).state == "awaiting_scope"
    platform.fail_closures_after = None
    finished = sync(saved, platform)
    use = only_use(finished.registry)
    assert use.state == "active" and use.categories == ("scope:general",)
    assert use.settlement is None


def test_a_crash_while_saving_leaves_nothing_half_done() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    platform.answer(item_of(platform), "scope:general")
    crash = Crash(on_call=1)
    try:
        sync(first.registry, platform, crash)
    except OSError:
        pass
    assert platform.closed == []  # nothing closed before the settlement was saved


def test_ignoring_a_method_only_material_ends_it() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    platform.answer(item_of(platform), "ignore")
    after = sync(first.registry, platform).registry
    [use] = after.method_uses
    assert (use.state, use.decided_by) == ("ignored", "person")
    assert after.pending == []
    decision = after.decisions[-1]
    assert decision.attribution.outcome == "IGNORED"
    assert decision.confirmation is not None and decision.confirmation.option_key == "ignore"


def test_ignoring_the_method_use_of_a_product_material_keeps_the_product_use() -> None:
    slides = (("智盈倍护销售方法课程", "2024年5月", "重疾险与医疗险"), *METHOD_SLIDES[1:])
    current = judged(v2(**{"2635": nursing_entry()}), {"k-deck": (BRAND_DECK, slides, "d" * 64)})
    assert only_use(current).state == "awaiting_scope"
    platform = FakePlatform()
    first = sync(current, platform)
    platform.answer(item_of(platform), "ignore")
    after = sync(first.registry, platform).registry
    assert only_use(after).state == "ignored"
    assert "k-deck" in {m.knowledge_id for m in after.products["2635"].materials}
    assert all(d.attribution.outcome != "IGNORED" for d in after.decisions)


def test_a_dry_run_writes_nothing() -> None:
    platform = FakePlatform()
    report = sync(waiting_method(), platform, write=False).report
    assert report.pushed == ["k-deck"] and platform.writes == []


def test_the_product_question_flow_never_asks_a_method_material() -> None:
    from tests.ingest.confirmation_scenarios import run  # the S5b-3c-2 product sync

    platform = FakePlatform()
    current = judged(v2(), {"k-deck": (DECK, METHOD_SLIDES, "d" * 64)})
    result, _ = run(current, platform)
    assert result.report.pushed == []
    assert platform.find("material:k-deck") == []
    assert BRAND_SLIDES  # shared fixture stays importable
