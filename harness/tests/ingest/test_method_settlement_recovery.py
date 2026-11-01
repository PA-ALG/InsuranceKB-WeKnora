"""SK-1 acceptance (written by Claude): a saved method answer is carried out as it was saved.

Spec docs/design/slices/SK-1-方法用途登记与方法材料归属.md §4.3, §7 item 6 (r4; Codex review R1).
The settlement holds the whole conclusion, including whether the whole material or only its method
use is ignored. While it waits, a run neither judges the material again nor expires its record,
and a detach is refused; so registering a matching version in between cannot turn an "ignore the
material" into "ignore the method use". A conclusion that can no longer be carried out as saved is
kept and reported, never replaced. The commands run for real: `relabel` and `confirm` through
`uploads.main`, the registry saved and loaded on disk, the platform an HTTP fake. Texts are
invented.
"""

from pathlib import Path

import pytest

from insurance_harness.ingest.detach import DetachError, detach
from insurance_harness.ingest.method_confirmations import request_relabel
from insurance_harness.ingest.registry import ProductRegistry, load_registry, save_registry
from insurance_harness.ingest.uploads import attribute_uploads, main
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import Saves
from tests.ingest.method_helpers import DeckPages, deck_pages, nursing_entry, source, v2
from tests.ingest.test_method_confirmations import item_of, sync
from tests.ingest.test_method_uses import BRAND_DECK, BRAND_SLIDES, judged, only_use

SHA = "d" * 64


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://weknora.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")


def method_only() -> ProductRegistry:
    """A brand deck with no version to attach to yet: a METHOD_MATERIAL with a live method use."""
    current = judged(v2(), {"k-deck": (BRAND_DECK, BRAND_SLIDES, SHA)})
    assert [p.attribution.outcome for p in current.pending] == ["METHOD_MATERIAL"]
    return current


def run_over(path: Path, sha256: str = SHA) -> None:
    """One `run` over the listed deck, through the public step, saved as the command saves."""
    pages = DeckPages({"k-deck": deck_pages(BRAND_DECK, sha256, BRAND_SLIDES)})
    after = attribute_uploads(load_registry(path), [source("k-deck", BRAND_DECK, sha256)], pages)
    save_registry(after.registry, path)


def confirm(path: Path, platform: FakePlatform) -> int:
    return main(["confirm", "--registry", str(path)], transport=platform.transport())


def attached(current: ProductRegistry) -> set[str]:
    return {m.knowledge_id for p in current.products.values() for m in p.materials}


def interrupted_ignore(path: Path, platform: FakePlatform, interruption: str) -> None:
    """relabel → asked → a person ignores → the run applying it is interrupted at the close."""
    save_registry(method_only(), path)
    assert main(["relabel", "--registry", str(path), "--knowledge-id", "k-deck"]) == 0
    assert confirm(path, platform) == 0
    platform.answer(item_of(platform), "ignore")
    if interruption == "close_fails":
        platform.fail_closures_after = 0
    else:  # the platform closes the item, but its receipt is lost
        platform.lose_closure_responses = 1
    assert confirm(path, platform) == 1
    platform.fail_closures_after = None


@pytest.mark.parametrize("interruption", ["close_fails", "receipt_lost"])
def test_an_interrupted_ignore_stays_whole_when_a_version_is_registered_meanwhile(
    tmp_path: Path, environment: None, interruption: str
) -> None:
    path, platform = tmp_path / "registry.json", FakePlatform()
    interrupted_ignore(path, platform, interruption)
    saved = only_use(load_registry(path)).settlement
    assert saved is not None and saved.ignore == "material" and saved.categories == ()
    registered = load_registry(path)
    registered.products["2635"] = nursing_entry()  # the deck's version is now registered
    save_registry(registered, path)
    run_over(path)
    between = load_registry(path)
    assert [p.attribution.outcome for p in between.pending] == ["METHOD_MATERIAL"]  # not judged
    assert "k-deck" not in attached(between)
    assert only_use(between).settlement == saved
    assert confirm(path, platform) == 0
    after = load_registry(path)
    [use] = after.method_uses
    assert (use.state, use.settlement) == ("ignored", None)
    decision = after.decisions[-1]
    assert (decision.knowledge_id, decision.attribution.outcome) == ("k-deck", "IGNORED")
    assert decision.confirmation is not None and decision.confirmation.option_key == "ignore"
    run_over(path)
    final = load_registry(path)
    assert "k-deck" not in attached(final) and final.pending == []


def test_a_run_neither_judges_nor_expires_a_material_whose_answer_waits(
    tmp_path: Path, environment: None
) -> None:
    path, platform = tmp_path / "registry.json", FakePlatform()
    interrupted_ignore(path, platform, "close_fails")
    before = load_registry(path)
    run_over(path, sha256="9" * 64)  # a new revision listed meanwhile
    after = load_registry(path)
    assert after.method_uses == before.method_uses  # not expired, settlement kept
    assert after.pending == before.pending


def test_a_detach_waits_for_a_saved_method_answer(tmp_path: Path, environment: None) -> None:
    path, platform = tmp_path / "registry.json", FakePlatform()
    interrupted_ignore(path, platform, "close_fails")
    with pytest.raises(DetachError) as refused:
        detach(load_registry(path), "k-deck", "not_product_material")
    assert refused.value.code == "SETTLEMENT_PENDING"


def test_ignoring_only_the_method_use_is_saved_as_such() -> None:
    current = judged(v2(**{"2635": nursing_entry()}), {"k-deck": (BRAND_DECK, BRAND_SLIDES, SHA)})
    assert "k-deck" in attached(current)
    platform = FakePlatform()
    first = sync(request_relabel(current, "k-deck"), platform)
    platform.answer(item_of(platform), "ignore")
    platform.fail_closures_after = 0
    crashed = Saves()
    with pytest.raises(Exception):  # noqa: B017 — the lost close, as an interrupted run sees it
        sync(first.registry, platform, crashed)
    saved = only_use(crashed[-1]).settlement
    assert saved is not None and saved.ignore == "method_use"


def test_a_saved_conclusion_that_cannot_be_carried_out_is_kept_and_reported() -> None:
    platform = FakePlatform()
    first = sync(request_relabel(method_only(), "k-deck"), platform)
    platform.answer(item_of(platform), "ignore")
    platform.fail_closures_after = 0
    crashed = Saves()
    with pytest.raises(Exception):  # noqa: B017
        sync(first.registry, platform, crashed)
    changed = crashed[-1].model_copy(deep=True)
    changed.pending = []  # the material left `pending` some other way
    platform.fail_closures_after = None
    result = sync(changed, platform)
    use = only_use(result.registry)
    assert use.settlement is not None and use.state == "active"  # not reinterpreted
    assert all(d.attribution.outcome != "IGNORED" for d in result.registry.decisions)
    assert result.report.skipped.get("SETTLEMENT_NOT_APPLICABLE") == 1
    assert result.report.applied == []
    again = sync(result.registry, platform)  # reported again, still not reinterpreted
    assert again.report.skipped.get("SETTLEMENT_NOT_APPLICABLE") == 1
    assert only_use(again.registry).settlement == use.settlement
