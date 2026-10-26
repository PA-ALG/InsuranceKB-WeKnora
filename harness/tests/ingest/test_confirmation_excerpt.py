"""S5b-3d-1 acceptance (protected, written by Claude): a question shows how the file begins.

Spec docs/design/slices/S5b-3d-1-待确认材料显示文件开头.md §2, §4. The user could not judge an
item from its file name alone (2026-10-26); the detail now ends with the cleaned opening of the
material's first pages. A material whose pages cannot be read is not asked that run and keeps
any item already asked, so a failed read never discards an answer.
"""

from collections import Counter

import pytest

from insurance_harness.ingest.confirmation_questions import (
    ConfirmationsError,
    load_wording,
    question_of,
)
from insurance_harness.ingest.registry import PendingEntry, ProductRegistry
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import UPLOADS, asked, only_item, pages, products, run


def waiting() -> tuple[ProductRegistry, dict[str, PendingEntry]]:
    current = asked(products(), *UPLOADS)
    entries = {
        p.knowledge_id: p for p in current.pending if p.attribution.outcome == "NEEDS_CONFIRM"
    }
    assert entries
    return current, entries


def test_the_detail_ends_with_the_cleaned_opening_of_the_file() -> None:
    current, entries = waiting()
    entry = next(iter(entries.values()))
    head = (
        "《平安示例年金保险》转换标准表\n(每万元保单账户价值转换的领取金额)\t女性　"
        "单位:人民币元\x0c领取方式\x07"
    )
    other = question_of(entry, current, head="另一份文件的开头")
    question = question_of(entry, current, head=head)
    reason = other.detail.rsplit("\n", 1)[0]
    assert reason.startswith("文件：")
    assert question.detail == (
        reason + "\n文件开头：《平安示例年金保险》转换标准表 (每万元保单账户价值转换的领取金额) "
        "女性 单位:人民币元 领取方式"
    )
    assert (question.subject, question.title) == (other.subject, other.title)


def test_a_long_opening_is_cut_with_an_ellipsis_within_the_limit() -> None:
    current, entries = waiting()
    for entry in entries.values():
        question = question_of(entry, current, head="长" * 1000)
        assert question.detail.rsplit("\n", 1)[1] == "文件开头：" + "长" * 300 + "…"
        assert len(question.detail) <= 2000


def test_first_pages_without_text_cannot_be_asked() -> None:
    current, entries = waiting()
    for entry in entries.values():
        with pytest.raises(ConfirmationsError) as error:
            question_of(entry, current, head=" \n\t\x07")
        assert error.value.code == "QUESTION_INVALID"


def test_the_wording_is_versioned() -> None:
    wording = load_wording()
    assert wording.version == "2026-10-26.1"
    assert wording.excerpt_chars == 300


def test_each_pushed_question_shows_its_file_and_an_unreadable_one_waits() -> None:
    current, entries = waiting()
    unreadable = sorted(entries)[0]
    reader = pages(unreadable)
    platform = FakePlatform()
    result, _ = run(current, platform, reader=reader)
    assert sorted(result.report.pushed) == sorted(set(entries) - {unreadable})
    assert result.report.skipped == {"SOURCE_UNAVAILABLE": 1}
    assert platform.find(f"material:{unreadable}") == []
    for kid in set(entries) - {unreadable}:
        [item] = platform.find(f"material:{kid}")
        opening = " ".join(UPLOADS[kid][1].split())[:40]
        assert "\n文件开头：" + opening in item["detail"]
    calls = Counter(kid for _, kid, _ in reader.calls)
    assert all(count <= 1 for count in calls.values()), calls


def test_a_failed_read_never_discards_an_answer() -> None:
    current, entries = waiting()
    kid = sorted(entries)[0]
    platform = FakePlatform()
    first, _ = run(current, platform)
    item = only_item(platform, kid)
    option = platform.view(item)["options"][0]["key"]
    platform.answer(item, option)
    second, _ = run(first.registry, platform, reader=pages(kid))
    assert platform.closed == []
    assert second.report.skipped == {"SOURCE_UNAVAILABLE": 1}
    third, _ = run(second.registry, platform)
    assert third.report.applied == [kid]
