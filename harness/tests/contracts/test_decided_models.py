"""Frozen S3a §8 types, defaults, aliases and nested boundary validation."""

import hashlib
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from insurance_harness.contracts import (
    Block,
    BundleMember,
    CandidateBundle,
    CompileResult,
    CompileTask,
    Entity,
    Evidence,
    ExpertRevision,
    GapTask,
    Locator,
    PageText,
    QAItem,
    Relation,
    Review,
    ReviewItem,
    ReviewPlan,
    SchemaSnapshot,
)
from insurance_harness.contracts.enums import (
    CompileStatus,
    CompileTaskKind,
    GapTrigger,
    LocatorKind,
    Origin,
    ReviewKind,
    ReviewMode,
    TextOrigin,
)
from tests.contracts.test_knowledge_invariants import evidence, supported_claim

SHA = "b" * 64


@pytest.mark.parametrize("value", [0, 2, 1.5, False, True, "90 days", ["option-a", "option-b"]])
def test_typed_values_keep_their_json_types(value: Any) -> None:
    actual = supported_claim(value=value).value
    assert actual == value
    assert type(actual) is type(value)


def test_claim_defaults_and_closed_metadata() -> None:
    claim = supported_claim()
    assert claim.applicability.model_dump() == {
        "region": [], "channel": [], "population": [], "scenario": [],
    }
    assert claim.provenance.compiler == ""
    assert claim.maintenance.revision_no == 0
    assert claim.maintenance.changed_by == "compile"
    assert claim.review.mode == "machine"
    assert claim.review.score is None
    assert claim.effective_from is None and claim.effective_to is None
    for name in ("applicability", "provenance", "maintenance", "review"):
        with pytest.raises(ValidationError):
            supported_claim(**{name: {"unexpected": "value"}})


@pytest.mark.parametrize("reason", [
    "NOT_IN_MATERIAL", "MATERIAL_AMBIGUOUS", "LOCATOR_UNSUPPORTED",
    "EXTRACTION_FAILED", "OUT_OF_SCOPE",
])
def test_reason_is_required_only_for_unknown(reason: str) -> None:
    assert supported_claim(
        state="unknown", value=None, evidence=[], unknown_reason=reason,
    ).unknown_reason == reason
    with pytest.raises(ValidationError):
        supported_claim(unknown_reason=reason)
    with pytest.raises(ValidationError):
        supported_claim(state="absent_explicitly", value=None, unknown_reason=reason)


def test_quote_hash_uses_normalized_text_and_preserves_explicit_hash() -> None:
    original = evidence(quote="Ａ B\nＣ")
    assert original.quote == "Ａ B\nＣ"
    assert original.quote_sha256 == hashlib.sha256(b"ABC").hexdigest()
    explicit = Evidence(**{**original.model_dump(), "quote_sha256": SHA})
    assert explicit.quote_sha256 == SHA
    with pytest.raises(ValidationError):
        Evidence(**{**original.model_dump(), "file_sha256": "bad-hash"})


def test_bundle_preserves_first_publication_and_catalog_member_kinds() -> None:
    member = BundleMember(
        kind="catalog_extension", logical_slug="entity/example", payload={"name": "Example"},
        member_digest=SHA, access_scope="internal",
    )
    bundle = CandidateBundle(
        contract_version="1", origin="compile", compiler_identity="compiler/example",
        members=[member], review_plan=[ReviewPlan(mode=ReviewMode.HUMAN, sample_size=0)],
    )
    assert bundle.base_release_id is None and bundle.base_epoch is None
    assert bundle.review_plan[0].mode == "human"
    patches: list[dict[str, Any]] = [
        {"contract_version": "2"}, {"base_release_id": ""},
        {"base_epoch": -1}, {"review_plan": {}},
    ]
    for patch in patches:
        with pytest.raises(ValidationError):
            CandidateBundle(**{**bundle.model_dump(), **patch})
    with pytest.raises(ValidationError):
        BundleMember(**{**member.model_dump(), "kind": "Invalid-kind"})


