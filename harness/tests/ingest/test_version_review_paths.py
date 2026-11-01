"""PV-3 review R4, R6, R7 (written by Claude): Codex's counterexamples on PR #506, synthetic.

R4: every answer to a question that carries version evidence is checked again before it is applied
(replace and supplement too, and a second question after a person chose the version), and the final
decision keeps the evidence and who decided. R6: the last material of an entry cannot be detached,
since no source withdrawal path exists for an entry left without sources. R7: a v1 registry refuses
DETACHED, on load and on record.
"""

import pytest
from pydantic import ValidationError

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredMaterial,
    RegisteredProduct,
    attribute,
)
from insurance_harness.identity.confirmation import ConfirmationError, choices, conclude
from insurance_harness.ingest.detach import DetachError, detach
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    DecisionEntry,
    ProductRegistry,
    RegistryError,
    record,
)
from tests.identity.test_training_versions import YXJY_PAR, YXJY_PLAIN, ZYBH_2024, ZYBH_2026, deck
from tests.ingest.test_shared_code_question import asked as shared_question
from tests.ingest.test_version_questions import attached
from tests.ingest.upload_helpers import entry, registry

HELD = RegisteredMaterial(knowledge_id="k-old", sha256="e" * 64, role="sales_training")
DECK = deck("智盈倍护产品培训_20240527.pptx", "智盈倍护产品培训")


def key(
    question: Attribution, registry: list[RegisteredProduct], kind: str, value: str | None = None
) -> str:
    return next(c.key for c in choices(question, registry) if c.kind == kind and c.value == value)


# R4 ------------------------------------------------------------------------------------------


def test_a_same_role_answer_is_stale_once_the_version_evidence_changes() -> None:
    before = [ZYBH_2024.model_copy(update={"materials": (HELD,)}), ZYBH_2026]
    question = attribute(DECK, before)
    assert (question.reason, question.version_basis is not None) == ("same_role_differs", True)
    assert ZYBH_2024.version is not None
    ended = ZYBH_2024.version.model_copy(update={"sale_end": "2024-05-01"})
    after = [before[0].model_copy(update={"version": ended}), ZYBH_2026]
    with pytest.raises(ConfirmationError) as stale:
        conclude(question, key(question, before, "supplement"), DECK, after)
    assert stale.value.code == "CHOICE_STALE"


def test_same_role_answers_keep_the_version_evidence_and_who_decided() -> None:
    registry_ = [ZYBH_2024.model_copy(update={"materials": (HELD,)}), ZYBH_2026]
    question = attribute(DECK, registry_)
    for kind in ("supplement", "replace", "ignore"):
        result = conclude(question, key(question, registry_, kind), DECK, registry_)
        assert result.version_basis == question.version_basis, kind


def test_a_second_question_after_a_persons_version_choice_is_checked_and_kept() -> None:
    held = YXJY_PAR.model_copy(update={"materials": (HELD,)})
    registry_ = [YXJY_PLAIN, held]
    upload = deck("御享金越销售方法.pptx", "御享金越销售方法\n2023年11月")
    first = attribute(upload, registry_)
    second = conclude(first, key(first, registry_, "product", "1734"), upload, registry_)
    assert (second.reason, second.product_id) == ("same_role_differs", "1734")
    assert second.version_basis is not None and second.version_basis.version_decided_by == "person"
    final = conclude(second, key(second, registry_, "supplement"), upload, registry_)
    assert final.outcome == "SUPPLEMENT"
    assert final.version_basis is not None and final.version_basis.version_decided_by == "person"
    third = YXJY_PAR.model_copy(update={"product_id": "1736", "version_key": "1736-1"})
    with pytest.raises(ConfirmationError):
        conclude(second, key(second, registry_, "supplement"), upload, [*registry_, third])


def test_ignoring_a_shared_code_keeps_the_shared_versions() -> None:
    pending = shared_question()
    result = conclude(pending.attribution, "ignore", deck("x.pdf", "x"), [])
    assert result.shared_versions == pending.attribution.shared_versions


# R6 ------------------------------------------------------------------------------------------


def test_the_last_material_of_an_entry_cannot_be_detached() -> None:
    lonely = attached()
    product = lonely.products["p00"]
    product.materials = [m for m in product.materials if m.knowledge_id == "k-deck"]
    with pytest.raises(DetachError) as refused:
        detach(lonely, "k-deck", "wrong_version")
    assert refused.value.code == "LAST_MATERIAL"


# R7 ------------------------------------------------------------------------------------------


