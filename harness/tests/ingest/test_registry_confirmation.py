"""S5b-3c-1 acceptance (protected, written by Claude): the registry records a person's decision.

Spec docs/design/slices/S5b-3c-1-人工确认的选项与结论.md §2.3, §3 item 8. Questions are raised the
way S5b-2 raises them (attribute_uploads), then settled with the S5b-3c-1 core.
"""

import hashlib
import json
import unicodedata
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.identity.attribution import Attribution, Upload
from insurance_harness.identity.confirmation import conclude
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    ConfirmationRef,
    ProductRegistry,
    RegistryError,
    load_registry,
    record,
    save_registry,
)
from insurance_harness.ingest.uploads import attribute_uploads
from tests.ingest.upload_helpers import PRODUCTS, Pages, entry, material, raw, registry

OTHER_CODE = "平安人寿〔2026〕终身寿险302号"


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def ref(answer_id: str = "answer-1", key: str = "replace") -> ConfirmationRef:
    return ConfirmationRef(
        item_id="item-1", answer_id=answer_id, option_key=key, answerer="user:alice"
    )


def ask(
    current: ProductRegistry, source: RawSource, head: str
) -> tuple[ProductRegistry, Attribution, Upload]:
    """Raise the question as S5b-2 does; the material then waits in pending."""
    run = attribute_uploads(
        current, [source], Pages(heads={source.knowledge_id: head}, sources=[source])
    )
    [waiting] = run.registry.pending
    assert waiting.attribution.outcome == "NEEDS_CONFIRM"
    item = Upload(
        knowledge_id=source.knowledge_id,
        file_name=source.file_name,
        sha256=source.sha256,
        head=head,
    )
    return run.registry, waiting.attribution, item


def settle(
    current: ProductRegistry, source: RawSource, head: str, key: str, answer_id: str = "answer-1"
) -> tuple[ProductRegistry, Attribution, bool]:
    asked, pending, item = ask(current, source, head)
    conclusion = conclude(pending, key, item, asked.registered())
    changed = record(asked, source, conclusion, ref(answer_id, key))
    return asked, conclusion, changed


def second_brochure() -> tuple[ProductRegistry, RawSource, str]:
    source = raw("1818", "brochure", knowledge_id="k-new", sha256="f" * 64)
    return (
        registry(p1818=entry("1818", "terms", "brochure")),
        source,
        material("1818", "brochure")["head"],
    )


def judged_again(current: ProductRegistry, source: RawSource, head: str) -> dict[str, int]:
    run = attribute_uploads(
        current, [source], Pages(heads={source.knowledge_id: head}, sources=[source])
    )
    assert run.registry == current
    return run.report.counts


# Recording each conclusion ----------------------------------------------------------------------


def test_a_confirmed_replacement_retires_the_old_material_and_keeps_the_codes() -> None:
    current, source, head = second_brochure()
    asked, conclusion, changed = settle(current, source, head, "replace")
    assert changed is True
    product = asked.products["1818"]
    assert [m.knowledge_id for m in product.materials] == ["k-1818-terms", "k-new"]
    assert [m.knowledge_id for m in product.retired] == ["k-1818-brochure"]
    assert product.clause_codes == [PRODUCTS["1818"]["clause_code"]]
    assert asked.pending == []
    assert (asked.decisions[-1].attribution, asked.decisions[-1].confirmation) == (
        conclusion,
        ref(),
    )


def test_a_replacement_citing_another_code_never_adds_it() -> None:
    current, source, head = second_brochure()
    asked, pending, item = ask(current, source, head)
    conclusion = conclude(pending, "replace", item, asked.registered())
    record(asked, source, conclusion.model_copy(update={"clause_code": OTHER_CODE}), ref())
    assert asked.products["1818"].clause_codes == [PRODUCTS["1818"]["clause_code"]]


def test_a_confirmed_supplement_keeps_both_materials() -> None:
    current, source, head = second_brochure()
    asked, _, changed = settle(current, source, head, "supplement")
    assert changed is True
    product = asked.products["1818"]
    assert [m.knowledge_id for m in product.materials] == [
        "k-1818-brochure",
        "k-1818-terms",
        "k-new",
    ]
    assert product.retired == []


