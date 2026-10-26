"""S5b-3c-2 acceptance (protected, written by Claude): questions for a person are pushed as
confirmation items, answers come back, are applied to the registry and the items closed.

Spec docs/design/slices/S5b-3c-2-待确认材料的推送与应用.md §2, §4. Questions are raised the way
S5b-2 raises them, from real openings of endowment, accident, critical illness and annuity
products; the platform is a fake that keeps the S5b-3a rules.
"""

import pytest

from insurance_harness.bundle.client import ConfirmationInput, PlatformClient, PlatformError
from insurance_harness.identity.attribution import load_attribution_policy
from insurance_harness.identity.confirmation import choices
from insurance_harness.ingest.confirmations import load_wording, question_of, sync
from insurance_harness.ingest.registry import ConfirmationRef, DecisionEntry
from insurance_harness.ingest.uploads import attribute_uploads
from tests.ingest.confirmation_platform import PREFIX, FakePlatform
from tests.ingest.confirmation_scenarios import (
    BASE,
    UNNAMED,
    UPLOADS,
    Saves,
    asked,
    only_item,
    pages,
    product_key,
    products,
    run,
    waiting,
)
from tests.ingest.upload_helpers import PRODUCTS, SPACE, Pages, raw

# 1. Pushing ---------------------------------------------------------------------------------------


def test_each_question_for_a_person_is_pushed_once_and_quarantine_is_not() -> None:
    current = asked(products(), *UPLOADS)
    assert waiting(current) == ["k-new", "k-scan", "k-two", "k-unnamed"]
    platform = FakePlatform()
    first, saves = run(current, platform)
    entries = sorted(
        (p for p in current.pending if p.knowledge_id != "k-orphan"), key=lambda p: p.knowledge_id
    )
    pushed = [
        {k: platform.view(i)[k] for k in ("subject", "revision", "title", "detail", "options")}
        for i in platform.items
    ]
    # S5b-3d-1: the pushed detail ends with the opening the fake reader gives for the material.
    assert pushed == [
        question_of(e, current, head=UPLOADS[e.knowledge_id][1]).model_dump() for e in entries
    ]
    for e in entries:
        [item] = platform.find(f"material:{e.knowledge_id}")
        assert [o["key"] for o in item["options"]] == [
            c.key for c in choices(e.attribution, current.registered())
        ]
    assert platform.find("material:k-orphan") == []
    assert (first.registry, saves) == (current, [])
    assert first.report.pushed == ["k-new", "k-scan", "k-two", "k-unnamed"]
    assert first.report.waiting == 4

    again, saves = run(first.registry, platform)
    assert len(platform.items) == 4
    assert (again.registry, saves, platform.closed) == (current, [], [])


# 2. Applying an answer ----------------------------------------------------------------------------


def test_an_answer_is_applied_once_after_its_item_is_closed() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    answer_id = platform.answer(item_id, "replace", note="以新版为准")
    second, saves = run(first.registry, platform)
    assert platform.closed == [(item_id, "applied", answer_id)]
    decision = second.registry.decisions[-1]
    assert decision.attribution.outcome == "REPLACE"
    assert decision.confirmation == ConfirmationRef(
        item_id=item_id, answer_id=answer_id, option_key="replace", answerer="user:alice"
    )
    assert [m.knowledge_id for m in second.registry.products["1818"].retired] == ["k-1818-brochure"]
    assert second.registry.pending == []
    assert saves[-1] == second.registry
    assert (second.report.applied, second.report.waiting) == (["k-new"], 0)

    third, saves = run(second.registry, platform)
    assert platform.closed == [(item_id, "applied", answer_id)]
    assert (third.registry, saves, third.report.applied) == (second.registry, [], [])


# 3. The next question ---------------------------------------------------------------------------


