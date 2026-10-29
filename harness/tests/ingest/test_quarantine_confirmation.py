"""S11a acceptance (protected, written by Claude): quarantined materials reach the page.

Spec docs/design/slices/S11a-隔离材料上页面.md §2, §4. A person may name the registered product a
material without a product anchor belongs to, or settle any quarantined material as not belonging
to a registered product; the S5b-1 rules are never widened by the choice.
"""

import hashlib
import json

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredProduct,
    Upload,
    attribute,
)
from insurance_harness.identity.confirmation import ConfirmationError, choices, conclude
from insurance_harness.ingest.confirmations import load_wording, question_of
from insurance_harness.ingest.registry import ConfirmationRef, ProductRegistry, record
from insurance_harness.ingest.uploads import attribute_uploads
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import (
    UNNAMED,
    UPLOADS,
    Crash,
    asked,
    only_item,
    pages,
    product_key,
    products,
    run,
)
from tests.ingest.upload_helpers import PRODUCTS, Pages, entry, material, raw, registry

ORPHAN = "k-orphan"  # the 1826 brochure, whose product is not registered: no product anchor


def upload(product_id: str, role: str, **override: str) -> Upload:
    m = material(product_id, role)
    fields = {
        "knowledge_id": f"k-{product_id}-{role}",
        "file_name": m["file_name"],
        "sha256": m["sha256"],
        "head": m["head"],
    }
    fields.update(override)
    return Upload(**fields)


def product(
    product_id: str, *, names: tuple[str, ...] = (), codes: tuple[str, ...] = ()
) -> RegisteredProduct:
    facts = PRODUCTS[product_id]
    return RegisteredProduct(
        product_id=product_id,
        names=names or (facts["name"],),
        clause_codes=codes or (facts["clause_code"],),
        schema_pack_id=facts["schema_pack_id"],
    )


def quarantined(item: Upload, registered: list[RegisteredProduct], reason: str) -> Attribution:
    result = attribute(item, registered)
    assert (result.outcome, result.reason) == ("QUARANTINE", reason)
    return result


def ref(key: str, answer: str = "a-1") -> ConfirmationRef:
    return ConfirmationRef(item_id="i-1", answer_id=answer, option_key=key, answerer="user:alice")


# 1. Choices by quarantine reason (Spec §2.1) -----------------------------------------------------


def test_a_material_without_a_product_anchor_offers_every_registered_product_then_ignore() -> None:
    registered = [product("1818"), product("1828"), product("1830")]
    pending = quarantined(upload("1826", "brochure"), registered, "no_product_anchor")
    assert [c.key for c in choices(pending, registered)] == [
        product_key("1818"),
        product_key("1828"),
        product_key("1830"),
        "ignore",
    ]


def test_conflicting_anchors_and_unreadable_openings_can_only_be_ignored() -> None:
    # The code belongs to one registered product while the title names another.
    registered = [
        product("1818", codes=(PRODUCTS["1826"]["clause_code"],)),
        product("1826", codes=("X1",)),
    ]
    conflict = quarantined(upload("1826", "terms"), registered, "anchor_conflict")
    assert [c.key for c in choices(conflict, registered)] == ["ignore"]
    blank = quarantined(upload("1830", "terms", head=" \n "), [product("1818")], "text_unavailable")
    assert [c.key for c in choices(blank, [product("1818")])] == ["ignore"]


def test_more_registered_products_than_options_is_not_confirmable() -> None:
    pending = quarantined(upload("1826", "brochure"), [product("1818")], "no_product_anchor")
    many = [
        RegisteredProduct(
            product_id=f"P{i:03d}",
            names=(f"产品{i}",),
            clause_codes=(f"C{i}",),
            schema_pack_id=PRODUCTS["1818"]["schema_pack_id"],
        )
        for i in range(50)
    ]
    with pytest.raises(ConfirmationError) as failure:
        choices(pending, many)
    assert failure.value.code == "NOT_CONFIRMABLE"


# 2. What a choice concludes (Spec §2.2) ----------------------------------------------------------


def test_naming_the_product_attributes_the_material_and_ignoring_settles_it() -> None:
    # 1826 is registered under another name and code, so its brochure has no anchor of its own.
    registered = [product("1818"), product("1826", names=(UNNAMED,), codes=("X1",))]
    item = upload("1826", "brochure", knowledge_id="k-orphan")
    pending = quarantined(item, registered, "no_product_anchor")
    named = conclude(pending, product_key("1826"), item, registered)
    assert (named.outcome, named.product_id, named.role) == ("SUPPLEMENT", "1826", "brochure")
    assert named.reason == "confirmed_by_person"
    ignored = conclude(pending, "ignore", item, registered)
    assert (ignored.outcome, ignored.reason, ignored.product_id) == (
        "IGNORED",
        "confirmed_ignore",
        None,
    )


def test_a_product_not_offered_for_a_conflict_is_unknown() -> None:
    registered = [
        product("1818", codes=(PRODUCTS["1826"]["clause_code"],)),
        product("1826", codes=("X1",)),
    ]
    item = upload("1826", "terms")
    conflict = quarantined(item, registered, "anchor_conflict")
    with pytest.raises(ConfirmationError) as failure:
        conclude(conflict, product_key("1826"), item, registered)
    assert failure.value.code == "CHOICE_UNKNOWN"