def model_examples() -> list[BaseModel]:
    locator = Locator(kind="DOCX_BLOCK", block_index=0)
    return [
        Entity(entity_id="entity-a", entity_type="catalog_type", names=["Example"],
               owner_module="module-a"),
        Relation.model_validate({"relation_id": "r", "predicate": "catalog_predicate",
                                 "from": "entity-a", "to": "entity-b"}),
        QAItem(qa_id="qa", question="Question?", intent="intent", answer="Answer"),
        ExpertRevision(revision_record_id="r", actor="a", role="editor", recorded_at="time",
                       target="entity-a"),
        SchemaSnapshot(schema_pack_id="pack", schema_pack_sha256=SHA,
                       presentation_profile_ref="profile", catalog_version="1"),
        PageText(source_revision_id="r", parse_artifact_digest=SHA, document_role="document",
                 page_number=1, text="text", text_origin=TextOrigin.NATIVE, blocks=[
                     Block(block_id="b", start=0, end=4, locator=locator),
                 ]),
        CompileTask(task_key="task", entity_version="v", config_ref="config",
                    kind=CompileTaskKind.SCHEMA_FIELDS),
        CompileResult(task_key="task", status=CompileStatus.SUCCEEDED, claims=[supported_claim()]),
        GapTask(gap_id="gap", target="entity-a", trigger=GapTrigger.SCHEMA),
        ReviewItem(item_id="item", target="entity-a", kind=ReviewKind.CONFLICT),
        ReviewPlan(mode=ReviewMode.MACHINE),
    ]


def test_all_models_reject_extra_fields_and_reassignment() -> None:
    for model in model_examples():
        assert type(model).model_validate_json(model.model_dump_json()) == model
        with pytest.raises(ValidationError):
            type(model).model_validate({**model.model_dump(by_alias=True), "surprise": True})
        field = next(iter(type(model).model_fields))
        with pytest.raises(ValidationError):
            setattr(model, field, getattr(model, field))


def test_relation_uses_blueprint_wire_names() -> None:
    relation = Relation.model_validate(
        {"relation_id": "r", "predicate": "links", "from": "a", "to": "b"}
    )
    assert relation.model_dump()["from"] == "a"
    assert "from_" not in relation.model_dump()


def test_compile_defaults_and_block_offsets() -> None:
    task = CompileTask(task_key="k", entity_version="v", config_ref="c", kind=CompileTaskKind.QA)
    assert task.material_set == [] and task.targets == [] and task.budget == 0
    assert GapTask(gap_id="g", target="t", trigger=GapTrigger.LINT).status == "OPEN"
    assert ReviewItem(item_id="i", target="t", kind=ReviewKind.SAMPLE).status == "OPEN"
    with pytest.raises(ValidationError):
        CompileTask(**{**task.model_dump(), "budget": -1})
    page = next(model for model in model_examples() if isinstance(model, PageText))
    with pytest.raises(ValidationError):
        PageText.model_validate({**page.model_dump(), "blocks": [
            {**page.blocks[0].model_dump(), "start": 5, "end": 4},
        ]})


@pytest.mark.parametrize("model,fields", [
    (CompileResult, {"task_key": "t", "status": "UNKNOWN"}),
    (GapTask, {"gap_id": "g", "target": "t", "trigger": "schema", "status": "UNKNOWN"}),
    (ReviewItem, {"item_id": "i", "target": "t", "kind": "lint", "status": "UNKNOWN"}),
    (Entity, {"entity_id": "e", "entity_type": "t", "names": [], "owner_module": "m"}),
])
def test_model_boundaries_reject_invalid_vocabulary(
    model: type[BaseModel], fields: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(fields)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_review_score_cannot_silently_serialize_as_null(score: float) -> None:
    with pytest.raises(ValidationError):
        Review(score=score)


def test_wire_constructors_preserve_call_level_strict_validation() -> None:
    with pytest.raises(ValidationError):
        Locator.model_validate(
            {"kind": LocatorKind.PPTX_SHAPE, "slide": 1, "shape_id": b"title"}, strict=True,
        )
    with pytest.raises(ValidationError):
        CandidateBundle.model_validate(
            {"contract_version": "1", "origin": Origin.COMPILE,
             "compiler_identity": b"compiler"}, strict=True,
        )
