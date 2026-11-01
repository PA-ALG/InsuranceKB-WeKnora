"""S5b-7 review R3–R4 (protected, written by Claude): revisions and withdrawn answers.

Spec docs/design/slices/S5b-7-正文中的标题行与旧问题重判.md §2.4–§2.5. R3: a question is kept as
asked only for the same material revision; a new revision is recorded as before. R4: an answer on
an item closed as obsolete is reported from the platform's closed items, so a lost close receipt or
an answer that came between listing and closing is still reported, and never becomes a decision.
"""

from typing import Any

from insurance_harness.bundle.client import PlatformError
from insurance_harness.identity.attribution import load_attribution_policy
from insurance_harness.ingest.registry import ProductRegistry
from insurance_harness.ingest.uploads import attribute_uploads
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import run
from tests.ingest.test_policy_rejudge import (
    BRAND,
    OTHER,
    OTHER_BROCHURE,
    PACK_UNRESOLVED,
    SOURCES,
    old_question,
    pages,
    registry,
    uploads_run,
)
from tests.ingest.upload_helpers import Pages


def test_a_new_revision_of_a_quarantined_material_is_recorded_as_before() -> None:
    stale = old_question(
        "k-other", outcome="QUARANTINE", reason="no_product_anchor", role="brochure"
    )
    newer = OTHER.model_copy(update={"parse_attempt": 2, "sha256": "e" * 64})
    reader = Pages(heads={"k-other": OTHER_BROCHURE}, sources=[newer])
    after = attribute_uploads(registry(stale), [newer], reader).registry
    [entry] = after.pending
    assert (entry.parse_attempt, entry.sha256) == (2, "e" * 64)
    assert entry.attribution.policy_ref == load_attribution_policy().policy_ref
    assert [d.parse_attempt for d in after.decisions] == [2]


def test_a_question_of_an_older_revision_still_reports_the_revision_change() -> None:
    newer = SOURCES["k-deck"].model_copy(update={"parse_attempt": 2, "sha256": "f" * 64})
    reader = Pages(heads={"k-deck": "平安e生保\r\n产品亮点"}, sources=[newer])
    run_ = attribute_uploads(registry(BRAND), [newer], reader)
    assert run_.registry.pending == [BRAND], "a person's question is not replaced"
    assert run_.report.revision_changes == ["k-deck"]


def _answered_then_settled(platform: FakePlatform) -> tuple[dict[str, Any], ProductRegistry]:
    """The question is pushed, then the next `uploads run` settles its material automatically."""
    first, _ = run(registry(PACK_UNRESOLVED), platform, reader=pages())
    [item] = platform.find("material:k-terms")
    return item, uploads_run(first.registry)


def test_an_answer_whose_close_receipt_was_lost_is_reported_by_the_next_run() -> None:
    platform = FakePlatform()
    item, settled = _answered_then_settled(platform)
    answer = platform.answer(item["id"], item["options"][0]["key"])
    platform.lose_closure_responses = 1
    try:
        run(settled, platform, reader=pages())
    except PlatformError:
        pass  # the item is closed on the platform, the receipt is lost
    again, _ = run(settled, platform, reader=pages())
    assert platform.closed == [(item["id"], "obsolete", None)]
    assert [(w.knowledge_id, w.item_id, w.answer_id) for w in again.report.answers_withdrawn] == [
        ("k-terms", item["id"], answer)
    ]
    assert all(d.confirmation is None for d in again.registry.decisions)


def test_an_answer_given_between_listing_and_closing_is_reported() -> None:
    platform = FakePlatform()
    item, settled = _answered_then_settled(platform)
    key = item["options"][0]["key"]
    answers: list[str] = []
    platform.before_close = lambda item_id: answers.append(platform.answer(item_id, key))
    result, _ = run(settled, platform, reader=pages())
    assert platform.closed == [(item["id"], "obsolete", None)]
    assert [(w.knowledge_id, w.answer_id) for w in result.report.answers_withdrawn] == [
        ("k-terms", answers[0])
    ]


def test_an_applied_answer_is_not_reported_as_withdrawn() -> None:
    platform = FakePlatform()
    first, _ = run(registry(BRAND), platform, reader=pages())
    [item] = platform.find("material:k-deck")
    platform.answer(item["id"], item["options"][0]["key"])
    result, _ = run(first.registry, platform, reader=pages())
    assert [c[1] for c in platform.closed] == ["applied"]
    assert result.report.answers_withdrawn == []