def test_a_choice_that_raises_the_next_question_pushes_it_in_the_same_run() -> None:
    first, _ = run(asked(products(), "k-two"), platform := FakePlatform())
    old = only_item(platform, "k-two")
    answer_id = platform.answer(old, product_key("1814"))
    second, _ = run(first.registry, platform)
    assert platform.closed == [(old, "applied", answer_id)]
    [waits] = second.registry.pending
    assert (waits.attribution.reason, waits.attribution.product_id) == ("same_role_differs", "1814")
    items = platform.find("material:k-two")
    assert len(items) == 2 and items[0]["revision"] != items[1]["revision"]
    new = str(items[1]["id"])
    assert "closure" not in items[1]
    assert [o["key"] for o in items[1]["options"]] == ["replace", "supplement", "ignore"]
    assert second.report.pushed == ["k-two"]

    platform.answer(new, "supplement")
    third, _ = run(second.registry, platform)
    assert [m.knowledge_id for m in third.registry.products["1814"].materials] == [
        "k-1814-brochure",
        "k-1814-terms",
        "k-two",
    ]
    assert third.registry.pending == []


# 4. A choice the registry has overtaken -----------------------------------------------------------


def test_a_choice_that_no_longer_applies_reopens_the_material_for_judging() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    first_revision = platform.view(item_id)["revision"]
    changed = first.registry.model_copy(deep=True)
    materials = changed.products["1818"].materials
    brochure = materials.pop(next(i for i, m in enumerate(materials) if m.role == "brochure"))
    platform.answer(item_id, "replace")
    second, _ = run(changed, platform)
    assert platform.closed == [(item_id, "obsolete", None)]
    assert second.registry.pending == []
    assert second.report.reopened == ["k-new"]
    judged = attribute_uploads(second.registry, [UPLOADS["k-new"][0]], pages())
    assert judged.report.counts == {"SUPPLEMENT": 1}

    # Judged again into the very same question, it is a new item, not the closed one.
    restored = second.registry.model_copy(deep=True)
    restored.products["1818"].materials.append(brochure)
    again = attribute_uploads(restored, [UPLOADS["k-new"][0]], pages()).registry
    [question] = again.pending
    assert question.attribution == first.registry.pending[0].attribution
    third, _ = run(again, platform)
    items = platform.find("material:k-new")
    assert len(items) == 2 and items[1]["revision"] != first_revision and "closure" not in items[1]
    assert third.report.pushed == ["k-new"]


# 5. Concurrent change of mind ---------------------------------------------------------------------


def test_a_newer_answer_before_closing_is_taken_on_the_next_run() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    item_id = only_item(platform, "k-new")
    platform.answer(item_id, "replace")

    def change_of_mind(target: str) -> None:
        platform.before_close = None
        platform.answer(target, "supplement")

    platform.before_close = change_of_mind
    second, saves = run(first.registry, platform)
    assert platform.closed == []
    # The settlement is saved before closing and cleared on ANSWER_STALE (Spec §2.2).
    assert second.registry == saves[-1] == first.registry
    assert second.report.skipped == {"ANSWER_STALE": 1}
    third, _ = run(second.registry, platform)
    [(_, reason, answer_id)] = platform.closed
    assert (reason, answer_id) == ("applied", platform.answers[item_id][-1]["id"])
    assert third.registry.decisions[-1].attribution.outcome == "SUPPLEMENT"


# 7. Cleaning up -----------------------------------------------------------------------------------


def test_items_no_longer_asked_are_closed_and_other_submitters_are_left_alone() -> None:
    current = asked(products(), "k-new")
    platform = FakePlatform()
    options = [{"key": "ignore", "label": "忽略"}]
    gone = platform.add("material:k-gone", "r1", "已处理的材料", options)
    foreign = platform.add("other:item-1", "r1", "别的提交方", options)
    result, _ = run(current, platform)
    assert (gone, "obsolete", None) in platform.closed
    assert foreign not in platform.closures
    assert result.report.obsoleted == ["k-gone"]

    reworded = load_wording().model_copy(update={"title": "请确认「{file}」"})
    old = only_item(platform, "k-new")
    client = PlatformClient(BASE, "key", transport=platform.transport())
    sync(result.registry, client, pages(), write=True, save=Saves(), wording=reworded)
    items = platform.find("material:k-new")
    assert platform.closures[old]["reason"] == "obsolete"
    assert len(items) == 2 and items[1]["revision"] == items[0]["revision"]
    assert items[1]["title"].startswith("请确认「")


# 8. Dry run ---------------------------------------------------------------------------------------