def test_the_registry_records_a_person_decision_on_a_quarantined_material() -> None:
    source = raw("1818", "brochure", knowledge_id=ORPHAN, sha256="f" * 64)
    head = material("1818", "brochure")["head"]
    judged = attribute_uploads(
        registry(), [source], Pages(heads={ORPHAN: head}, sources=[source])
    ).registry
    [waiting] = judged.pending
    assert waiting.attribution.outcome == "QUARANTINE"
    ignored = waiting.attribution.model_copy(
        update={"outcome": "IGNORED", "reason": "confirmed_ignore"}
    )
    record(judged, source, ignored, ref("ignore"))
    assert judged.pending == []
    assert (judged.decisions[-1].attribution.outcome, judged.decisions[-1].confirmation) == (
        "IGNORED",
        ref("ignore"),
    )


# 3. Pushing, answering and re-judging (Spec §2.3, §4) --------------------------------------------


def test_a_quarantined_material_is_pushed_with_its_reason_opening_and_source() -> None:
    current = asked(products(), *UPLOADS)
    [orphan] = [p for p in current.pending if p.knowledge_id == ORPHAN]
    assert (orphan.attribution.outcome, orphan.attribution.reason) == (
        "QUARANTINE",
        "no_product_anchor",
    )
    platform = FakePlatform()
    first, _ = run(current, platform)
    [item] = platform.find(f"material:{ORPHAN}")
    fields = ("subject", "revision", "title", "detail", "options", "source_ref")
    assert {k: item[k] for k in fields} == question_of(
        orphan, current, head=UPLOADS[ORPHAN][1]
    ).model_dump()
    assert [o["key"] for o in item["options"]] == [
        *(product_key(p.product_id) for p in current.registered()),
        "ignore",
    ]
    assert "文件开头：" in item["detail"] and item["source_ref"]
    assert ORPHAN in first.report.pushed
    assert first.report.waiting == 5


def test_rejudging_the_same_quarantine_neither_repushes_nor_closes_it() -> None:
    current = asked(products(), *UPLOADS)
    platform = FakePlatform()
    first, _ = run(current, platform)
    count = len(platform.items)
    rejudged = attribute_uploads(first.registry, [UPLOADS[ORPHAN][0]], pages()).registry
    assert rejudged == first.registry
    run(rejudged, platform)
    assert len(platform.items) == count and platform.closed == []


def test_ignoring_a_quarantined_material_ends_its_judging() -> None:
    current = asked(products(), *UPLOADS)
    platform = FakePlatform()
    first, _ = run(current, platform)
    answer = platform.answer(only_item(platform, ORPHAN), "ignore")
    second, _ = run(first.registry, platform)
    assert ORPHAN not in {p.knowledge_id for p in second.registry.pending}
    [decision] = [d for d in second.registry.decisions if d.knowledge_id == ORPHAN][-1:]
    assert decision.attribution.outcome == "IGNORED"
    assert decision.confirmation is not None and decision.confirmation.answer_id == answer
    again = attribute_uploads(second.registry, [UPLOADS[ORPHAN][0]], pages()).registry
    assert again == second.registry


def test_naming_the_product_registers_the_quarantined_material() -> None:
    renamed = entry("1826", "terms").model_copy(update={"names": [UNNAMED], "clause_codes": ["X1"]})
    current = asked(registry(p1818=entry("1818", "terms", "brochure"), p1826=renamed), ORPHAN)
    [orphan] = current.pending
    assert (orphan.attribution.outcome, orphan.attribution.reason) == (
        "QUARANTINE",
        "no_product_anchor",
    )
    platform = FakePlatform()
    first, _ = run(current, platform)
    platform.answer(only_item(platform, ORPHAN), product_key("1826"))
    second, _ = run(first.registry, platform)
    materials = {m.knowledge_id: m.role for m in second.registry.products["1826"].materials}
    assert materials.get(ORPHAN) == "brochure"
    assert second.registry.pending == []


def test_a_settled_quarantined_material_is_not_rejudged() -> None:
    current = asked(products(), *UPLOADS)
    platform = FakePlatform()
    first, _ = run(current, platform)
    platform.answer(only_item(platform, ORPHAN), "ignore")
    crash = Crash(on_call=2)  # the settlement is saved, the run stops before executing it
    with pytest.raises(OSError):
        run(first.registry, platform, save=crash)
    saved: ProductRegistry = crash.saved[-1]
    [settled] = [p for p in saved.pending if p.knowledge_id == ORPHAN]
    assert settled.settlement is not None
    rejudged = attribute_uploads(saved, [UPLOADS[ORPHAN][0]], pages()).registry
    [kept] = [p for p in rejudged.pending if p.knowledge_id == ORPHAN]
    assert kept.settlement == settled.settlement


# 4. Wording (Spec §2.5) --------------------------------------------------------------------------


def test_an_unreadable_opening_is_asked_without_an_excerpt() -> None:
    source = raw("1830", "terms", knowledge_id="k-blank", sha256="e" * 64)
    judged = attribute_uploads(
        products(), [source], Pages(heads={"k-blank": " \n "}, sources=[source])
    ).registry
    [blank] = judged.pending
    assert blank.attribution.reason == "text_unavailable"
    question = question_of(blank, judged, head=" \n ")
    assert "文件开头" not in question.detail
    assert [o.key for o in question.options] == ["ignore"]


def test_the_existing_wording_and_its_version_are_unchanged() -> None:
    wording = load_wording()
    assert wording.version == "2026-10-26.1"
    existing = {
        k: wording.details[k]
        for k in ("multiple_products", "pack_unresolved", "role_unresolved", "same_role_differs")
    }
    canonical = json.dumps(
        [existing, wording.options, wording.roles, wording.title, wording.excerpt],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == EXISTING_WORDING_SHA256


# main's wording before S11a (commit 5c9e9ae5f): the four existing reasons, options, roles,
# title and excerpt line, canonical JSON.
EXISTING_WORDING_SHA256 = "001a46d6ccfa0cd097b862def27a37f7e82044d987905d02312b6c1e582202c8"
