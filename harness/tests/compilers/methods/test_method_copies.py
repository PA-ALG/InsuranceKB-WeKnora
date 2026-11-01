"""SK-2b Spec §2, §3, §9.1 (RED, written by Claude): copying method materials into discovery."""

from pathlib import Path

import pytest

from insurance_harness.compilers.methods.copies import (
    CopiesError,
    CopyBook,
    MethodCopy,
    empty_book,
    load_copies,
    save_copies,
    sync_copies,
)
from insurance_harness.compilers.methods.platform import PlatformCallError
from tests.compilers.methods.discovery_helpers import DISCOVERY_KB, DiscoveryWorld, FakePlatform
from tests.compilers.methods.helpers import DECK_A
from tests.ingest.upload_helpers import RAW_KB, SPACE


def book(*copies: MethodCopy) -> CopyBook:
    return empty_book(SPACE, DISCOVERY_KB).model_copy(update={"copies": copies})


def mapped(world: DiscoveryWorld, knowledge_id: str, copy_id: str) -> MethodCopy:
    raw = world.raws[knowledge_id]
    return MethodCopy(
        copy_knowledge_id=copy_id,
        knowledge_id=raw.knowledge_id,
        parse_attempt=raw.parse_attempt,
        sha256=raw.sha256,
    )


def test_a_plan_copies_every_active_record_and_writes_nothing() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    result = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=False)
    assert result.report["counts"] == {"to_copy": 2}
    assert platform.writes() == [] and not [c for c in platform.calls if c[0] == "download"]
    assert result.book.copies == ()


def test_a_live_run_copies_the_bytes_and_records_the_mapping() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    result = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    assert result.report["counts"] == {"copied": 2}
    assert [c for c in platform.calls if c[0] == "upload"] == [
        ("upload", "需求销售方法.pptx"),
        ("upload", "转保沟通.pptx"),
    ]
    by_original = {copy.knowledge_id: copy for copy in result.book.copies}
    for knowledge_id in ("k-deck-a", "k-deck-c"):
        copy = by_original[knowledge_id]
        assert copy.sha256 == world.raws[knowledge_id].sha256
        assert platform.items[copy.copy_knowledge_id][1] == copy.sha256  # same bytes


def test_other_current_bytes_are_never_copied() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    platform.files["k-deck-a"] = b"a newer file under the same knowledge id"
    result = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    assert result.report["counts"] == {"SOURCE_CHANGED": 1, "copied": 1}
    assert [copy.knowledge_id for copy in result.book.copies] == ["k-deck-c"]


@pytest.mark.parametrize("code", ["SOURCE_TOO_LARGE", "SOURCE_UNAVAILABLE"])
def test_an_unreadable_source_is_skipped_with_its_code(code: str) -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    platform.download_error["k-deck-a"] = code
    result = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    assert result.report["counts"] == {code: 1, "copied": 1}


def test_a_listed_copy_with_the_same_bytes_is_adopted_without_an_upload() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    platform.items["copy-old"] = ("x.pptx", world.raws["k-deck-a"].sha256, True)
    result = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    assert result.report["counts"] == {"adopted": 1, "copied": 1}
    assert mapped(world, "k-deck-a", "copy-old") in result.book.copies
    assert ("upload", "需求销售方法.pptx") not in platform.calls


def test_a_duplicate_answer_from_the_platform_is_adopted() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    platform.duplicate_of[world.raws["k-deck-a"].sha256] = "copy-parsing"
    result = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    assert result.report["counts"] == {"adopted": 1, "copied": 1}
    assert mapped(world, "k-deck-a", "copy-parsing") in result.book.copies


def test_records_with_the_same_bytes_share_no_copy() -> None:
    world = DiscoveryWorld()
    world.add_file("k-deck-b", "需求销售方法副本.pptx", DECK_A, data=world.files["k-deck-a"])
    platform = FakePlatform(world)
    result = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    assert result.report["counts"] == {"SAME_BYTES": 1, "copied": 2}
    assert sorted(c.knowledge_id for c in result.book.copies) == ["k-deck-a", "k-deck-c"]


def test_a_mapped_copy_still_listed_is_kept() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    first = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    again = sync_copies(world.registry, first.book, platform, live=True)
    assert again.report["counts"] == {"kept": 2}
    assert again.book == first.book
    assert len([c for c in platform.calls if c[0] == "upload"]) == 2


def test_the_copy_of_an_invalidated_record_is_deleted() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    first = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    stale = next(c for c in first.book.copies if c.knowledge_id == "k-deck-a")
    world.set_use("k-deck-a", state="invalidated", invalidated_reason="detached")
    plan = sync_copies(world.registry, first.book, platform, live=False)
    assert plan.report["counts"] == {"kept": 1, "stale": 1} and plan.book == first.book
    result = sync_copies(world.registry, first.book, platform, live=True)
    assert ("delete", stale.copy_knowledge_id) in platform.calls
    assert [c.knowledge_id for c in result.book.copies] == ["k-deck-c"]


def test_a_copy_gone_from_the_listing_is_copied_again_and_never_deleted() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    gone = mapped(world, "k-deck-a", "copy-gone")
    world.set_use("k-deck-c", state="invalidated", invalidated_reason="withdrawn")
    stale_gone = mapped(world, "k-deck-c", "copy-other-gone")
    result = sync_copies(world.registry, book(gone, stale_gone), platform, live=True)
    assert result.report["counts"] == {"copied": 1, "gone": 2}
    assert not [call for call in platform.calls if call[0] == "delete"]
    (copy,) = result.book.copies
    assert copy.knowledge_id == "k-deck-a" and copy.copy_knowledge_id != "copy-gone"


def test_a_failed_run_is_reconciled_without_uploading_twice() -> None:
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    platform.fail_upload.add("转保沟通.pptx")
    with pytest.raises(PlatformCallError):
        sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    platform.fail_upload.clear()
    result = sync_copies(world.registry, empty_book(SPACE, DISCOVERY_KB), platform, live=True)
    assert result.report["counts"] == {"adopted": 1, "copied": 1}
    uploads = [call for call in platform.calls if call == ("upload", "需求销售方法.pptx")]
    assert len(uploads) == 1


def test_the_raw_knowledge_base_is_never_the_discovery_one() -> None:
    world = DiscoveryWorld()
    with pytest.raises(CopiesError) as raised:
        sync_copies(world.registry, empty_book(SPACE, RAW_KB), FakePlatform(world), live=False)
    assert raised.value.code == "DISCOVERY_KB_INVALID"


def test_the_copies_file_round_trips_and_is_checked(tmp_path: Path) -> None:
    world = DiscoveryWorld()
    path = tmp_path / "copies.json"
    assert load_copies(path, SPACE, DISCOVERY_KB) == empty_book(SPACE, DISCOVERY_KB)
    saved = book(mapped(world, "k-deck-a", "copy-1"), mapped(world, "k-deck-c", "copy-2"))
    save_copies(saved, path)
    assert load_copies(path, SPACE, DISCOVERY_KB) == saved
    with pytest.raises(CopiesError) as raised:
        load_copies(path, SPACE, "kb-other")
    assert raised.value.code == "COPIES_MISMATCH"
    for text in ("not json", path.read_text(encoding="utf-8").replace("copy-2", "copy-1")):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(CopiesError) as raised:
            load_copies(path, SPACE, DISCOVERY_KB)
        assert raised.value.code == "COPIES_INVALID"