def test_a_dry_run_only_reads_and_reports_what_the_run_then_does() -> None:
    first, _ = run(asked(products(), "k-new", "k-two"), platform := FakePlatform())
    platform.answer(only_item(platform, "k-new"), "replace")
    platform.answer(only_item(platform, "k-two"), product_key("1814"))
    platform.add("material:k-gone", "r1", "已处理的材料", [{"key": "ignore", "label": "忽略"}])
    writes = len(platform.writes)
    dry, saves = run(first.registry, platform, write=False)
    assert (len(platform.writes), saves) == (writes, [])
    real, _ = run(first.registry, platform)
    assert dry.report == real.report
    assert dry.registry == real.registry
    assert real.report.pushed == ["k-new", "k-two"]
    assert real.report.applied == ["k-new", "k-two"]
    assert real.report.obsoleted == ["k-gone"]


# 9. A page that cannot be read --------------------------------------------------------------------


def test_an_unreadable_material_is_skipped_and_the_rest_applied() -> None:
    first, _ = run(asked(products(), "k-new", "k-scan"), platform := FakePlatform())
    platform.answer(only_item(platform, "k-new"), "supplement")
    platform.answer(only_item(platform, "k-scan"), "role:brochure")
    second, _ = run(first.registry, platform, reader=pages("k-scan"))
    assert second.report.applied == ["k-new"]
    assert second.report.skipped == {"SOURCE_UNAVAILABLE": 1}
    assert waiting(second.registry) == ["k-scan"]
    third, _ = run(second.registry, platform)
    assert third.report.applied == ["k-scan"]


# 10. Wording --------------------------------------------------------------------------------------


def labels(question: ConfirmationInput) -> list[str]:
    return [option.label for option in question.options]


def test_the_wording_states_the_facts_within_the_platform_limits() -> None:
    long_name = "很长的材料名称" * 40 + "产品说明书.pdf"
    current = asked(products(), *UPLOADS)
    entries = {p.knowledge_id: p for p in current.pending}
    long_entry = entries["k-new"].model_copy(update={"file_name": long_name})
    wording = load_wording()
    policy = load_attribution_policy()
    for kid, e in [*entries.items(), ("long", long_entry)]:
        if e.attribution.outcome != "NEEDS_CONFIRM":
            continue
        question = question_of(e, current)
        assert 0 < len(question.title) <= 200 and len(question.detail) <= 2000
        assert all(0 < len(label) <= 200 for label in labels(question))
        visible = "\n".join([question.title, question.detail, *labels(question)])
        for internal in (
            "material:",
            question.revision,
            e.knowledge_id,
            *(o.key for o in question.options),
        ):
            assert internal not in visible, (kid, internal)
    long_title = question_of(long_entry, current).title
    assert "…" in long_title
    assert len(long_title) <= 200

    same_role = question_of(entries["k-new"], current)
    assert (
        PRODUCTS["1818"]["name"] in same_role.detail
        and wording.roles["brochure"] in same_role.detail
    )
    assert entries["k-new"].file_name in same_role.title
    two = question_of(entries["k-two"], current)
    for pid in ("1814", "1828"):
        assert PRODUCTS[pid]["name"] in two.detail
        assert any(PRODUCTS[pid]["name"] in label for label in labels(two))
    scan = question_of(entries["k-scan"], current)
    assert PRODUCTS["1830"]["name"] in scan.detail
    roles = ("terms", "brochure", "rate_table")
    assert all(wording.roles[r] in label for r, label in zip(roles, labels(scan)[:3], strict=True))
    unnamed = question_of(entries["k-unnamed"], current)
    assert UNNAMED in unnamed.detail and PRODUCTS["1826"]["clause_code"] in unnamed.detail
    suffixes = {c.schema_pack_id: c.suffix for c in reversed(policy.classifications)}
    for option in unnamed.options[:-1]:
        assert suffixes[option.key.removeprefix("pack:")] in option.label


def test_a_platform_failure_ends_the_run_keeping_what_was_applied() -> None:
    first, _ = run(asked(products(), "k-new", "k-scan"), platform := FakePlatform())
    platform.answer(only_item(platform, "k-new"), "supplement")
    platform.answer(only_item(platform, "k-scan"), "role:brochure")
    platform.fail_closures_after = 1
    saves = Saves()
    with pytest.raises(PlatformError) as failure:
        run(first.registry, platform, save=saves)
    assert failure.value.code == "SERVICE_UNAVAILABLE"
    assert [d.knowledge_id for d in saves[-1].decisions if d.confirmation] == ["k-new"]


