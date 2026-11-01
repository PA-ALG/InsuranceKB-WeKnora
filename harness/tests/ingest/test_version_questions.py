"""PV-3 acceptance (written by Claude): version questions show their evidence; detach is controlled.

Spec docs/design/slices/PV-3-培训材料按版本归属与人工闭环.md §2.8, §3, §4. A question lists the date
signals and every candidate with its verdict (at most ten, with the total), offers only what may be
chosen, and is a new question when the evidence changes. `uploads detach` takes a material off its
entry in a v2 registry, records why, and the material is not judged again.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_harness.identity.attribution import Attribution, Upload, attribute
from insurance_harness.ingest.confirmation_questions import question_of
from insurance_harness.ingest.detach import DetachError, detach
from insurance_harness.ingest.product_versions import MetadataBasis, ProductVersion
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    MaterialEntry,
    PendingEntry,
    ProductEntry,
    ProductRegistry,
    load_registry,
    registry_document,
    save_registry,
)
from insurance_harness.ingest.uploads import attribute_uploads, main
from tests.ingest.upload_helpers import RAW_KB, SPACE, Pages, entry, registry

NURSING = "schemapack_nursing_care_insurance"
NAME = "平安智盈倍护终身护理保险"
DECK = Upload(
    knowledge_id="k-deck",
    file_name="智盈倍护产品培训.pptx",
    sha256="d" * 64,
    head="智盈倍护产品培训\n2024年5月",
)


def basis(commit: str = "c" * 40) -> MetadataBasis:
    return MetadataBasis(
        repository="PA-ALG/pingan-life-product-documents",
        commit=commit,
        catalog_sha256="a" * 64,
        synced_at="2026-11-01T00:00:00Z",
    )


def versioned(
    key: str, start: str, *, materials: list[MaterialEntry] | None = None
) -> ProductEntry:
    return ProductEntry(
        names=[NAME],
        clause_codes=[],
        schema_pack_id=NURSING,
        origin="created",
        materials=materials or [],
        version=ProductVersion(
            version_key=key,
            plan_code=key.split("-")[0],
            version_no=1,
            sale_start=start,
            source_status="on_sale",
            plan_type="普通型",
        ),
    )


def v2(count: int, commit: str = "c" * 40) -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v2",
        space_id=SPACE,
        raw_kb_id=RAW_KB,
        products={f"p{n:02d}": versioned(f"9{n:02d}-1", "2024-01-01") for n in range(count)},
        pending=[],
        decisions=[],
        metadata_basis=basis(commit),
    )


def asked(current: ProductRegistry) -> tuple[PendingEntry, Attribution]:
    attribution = attribute(DECK, current.registered())
    assert attribution.outcome == "NEEDS_CONFIRM", attribution
    pending = PendingEntry(
        knowledge_id=DECK.knowledge_id,
        parse_attempt=1,
        sha256=DECK.sha256,
        file_name=DECK.file_name,
        attribution=attribution,
    )
    return pending, attribution


def test_a_version_question_lists_signals_verdicts_and_only_consistent_choices() -> None:
    current = v2(2)
    pending, attribution = asked(current)
    assert attribution.reason == "version_candidates"
    question = question_of(pending, current, head=DECK.head)
    assert "2024-05" in question.detail
    assert question.detail.count("一致") >= 2
    assert "900-1" in question.detail and "901-1" in question.detail
    assert len(question.options) == 3  # the two consistent versions and ignoring


def test_more_than_ten_candidates_are_listed_with_the_total() -> None:
    current = v2(12)
    pending, _ = asked(current)
    question = question_of(pending, current, head=DECK.head)
    assert "共 12 个" in question.detail
    assert len(question.options) == 13  # every consistent candidate stays a choice


def test_changed_evidence_with_the_same_candidates_is_a_new_question() -> None:
    first, _ = asked(v2(2))
    second, _ = asked(v2(2, commit="d" * 40))
    assert first.attribution.candidates == second.attribution.candidates
    revisions = {
        question_of(first, v2(2), head=DECK.head).revision,
        question_of(second, v2(2, commit="d" * 40), head=DECK.head).revision,
    }
    assert len(revisions) == 2


def test_a_v1_registry_refuses_version_evidence_rather_than_dropping_it() -> None:
    pending, attribution = asked(v2(2))
    assert attribution.version_basis is not None
    legacy = registry(p1828=entry("1828", "terms"))
    legacy.pending = [pending]
    with pytest.raises(ValidationError):  # as PV-1 review R5 does for version keys
        ProductRegistry.model_validate(legacy.model_dump())
    legacy.pending = []
    written = json.loads(registry_document(legacy))
    assert "version_basis" not in json.dumps(written)


# --- uploads detach ----------------------------------------------------------------------------


def attached() -> ProductRegistry:
    material = MaterialEntry(
        knowledge_id="k-deck",
        parse_attempt=1,
        sha256="d" * 64,
        role="sales_training",
        file_name="智盈倍护产品培训.pptx",
    )
    current = v2(1)
    current.products["p00"] = versioned("900-1", "2024-01-01", materials=[material])
    return current


def test_detach_moves_the_material_off_its_entry_and_records_why() -> None:
    result = detach(attached(), "k-deck", "wrong_version")
    product = result.products["p00"]
    assert product.materials == [] and [m.knowledge_id for m in product.retired] == ["k-deck"]
    decision = result.decisions[-1]
    assert (decision.knowledge_id, decision.attribution.outcome) == ("k-deck", "DETACHED")
    assert (decision.attribution.reason, decision.attribution.product_id) == (
        "wrong_version",
        "p00",
    )
    assert decision.confirmation is None


@pytest.mark.parametrize(
    ("current", "knowledge", "reason", "code"),
    [
        (registry(p1828=entry("1828", "terms")), "k-1828-terms", "wrong_version", "REGISTRY_V1"),
        (attached(), "k-other", "wrong_version", "MATERIAL_NOT_ATTACHED"),
        (attached(), "k-deck", "because I said so", "REASON_INVALID"),
    ],
)
def test_detach_refuses(current: ProductRegistry, knowledge: str, reason: str, code: str) -> None:
    with pytest.raises(DetachError) as refused:
        detach(current, knowledge, reason)
    assert refused.value.code == code


def test_a_detached_material_is_not_judged_again() -> None:
    source = RawSource(
        knowledge_id="k-deck", parse_attempt=1, file_name="智盈倍护产品培训.pptx", sha256="d" * 64
    )
    result = attribute_uploads(
        detach(attached(), "k-deck", "wrong_version"),
        [source],
        Pages(heads={"k-deck": DECK.head}, sources=[source]),
    )
    assert result.report.counts == {} and result.registry.products["p00"].materials == []


def test_the_detach_command_holds_the_lock_and_honours_dry_run(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    save_registry(attached(), path)
    before = path.read_bytes()
    command = [
        "detach",
        "--registry",
        str(path),
        "--knowledge-id",
        "k-deck",
        "--reason",
        "wrong_version",
    ]
    assert main([*command, "--dry-run"]) == 0
    assert path.read_bytes() == before
    assert main(command) == 0
    assert load_registry(path).decisions[-1].attribution.outcome == "DETACHED"
    assert main(command) == 1  # no longer attached
