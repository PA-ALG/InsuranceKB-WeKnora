"""S5b-3d-1 acceptance (protected, written by Claude): a question shows how the file begins.

Spec docs/design/slices/S5b-3d-1-待确认材料显示文件开头.md §2, §4. The user could not judge an
item from its file name alone (2026-10-26); the detail now ends with the cleaned opening of the
material's first pages, or says it cannot be read, and the question is asked either way.
"""

from collections import Counter

from insurance_harness.ingest.confirmation_questions import load_wording, question_of
from insurance_harness.ingest.registry import PendingEntry, ProductRegistry
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import UPLOADS, asked, pages, products, run

UNREADABLE = "暂时读不到这份文件的内容。"


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
    plain = question_of(entry, current)
    question = question_of(entry, current, head=head)
    reason = plain.detail.rsplit("\n", 1)[0]
    assert question.detail == (
        reason + "\n文件开头：《平安示例年金保险》转换标准表 (每万元保单账户价值转换的领取金额) "
        "女性 单位:人民币元 领取方式"
    )
    assert (question.subject, question.title) == (plain.subject, plain.title)


def test_a_long_opening_is_cut_with_an_ellipsis_within_the_limit() -> None:
    current, entries = waiting()
    for entry in entries.values():
        question = question_of(entry, current, head="长" * 1000)
        assert question.detail.rsplit("\n", 1)[1] == "文件开头：" + "长" * 300 + "…"
        assert len(question.detail) <= 2000


def test_without_an_opening_the_detail_says_it_cannot_be_read() -> None:
    current, entries = waiting()
    for entry in entries.values():
        assert question_of(entry, current).detail.endswith("\n" + UNREADABLE)


def test_the_wording_is_versioned() -> None:
    wording = load_wording()
    assert wording.version == "2026-10-26.1"
    assert wording.excerpt_chars == 300


def test_each_pushed_question_shows_its_file_and_an_unreadable_one_is_asked_too() -> None:
    current, entries = waiting()
    unreadable = sorted(entries)[0]
    reader = pages(unreadable)
    platform = FakePlatform()
    result, _ = run(current, platform, reader=reader)
    assert sorted(result.report.pushed) == sorted(entries)
    for kid in entries:
        [item] = platform.find(f"material:{kid}")
        detail = item["detail"]
        if kid == unreadable:
            assert detail.endswith("\n" + UNREADABLE)
        else:
            opening = " ".join(UPLOADS[kid][1].split())[:40]
            assert "\n文件开头：" + opening in detail
    calls = Counter(kid for _, kid, _ in reader.calls)
    assert all(count <= 1 for count in calls.values()), calls
