"""SK-1 acceptance (written by Claude): the scope-label question and how its answers are applied.

Spec docs/design/slices/SK-1-方法用途登记与方法材料归属.md §4, §7 item 6 (r3). The machine labels
every method use whose blocks hit a label; only a use that hit none, or one a person asked to
correct (`relabel`), is asked on the confirmation page, under its own subject. The page takes one
choice per answer, so labels are chosen one at a time — add, remove, done — and the next step is
asked in the same run. Every step is a new revision, so an answer to an older one is stale. An
answer is saved before its item is closed and executed afterwards, so an interrupted run completes
it. Ignoring ends a method-only material, but only the method use of a material that also belongs
to a product. Texts are invented.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.catalog.sales_taxonomy import load_sales_taxonomy
from insurance_harness.ingest.confirmation_questions import ConfirmationsError
from insurance_harness.ingest.method_confirmations import (
    SUBJECT_PREFIX,
    MethodConfirmationRun,
    method_choices,
    method_question,
    request_relabel,
    sync_methods,
)
from insurance_harness.ingest.registry import ProductRegistry, load_registry, save_registry
from insurance_harness.ingest.uploads import main
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import BASE, Crash, Saves
from tests.ingest.method_helpers import METHOD_SLIDES, nursing_entry, v2
from tests.ingest.test_method_uses import BRAND_DECK, judged, only_use

NO_LABEL = (("家庭保障销售方法课程", "2024年5月"), *METHOD_SLIDES[1:])  # no category word at all
TWO_CATEGORIES = (("重疾险与医疗险销售方法",), *METHOD_SLIDES[1:])
DECK = "保障销售方法课程.pptx"
BOTH = ("critical_illness_insurance", "medical_insurance")


def waiting_method() -> ProductRegistry:
    current = judged(v2(), {"k-deck": (DECK, NO_LABEL, "d" * 64)})
    assert only_use(current).state == "awaiting_scope"
    return current


def labelled_method() -> ProductRegistry:
    return judged(v2(), {"k-deck": (DECK, TWO_CATEGORIES, "d" * 64)})


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


def open_keys(platform: FakePlatform) -> list[str]:
    [item] = [i for i in platform.find(SUBJECT_PREFIX + "k-deck") if i["id"] == item_of(platform)]
    return [option["key"] for option in item["options"]]


def answered(current: ProductRegistry, platform: FakePlatform, *keys: str) -> ProductRegistry:
    """Answer the open item with each key in turn, one run after each answer."""
    for key in keys:
        platform.answer(item_of(platform), key)
        current = sync(current, platform).registry
    return current


# The question (Spec §4.1) -------------------------------------------------------------------------


def test_a_use_without_any_label_is_asked_with_each_label_once() -> None:
    use = only_use(waiting_method())
    question = method_question(use)
    assert question.subject == "method:k-deck"
    assert question.source_ref is not None and "d" * 64 in question.source_ref
    keys = [option.key for option in question.options]
    assert {"add:critical_illness_insurance", "add:scope:general"} <= set(keys)
    assert keys[-1] == "ignore" and "done" not in keys
    assert not any(key.startswith("remove:") for key in keys)
    assert len(keys) == len(set(keys)) == len(load_sales_taxonomy().insurance_labels()) + 2
    assert [c.key for c in method_choices(use)] == keys


def test_machine_labelled_uses_are_never_asked() -> None:
    labelled = labelled_method()
    use = only_use(labelled)
    assert (use.state, use.decided_by, use.editing, use.categories) == (
        "active",
        "machine",
        False,
        BOTH,
    )
    platform = FakePlatform()
    report = sync(labelled, platform).report
    assert report.pushed == [] and report.waiting == 0
    assert platform.find(SUBJECT_PREFIX + "k-deck") == []


def test_changed_evidence_is_a_new_revision() -> None:
    use = only_use(waiting_method())
    other = use.model_copy(update={"evidence_digest": "f" * 64})
    assert method_question(use).revision != method_question(other).revision
    assert method_question(use).revision == method_question(use).revision


# Choosing labels one at a time (Spec §4.1, §4.4) --------------------------------------------------


def test_a_first_pick_applies_at_once_and_the_next_step_follows_in_the_same_run() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    assert first.report.pushed == ["k-deck"]
    platform.answer(item_of(platform), "add:medical_insurance")
    second = sync(first.registry, platform)
    use = only_use(second.registry)
    assert (use.state, use.decided_by, use.editing) == ("active", "person", True)
    assert use.categories == ("medical_insurance",) and use.settlement is None
    assert use.confirmation is not None and use.confirmation.option_key == "add:medical_insurance"
    assert second.report.applied == ["k-deck"] and second.report.pushed == ["k-deck"]
    follow = open_keys(platform)
    assert "done" in follow and "add:medical_insurance" not in follow
    assert not any(key.startswith("remove:") for key in follow)  # the only label: add another first


def test_several_labels_are_chosen_one_at_a_time_until_done() -> None:
    platform = FakePlatform()
    current = sync(waiting_method(), platform).registry
    current = answered(current, platform, "add:medical_insurance", "add:scope:general")
    assert "remove:medical_insurance" in open_keys(platform)
    platform.answer(item_of(platform), "done")
    done = sync(current, platform)
    use = only_use(done.registry)
    assert use.categories == ("medical_insurance", "scope:general")
    assert (use.decided_by, use.editing) == ("person", False)
    assert done.report.waiting == 0
    assert sync(done.registry, platform).report.pushed == []  # nothing is asked any more
    assert [reason for _, reason, _ in platform.closed] == ["applied"] * 3
    assert set(platform.items) == set(platform.closures)  # nothing left open


def test_a_label_can_be_removed_while_another_stays() -> None:
    platform = FakePlatform()
    current = sync(waiting_method(), platform).registry
    current = answered(current, platform, "add:medical_insurance", "add:critical_illness_insurance")
    current = answered(current, platform, "remove:medical_insurance", "done")
    assert only_use(current).categories == ("critical_illness_insurance",)


# Correcting the labels (Spec §4.5) ----------------------------------------------------------------


def test_a_person_corrects_machine_labels_through_the_same_question() -> None:
    labelled = labelled_method()
    asked = request_relabel(labelled, "k-deck")
    assert only_use(asked).editing and not only_use(labelled).editing  # the input is untouched
    platform = FakePlatform()
    first = sync(asked, platform)
    assert first.report.pushed == ["k-deck"]
    offered = set(open_keys(platform))
    assert {f"remove:{label}" for label in BOTH} | {"done", "ignore"} <= offered
    corrected = answered(first.registry, platform, "remove:medical_insurance", "done")
    use = only_use(corrected)
    assert use.categories == ("critical_illness_insurance",)
    assert (use.decided_by, use.editing) == ("person", False)
    assert tuple(hit.label for hit in use.label_hits) == BOTH  # the machine's evidence stays


def test_relabel_needs_a_live_record_and_leaves_an_asked_one_as_it_is() -> None:
    with pytest.raises(ConfirmationsError) as refused:
        request_relabel(v2(), "k-deck")
    assert refused.value.code == "METHOD_USE_NOT_FOUND"
    waiting = waiting_method()
    assert request_relabel(waiting, "k-deck").method_uses == waiting.method_uses


def test_the_relabel_command_holds_the_lock_and_honours_dry_run(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    save_registry(labelled_method(), path)
    before = path.read_bytes()
    command = ["relabel", "--registry", str(path), "--knowledge-id", "k-deck"]
    assert main([*command, "--dry-run"]) == 0
    assert path.read_bytes() == before
    assert main(command) == 0
    assert only_use(load_registry(path)).editing
    assert main(["relabel", "--registry", str(path), "--knowledge-id", "k-none"]) == 1


# Re-validation and the commit discipline (Spec §4.2, §4.3) ----------------------------------------


def test_an_answer_to_a_question_whose_evidence_changed_is_stale() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    platform.answer(item_of(platform), "add:scope:general")
    changed = first.registry.model_copy(deep=True)
    changed.method_uses = [
        u.model_copy(update={"evidence_digest": "f" * 64}) for u in changed.method_uses
    ]
    second = sync(changed, platform)
    use = only_use(second.registry)
    assert use.state == "awaiting_scope" and use.categories == ()
    assert second.report.skipped.get("CHOICE_STALE") == 1
    assert "obsolete" in {reason for _, reason, _ in platform.closed}
    assert second.report.pushed == ["k-deck"]  # asked again with the new evidence


def test_an_interrupted_application_is_completed_from_its_saved_settlement() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    platform.answer(item_of(platform), "add:scope:general")
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
    assert (use.state, use.categories, use.editing) == ("active", ("scope:general",), True)
    assert use.settlement is None


def test_a_crash_while_saving_leaves_nothing_half_done() -> None:
    platform = FakePlatform()
    first = sync(waiting_method(), platform)
    platform.answer(item_of(platform), "add:scope:general")
    crash = Crash(on_call=1)
    try:
        sync(first.registry, platform, crash)
    except OSError:
        pass
    assert platform.closed == []  # nothing closed before the settlement was saved


# Ignoring (Spec §4.4) -----------------------------------------------------------------------------


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
    slides = (("智盈倍护销售方法课程", "2024年5月"), *METHOD_SLIDES[1:])
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