def test_an_ignored_material_changes_no_product_and_is_never_judged_again() -> None:
    current, source, head = second_brochure()
    asked, conclusion, changed = settle(current, source, head, "ignore")
    assert changed is False
    assert asked.products == current.products
    assert asked.pending == []
    assert asked.decisions[-1].attribution.outcome == "IGNORED"
    assert asked.decisions[-1].confirmation == ref(key="ignore")
    assert judged_again(asked, source, head) == {}


def two_named() -> tuple[ProductRegistry, RawSource, str]:
    head = (
        fold(PRODUCTS["1828"]["name"])
        + "、"
        + fold(PRODUCTS["1814"]["name"])
        + "产品说明书在本说明书中"
    )
    source = raw("1828", "brochure", knowledge_id="k-two", sha256="c" * 64)
    return (
        registry(p1814=entry("1814", "terms", "brochure"), p1828=entry("1828", "terms")),
        source,
        head,
    )


def product_key(product_id: str) -> str:
    return "product:" + hashlib.sha256(product_id.encode("utf-8")).hexdigest()[:16]


def test_the_next_question_replaces_the_pending_one_and_still_waits_for_a_person() -> None:
    current, source, head = two_named()
    asked, conclusion, changed = settle(current, source, head, product_key("1814"))
    assert changed is False
    [waiting] = asked.pending
    assert (waiting.knowledge_id, waiting.attribution) == ("k-two", conclusion)
    assert (conclusion.reason, conclusion.product_id) == ("same_role_differs", "1814")
    assert asked.decisions[-1].confirmation == ref(key=product_key("1814"))
    assert judged_again(asked, source, head) == {}


def test_a_chosen_pack_creates_the_product() -> None:
    unnamed = "平安安心保障计划"
    head = material("1830", "terms")["head"].replace(fold(PRODUCTS["1830"]["name"]), unnamed, 1)
    source = raw("1830", "terms", knowledge_id="k-unnamed", sha256="d" * 64)
    asked, conclusion, changed = settle(
        registry(p1818=entry("1818", "terms")), source, head, "pack:schemapack_annuity_insurance"
    )
    assert changed is True
    product = asked.products[conclusion.product_id or ""]
    assert (product.names, product.origin, product.schema_pack_id) == (
        [unnamed],
        "created",
        "schemapack_annuity_insurance",
    )
    assert product.clause_codes == [PRODUCTS["1830"]["clause_code"]]
    assert [m.knowledge_id for m in product.materials] == ["k-unnamed"]


# Refusals ---------------------------------------------------------------------------------------


def unchanged_on(code: str, current: ProductRegistry, call: Callable[[], object]) -> None:
    before = current.model_dump()
    with pytest.raises(RegistryError) as failure:
        call()
    assert failure.value.code == code
    assert current.model_dump() == before


def test_a_decision_for_a_material_not_waiting_for_a_person_is_refused() -> None:
    current, source, head = second_brochure()
    asked, pending, item = ask(current, source, head)
    conclusion = conclude(pending, "supplement", item, asked.registered())
    elsewhere = raw("1818", "rate_table")
    unchanged_on(
        "CONFIRMATION_UNEXPECTED", asked, lambda: record(asked, elsewhere, conclusion, ref())
    )
    reparsed = source.model_copy(update={"parse_attempt": 2})
    unchanged_on(
        "CONFIRMATION_UNEXPECTED", asked, lambda: record(asked, reparsed, conclusion, ref())
    )
    changed = source.model_copy(update={"sha256": "e" * 64})
    unchanged_on(
        "CONFIRMATION_UNEXPECTED", asked, lambda: record(asked, changed, conclusion, ref())
    )


def test_a_quarantined_material_takes_no_person_decision() -> None:
    source = raw("1818", "brochure", knowledge_id="k-orphan", sha256="f" * 64)
    head = material("1818", "brochure")["head"]
    run = attribute_uploads(registry(), [source], Pages(heads={"k-orphan": head}, sources=[source]))
    [waiting] = run.registry.pending
    assert waiting.attribution.outcome == "QUARANTINE"
    ignored = waiting.attribution.model_copy(
        update={"outcome": "IGNORED", "reason": "confirmed_ignore"}
    )
    unchanged_on(
        "CONFIRMATION_UNEXPECTED",
        run.registry,
        lambda: record(run.registry, source, ignored, ref(key="ignore")),
    )