DETACHED = Attribution(
    outcome="DETACHED",
    reason="wrong_version",
    product_id="1828",
    role="terms",
    policy_ref="attribution-policy@2026-11-01.4",
)


def test_a_v1_registry_refuses_a_detached_decision() -> None:
    legacy = registry(p1828=entry("1828", "terms", "brochure"))
    material = legacy.products["1828"].materials[0]
    document = legacy.model_dump()
    document["decisions"] = [
        DecisionEntry(
            knowledge_id=material.knowledge_id,
            parse_attempt=1,
            sha256=material.sha256,
            attribution=DETACHED,
        ).model_dump()
    ]
    with pytest.raises(ValidationError):
        ProductRegistry.model_validate(document)


def test_recording_detached_into_a_v1_registry_is_refused() -> None:
    legacy = registry(p1828=entry("1828", "terms", "brochure"))
    material = legacy.products["1828"].materials[0]
    source = RawSource(
        knowledge_id=material.knowledge_id,
        parse_attempt=1,
        file_name=material.file_name,
        sha256=material.sha256,
    )
    with pytest.raises(RegistryError) as refused:
        record(legacy, source, DETACHED)
    assert refused.value.code == "RECORD_INVALID"
    assert legacy.decisions == []


# Review round 2: follow-up questions after a version decision keep the evidence -----------------


NO_ROLE = deck("智盈倍护_20240527.pptx", "智盈倍护\n2024年5月")
UNDATED_ROLE = deck("御享金越.pptx", "御享金越\n2023年11月")


def test_a_machine_version_then_role_then_same_role_supplement_applies() -> None:
    registry_ = [ZYBH_2024.model_copy(update={"materials": (HELD,)}), ZYBH_2026]
    first = attribute(NO_ROLE, registry_)
    assert first.reason == "version_role_unresolved"
    second = conclude(first, key(first, registry_, "role", "sales_training"), NO_ROLE, registry_)
    assert (second.reason, second.product_id) == ("same_role_differs", "2635")
    assert second.version_basis is not None
    assert (second.version_basis.version_decided_by, second.version_basis.role_decided_by) == (
        "machine",
        "person",
    )
    final = conclude(second, key(second, registry_, "supplement"), NO_ROLE, registry_)
    assert final.outcome == "SUPPLEMENT"
    assert final.version_basis == second.version_basis


def test_a_person_version_then_role_keeps_the_evidence_and_both_deciders() -> None:
    registry_ = [YXJY_PLAIN, YXJY_PAR]
    first = attribute(UNDATED_ROLE, registry_)
    assert first.reason == "version_candidates"
    second = conclude(first, key(first, registry_, "product", "1734"), UNDATED_ROLE, registry_)
    assert (second.reason, second.role) == ("role_unresolved", None)
    assert [c.value for c in choices(second, registry_)] == ["sales_training", None]
    final = conclude(
        second, key(second, registry_, "role", "sales_training"), UNDATED_ROLE, registry_
    )
    assert (final.outcome, final.product_id, final.role) == ("SUPPLEMENT", "1734", "sales_training")
    assert final.version_basis is not None
    assert (final.version_basis.version_decided_by, final.version_basis.role_decided_by) == (
        "person",
        "person",
    )


def test_a_person_version_then_role_then_same_role_supplement_applies() -> None:
    registry_ = [YXJY_PLAIN, YXJY_PAR.model_copy(update={"materials": (HELD,)})]
    first = attribute(UNDATED_ROLE, registry_)
    second = conclude(first, key(first, registry_, "product", "1734"), UNDATED_ROLE, registry_)
    third = conclude(
        second, key(second, registry_, "role", "sales_training"), UNDATED_ROLE, registry_
    )
    assert third.reason == "same_role_differs" and third.version_basis is not None
    final = conclude(third, key(third, registry_, "supplement"), UNDATED_ROLE, registry_)
    assert final.outcome == "SUPPLEMENT" and final.version_basis == third.version_basis


def test_a_follow_up_is_still_stale_when_the_evidence_really_changes() -> None:
    registry_ = [ZYBH_2024.model_copy(update={"materials": (HELD,)}), ZYBH_2026]
    first = attribute(NO_ROLE, registry_)
    second = conclude(first, key(first, registry_, "role", "sales_training"), NO_ROLE, registry_)
    twin = ZYBH_2024.model_copy(update={"product_id": "2636", "version_key": "2636-1"})
    with pytest.raises(ConfirmationError) as stale:
        conclude(second, key(second, registry_, "supplement"), NO_ROLE, [*registry_, twin])
    assert stale.value.code == "CHOICE_STALE"