def test_an_answer_that_cannot_be_recorded_is_not_closed() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    platform.answer(only_item(platform, "k-new"), "replace", answerer="user\talice")
    second, saves = run(first.registry, platform)
    assert (platform.closed, saves) == ([], [])
    assert second.registry == first.registry
    assert second.report.skipped == {"ANSWER_INVALID": 1}


def test_a_conclusion_the_registry_refuses_is_not_closed() -> None:
    current = asked(products(), "k-new")
    waits = current.pending[0]
    seen = current.model_copy(deep=True)
    seen.decisions.append(
        DecisionEntry(
            knowledge_id=waits.knowledge_id,
            parse_attempt=waits.parse_attempt,
            sha256=waits.sha256,
            attribution=waits.attribution,
            confirmation=ConfirmationRef(
                item_id="item-0000",
                answer_id="answer-0002",
                option_key="ignore",
                answerer="user:bob",
            ),
        )
    )
    first, _ = run(seen, platform := FakePlatform())
    assert platform.answer(only_item(platform, "k-new"), "replace") == "answer-0002"
    second, saves = run(first.registry, platform)
    assert (platform.closed, saves) == ([], [])
    assert second.registry == first.registry
    assert second.report.skipped == {"CONFIRMATION_RECORDED": 1}


# Review R4, R6–R8 ---------------------------------------------------------------------------------


def test_a_question_that_cannot_be_worded_keeps_its_item() -> None:
    first, _ = run(asked(products(), "k-new", "k-scan"), platform := FakePlatform())
    kept = only_item(platform, "k-new")
    renamed = first.registry.model_copy(deep=True)
    renamed.products["1818"].names = ["很长的产品名称" * 300]  # the detail exceeds the limit
    platform.answer(only_item(platform, "k-scan"), "role:brochure")
    second, _ = run(renamed, platform)
    assert second.report.skipped == {"WORDING_INVALID": 1}
    assert second.report.applied == ["k-scan"]
    assert kept not in platform.closures
    assert waiting(second.registry) == ["k-new"]


def test_a_dry_run_counts_a_closed_item_the_run_would_meet() -> None:
    first, _ = run(asked(products(), "k-new"), platform := FakePlatform())
    client = PlatformClient(BASE, "key", transport=platform.transport())
    client.close_confirmation(SPACE, only_item(platform, "k-new"), "obsolete")
    dry, _ = run(first.registry, platform, write=False)
    real, _ = run(first.registry, platform)
    assert dry.report == real.report
    assert real.report.skipped == {"CONFIRMATION_CLOSED": 1}


def test_text_the_platform_trims_does_not_make_a_fresh_item_obsolete() -> None:
    reworded = load_wording().model_copy(update={"title": " 请确认「{file}」 \n"})
    platform = FakePlatform()
    client = PlatformClient(BASE, "key", transport=platform.transport())
    result = sync(
        asked(products(), "k-new"), client, pages(), write=True, save=Saves(), wording=reworded
    )
    [item] = platform.find("material:k-new")
    assert platform.closed == []
    assert item["title"].startswith("请确认「") and item["title"].endswith("」")
    assert result.report.obsoleted == []


def test_long_wording_is_pushed_in_batches_the_platform_accepts() -> None:
    long_name = "很长的材料名称" * 250 + "产品说明书.pdf"
    head = UPLOADS["k-new"][1]
    sources = [
        raw(
            "1818",
            "brochure",
            knowledge_id=f"k-long-{n:03d}",
            sha256=f"{n:064x}",
            file_name=long_name,
        )
        for n in range(1, 101)
    ]
    reader = Pages(heads={s.knowledge_id: head for s in sources}, sources=sources)
    current = attribute_uploads(products(), sources, reader).registry
    assert len(waiting(current)) == 100
    platform = FakePlatform()
    result, _ = run(current, platform, reader=reader)
    assert len(platform.items) == 100
    assert platform.writes.count(PREFIX) >= 2
    assert result.report.pushed == sorted(s.knowledge_id for s in sources)