def test_an_answer_is_recorded_once() -> None:
    current, source, head = two_named()
    asked, _, _ = settle(current, source, head, product_key("1814"))
    [waiting] = asked.pending
    item = Upload(
        knowledge_id=source.knowledge_id,
        file_name=source.file_name,
        sha256=source.sha256,
        head=head,
    )
    again = conclude(waiting.attribution, "supplement", item, asked.registered())
    unchanged_on("CONFIRMATION_RECORDED", asked, lambda: record(asked, source, again, ref()))


def test_a_person_only_conclusion_needs_its_confirmation() -> None:
    current, source, head = second_brochure()
    asked, pending, item = ask(current, source, head)
    for key in ("replace", "ignore"):
        conclusion = conclude(pending, key, item, asked.registered())
        unchanged_on("CONFIRMATION_REQUIRED", asked, partial(record, asked, source, conclusion))


def test_a_failing_application_leaves_the_registry_as_it_was() -> None:
    """Review R1: errors found while applying leave nothing half-recorded."""
    current, source, head = second_brochure()
    asked, pending, item = ask(current, source, head)
    supplement = conclude(pending, "supplement", item, asked.registered())
    gone = asked.model_copy(deep=True)
    del gone.products["1818"]
    unchanged_on("PRODUCT_UNKNOWN", gone, partial(record, gone, source, supplement, ref()))
    unchanged_on("PRODUCT_UNKNOWN", gone, partial(record, gone, source, supplement))
    blank = source.model_copy(update={"file_name": " "})
    unchanged_on("RECORD_INVALID", asked, partial(record, asked, blank, supplement, ref()))
    roleless = supplement.model_copy(update={"role": None})
    unchanged_on("ATTRIBUTION_INCOMPLETE", asked, partial(record, asked, source, roleless, ref()))


# The registry file ------------------------------------------------------------------------------


def written(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_registry_written_before_confirmations_loads_and_round_trips(tmp_path: Path) -> None:
    current, source, head = second_brochure()
    asked, _, _ = ask(current, source, head)
    document = json.loads(asked.model_dump_json())
    for decision in document["decisions"]:
        decision.pop("confirmation", None)
    loaded = load_registry(written(tmp_path, document))
    assert [d.confirmation for d in loaded.decisions] == [None]
    save_registry(loaded, tmp_path / "again.json")
    assert load_registry(tmp_path / "again.json") == loaded


def test_a_recorded_confirmation_round_trips(tmp_path: Path) -> None:
    current, source, head = second_brochure()
    asked, _, _ = settle(current, source, head, "replace")
    save_registry(asked, tmp_path / "registry.json")
    assert load_registry(tmp_path / "registry.json") == asked


@pytest.mark.parametrize("breakage", ["replace_without", "ignore_without", "answer_twice"])
def test_a_registry_file_breaking_the_confirmation_rules_is_invalid(
    tmp_path: Path, breakage: str
) -> None:
    current, source, head = second_brochure()
    key = "ignore" if breakage == "ignore_without" else "replace"
    asked, _, _ = settle(current, source, head, key)
    document = json.loads(asked.model_dump_json())
    if breakage == "answer_twice":
        document["decisions"].append(document["decisions"][-1])
    else:
        document["decisions"][-1]["confirmation"] = None
    with pytest.raises(RegistryError) as failure:
        load_registry(written(tmp_path, document))
    assert failure.value.code == "REGISTRY_INVALID"


@pytest.mark.parametrize(
    "field, value",
    [
        ("item_id", "item 1"),
        ("answer_id", ""),
        ("option_key", "Replace"),
        ("answerer", "user\talice"),
        ("answerer", ""),
    ],
)
def test_a_confirmation_reference_is_checked(field: str, value: str) -> None:
    fields = ref().model_dump() | {field: value}
    with pytest.raises(ValidationError):
        ConfirmationRef(**fields)
