"""Deterministic Golden quality gate for the single 596-1 Schema67 product."""

from __future__ import annotations

import math
import threading
import weakref
from collections import Counter
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    validate_schema67_candidate_v2,
)
from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    MEDICAL_VERSION_ID,
    make_medical_schema_pack_596_1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
    CandidateEvidenceAuthorityError,
    Schema67CitationAuthorityJoinReceiptV1,
    Schema67LiveSourceAuthorityV1,
    validate_schema67_candidate_evidence_authority_596_1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationBBoxV1,
    Schema67GoldenQualityGateReceiptV1,
    schema_wiki_sha256,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlank = Annotated[StrictStr, StringConstraints(min_length=1, pattern=r"^\S(?:[^\r\n]*\S)?$")]
FieldState = Literal["present", "absent_explicitly", "unknown"]
RiskLevel = Literal["critical", "high", "standard"]
EvaluationStatus = Literal["PASS", "FAIL", "FIXTURE_ONLY"]

PROVIDER_ZERO_FIXTURE_CANDIDATE_SHA256: Final[str] = (
    "fa891bb1c6a67590e49ef35a305146da087ea2dbf1c4b34fd30b56be25f76cee"
)
NORMALIZATION_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-normalization-policy.v1",
    {"product_version_id": "596-1", "rule": "schema67-nfc-trim-exact.v1"},
)
RISK_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-risk-policy.v1",
    {"critical_high_exact": True, "product_version_id": "596-1"},
)
METRIC_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-metric-policy.v1",
    {
        "product_version_id": "596-1",
        "state_accuracy_min": "65/67",
        "state_recall_min_ppm": 950_000,
        "present_precision_min_ppm": 950_000,
        "present_recall_min_ppm": 950_000,
        "present_macro_f1_min_ppm": 900_000,
        "wrong_fill_max_ppm": 20_000,
        "hallucinated_fill_max_ppm": 0,
        "evidence_exact_ppm": 1_000_000,
        "bbox_iou_min_ppm": 800_000,
        "bbox_high_risk_iou_min_ppm": 900_000,
    },
)
EVALUATOR_IDENTITY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-evaluator.v1",
    {
        "implementation": "deterministic-596-1-only",
        "metric_policy_sha256": METRIC_POLICY_SHA256,
        "normalization_policy_sha256": NORMALIZATION_POLICY_SHA256,
        "risk_policy_sha256": RISK_POLICY_SHA256,
    },
)

GOLDEN_METRIC_IDS: Final[tuple[str, ...]] = (
    "sgq.state.micro_accuracy.v1",
    "sgq.state.macro_recall.v1",
    "sgq.value.present.micro_precision.v1",
    "sgq.value.present.micro_recall.v1",
    "sgq.value.present.macro_f1.v1",
    "sgq.state.absent_to_unknown.v1",
    "sgq.state.unknown_to_absent.v1",
    "sgq.value.wrong_fill_rate.v1",
    "sgq.value.hallucinated_fill_rate.v1",
    "sgq.evidence.document_revision_page_precision.v1",
    "sgq.evidence.field_support_recall.v1",
    "sgq.evidence.bbox_iou.v1",
    "sgq.evidence.highlight_accuracy.v1",
    "sgq.human.high_risk_pass.v1",
    "sgq.human.conflict_resolution_pass.v1",
)


class Schema67GoldenQualityGateError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class Schema67GoldenEvidenceTargetV1(_FrozenModel):
    contract: Literal["schema67-golden-evidence-target.v1"]
    source_role: Literal["terms", "brochure", "rate_table"]
    live_revision_source_receipt_sha256: Sha256Hex
    revision_source_id: Sha256Hex
    knowledge_id: NonBlank
    evidence_parse_attempt_id: NonBlank
    weknora_parse_attempt: Annotated[StrictInt, Field(gt=0)]
    file_sha256: Sha256Hex
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    weknora_manifest_algorithm: Literal["weknora.chunk_manifest.v1"]
    weknora_manifest_digest: Sha256Hex
    chunk_id: NonBlank
    page_number: Annotated[StrictInt, Field(gt=0)]
    locator_kind: Literal["page", "block", "table", "cell"]
    locator_ref: NonBlank
    quote_sha256: Sha256Hex
    content_sha256: Sha256Hex
    bbox_evaluation: Literal["required", "not_evaluable"]
    coordinate_space: Literal["normalized_0_1e6"] | None
    bbox: CitationBBoxV1 | None
    page_width: Annotated[StrictInt, Field(gt=0)] | None
    page_height: Annotated[StrictInt, Field(gt=0)] | None
    rotation_degrees: Literal[0, 90, 180, 270] | None
    target_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        required = self.bbox_evaluation == "required"
        bbox_fields = (
            self.coordinate_space,
            self.bbox,
            self.page_width,
            self.page_height,
            self.rotation_degrees,
        )
        if required != all(item is not None for item in bbox_fields):
            raise ValueError("bbox evaluation custody mismatch")
        if not required and any(item is not None for item in bbox_fields):
            raise ValueError("not-evaluable bbox must remain absent")
        payload = self.model_dump(mode="python", exclude={"target_sha256"})
        if self.target_sha256 != schema_wiki_sha256(self.contract, payload):
            raise ValueError("golden evidence target hash mismatch")
        return self


class Schema67GoldenFieldV1(_FrozenModel):
    contract: Literal["schema67-golden-field.v1"]
    field_id: NonBlank
    state: FieldState
    value_schema: Literal["scalar", "ordered_list", "unordered_set", "range", "structured"]
    canonical_value: NonBlank | None
    accepted_values: tuple[NonBlank, ...]
    normalization_rule_id: Literal["schema67-nfc-trim-exact.v1"]
    evidence_targets: tuple[Schema67GoldenEvidenceTargetV1, ...]
    risk_level: RiskLevel
    conflict_status: Literal["agreed", "resolved"]
    annotator_decision_sha256s: tuple[Sha256Hex, Sha256Hex]
    adjudication_sha256: Sha256Hex | None
    field_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_field(self) -> Self:
        known = self.state != "unknown"
        if known:
            if (
                self.canonical_value is None
                or not self.accepted_values
                or self.canonical_value not in self.accepted_values
                or not self.evidence_targets
            ):
                raise ValueError("known Golden field lacks value or evidence")
        elif self.canonical_value is not None or self.accepted_values or self.evidence_targets:
            raise ValueError("unknown Golden field carries value or evidence")
        if len(set(self.annotator_decision_sha256s)) != 2:
            raise ValueError("independent annotator decisions required")
        if (self.conflict_status == "resolved") != (self.adjudication_sha256 is not None):
            raise ValueError("conflict adjudication mismatch")
        payload = self.model_dump(mode="python", exclude={"field_sha256"})
        if self.field_sha256 != schema_wiki_sha256(self.contract, payload):
            raise ValueError("Golden field hash mismatch")
        return self


class Schema67GoldenSet5961V1(_FrozenModel):
    contract: Literal["schema67-golden-set-596-1.v1"]
    golden_id: NonBlank
    golden_version: NonBlank
    product_version_id: Literal["596-1"]
    entity_version_id: Literal["ping-an-e-sheng-bao@596-1"]
    schema_pack_id: Literal["medical-schema67.v1"]
    schema_pack_sha256: Sha256Hex
    ordered_field_ids: tuple[NonBlank, ...]
    source_authorities: tuple[Schema67LiveSourceAuthorityV1, ...]
    fields: tuple[Schema67GoldenFieldV1, ...]
    annotator_principal_ids: tuple[NonBlank, NonBlank]
    whole_batch_approval_receipt_sha256: Sha256Hex
    normalization_policy_sha256: Sha256Hex = NORMALIZATION_POLICY_SHA256
    risk_policy_sha256: Sha256Hex = RISK_POLICY_SHA256
    metric_policy_sha256: Sha256Hex = METRIC_POLICY_SHA256
    golden_set_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_golden(self) -> Self:
        pack = make_medical_schema_pack_596_1()
        if (
            self.entity_version_id != MEDICAL_VERSION_ID
            or self.schema_pack_id != pack.schema_pack_id
            or self.schema_pack_sha256 != pack.schema_pack_sha256
            or self.ordered_field_ids != APPROVED_ORDERED_FIELD_IDS
            or tuple(item.field_id for item in self.fields) != APPROVED_ORDERED_FIELD_IDS
            or tuple(item.source_role for item in self.source_authorities)
            != ("terms", "brochure", "rate_table")
            or len(set(self.annotator_principal_ids)) != 2
            or any(not item.startswith("human:") for item in self.annotator_principal_ids)
            or self.normalization_policy_sha256 != NORMALIZATION_POLICY_SHA256
            or self.risk_policy_sha256 != RISK_POLICY_SHA256
            or self.metric_policy_sha256 != METRIC_POLICY_SHA256
        ):
            raise ValueError("Golden authority identity mismatch")
        if any(
            row.source_sha256 != row.live_revision_source_receipt.file_sha256
            for row in self.source_authorities
        ):
            raise ValueError("Golden source revision mismatch")
        source_by_role = {row.source_role: row for row in self.source_authorities}
        for field in self.fields:
            for target in field.evidence_targets:
                source = source_by_role.get(target.source_role)
                if source is None or (
                    target.live_revision_source_receipt_sha256
                    != source.live_revision_source_receipt.source_receipt_sha256
                    or target.revision_source_id
                    != source.live_revision_source_receipt.revision_source_id
                    or target.knowledge_id != source.live_revision_source_receipt.knowledge_id
                    or target.weknora_parse_attempt
                    != source.live_revision_source_receipt.weknora_parse_attempt
                    or target.file_sha256 != source.source_sha256
                    or target.weknora_manifest_algorithm
                    != source.live_revision_source_receipt.weknora_manifest_algorithm
                    or target.weknora_manifest_digest
                    != source.live_revision_source_receipt.weknora_manifest_digest
                ):
                    raise ValueError("Golden evidence source authority mismatch")
        payload = self.model_dump(mode="python", exclude={"golden_set_sha256"})
        if self.golden_set_sha256 != schema_wiki_sha256(self.contract, payload):
            raise ValueError("Golden set hash mismatch")
        return self


class Schema67GoldenFieldDecisionV1(_FrozenModel):
    field_id: NonBlank
    golden_field_sha256: Sha256Hex
    candidate_state: FieldState
    golden_state: FieldState
    state_correct: bool
    value_correct: bool
    evidence_fragments: StrictInt
    evidence_fragments_matched: StrictInt
    bbox_required: StrictInt
    bbox_passed: StrictInt
    high_risk_pass: bool
    conflict_resolved: bool
    decision_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"decision_sha256"})
        if (
            min(
                self.evidence_fragments,
                self.evidence_fragments_matched,
                self.bbox_required,
                self.bbox_passed,
            )
            < 0
            or self.evidence_fragments_matched > self.evidence_fragments
            or self.bbox_passed > self.bbox_required
            or self.decision_sha256
            != schema_wiki_sha256("schema67-golden-field-decision.v1", payload)
        ):
            raise ValueError("field decision invalid")
        return self


class Schema67GoldenMetricV1(_FrozenModel):
    metric_id: NonBlank
    numerator: StrictInt | None
    denominator: StrictInt | None
    value_ppm: Annotated[StrictInt, Field(ge=0, le=1_000_000)] | None
    supports: tuple[StrictInt, ...]
    evaluability: Literal["EVALUABLE", "NOT_EVALUABLE"]
    sample_size: Literal["SMALL_SAMPLE", "ADEQUATE", "NOT_EVALUABLE"]
    wilson_low_ppm: Annotated[StrictInt, Field(ge=0, le=1_000_000)] | None
    wilson_high_ppm: Annotated[StrictInt, Field(ge=0, le=1_000_000)] | None
    admission_status: Literal["PASS", "FAIL"]
    metric_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_metric(self) -> Self:
        evaluable = self.evaluability == "EVALUABLE"
        if evaluable != (
            self.numerator is not None
            and self.denominator is not None
            and self.denominator > 0
            and self.value_ppm is not None
        ):
            raise ValueError("metric denominator missing")
        if not evaluable and any(
            item is not None
            for item in (
                self.numerator,
                self.denominator,
                self.value_ppm,
                self.wilson_low_ppm,
                self.wilson_high_ppm,
            )
        ):
            raise ValueError("not-evaluable metric carries a value")
        payload = self.model_dump(mode="python", exclude={"metric_sha256"})
        if self.metric_sha256 != schema_wiki_sha256("schema67-golden-metric.v1", payload):
            raise ValueError("metric hash mismatch")
        return self


class Schema67GoldenPrivateDossierV1(_FrozenModel):
    contract: Literal["schema67-golden-private-dossier.v1"]
    candidate_sha256: Sha256Hex
    candidate_evidence_authority_sha256: Sha256Hex
    golden_set_sha256: Sha256Hex
    field_decisions: tuple[Schema67GoldenFieldDecisionV1, ...]
    metrics: tuple[Schema67GoldenMetricV1, ...]
    status: EvaluationStatus
    reason_codes: tuple[NonBlank, ...]
    dossier_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_dossier(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"dossier_sha256"})
        if (
            tuple(row.field_id for row in self.field_decisions) != APPROVED_ORDERED_FIELD_IDS
            or tuple(row.metric_id for row in self.metrics) != GOLDEN_METRIC_IDS
            or self.dossier_sha256 != schema_wiki_sha256(self.contract, payload)
        ):
            raise ValueError("private dossier mismatch")
        return self


class Schema67GoldenPublicAggregateV1(_FrozenModel):
    contract: Literal["schema67-golden-public-aggregate.v1"]
    product_version_id: Literal["596-1"]
    candidate_sha256: Sha256Hex
    golden_set_sha256: Sha256Hex
    evaluator_identity_sha256: Sha256Hex
    metrics: tuple[Schema67GoldenMetricV1, ...]
    status: EvaluationStatus
    reason_codes: tuple[NonBlank, ...]
    aggregate_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"aggregate_sha256"})
        if (
            tuple(row.metric_id for row in self.metrics) != GOLDEN_METRIC_IDS
            or self.evaluator_identity_sha256 != EVALUATOR_IDENTITY_SHA256
            or self.aggregate_sha256 != schema_wiki_sha256(self.contract, payload)
        ):
            raise ValueError("public aggregate mismatch")
        return self


class Schema67GoldenEvaluationResultV1(_FrozenModel):
    status: EvaluationStatus
    private_dossier: Schema67GoldenPrivateDossierV1
    public_aggregate: Schema67GoldenPublicAggregateV1
    quality_gate_receipt: Schema67GoldenQualityGateReceiptV1 | None
    provider_calls: Literal[0] = 0
    draft_calls: Literal[0] = 0
    review_calls: Literal[0] = 0
    activation_calls: Literal[0] = 0


_RECEIPT_LOCK = threading.Lock()
_RECEIPT_REGISTRY: dict[
    int, tuple[weakref.ReferenceType[Schema67GoldenQualityGateReceiptV1], str]
] = {}


def _register_receipt(receipt: Schema67GoldenQualityGateReceiptV1) -> None:
    identity = id(receipt)

    def remove(ref: weakref.ReferenceType[Schema67GoldenQualityGateReceiptV1]) -> None:
        with _RECEIPT_LOCK:
            current = _RECEIPT_REGISTRY.get(identity)
            if current is not None and current[0] is ref:
                _RECEIPT_REGISTRY.pop(identity, None)

    ref = weakref.ref(receipt, remove)
    with _RECEIPT_LOCK:
        _RECEIPT_REGISTRY[identity] = (ref, receipt.receipt_sha256)


def _require_registered_receipt(receipt: Schema67GoldenQualityGateReceiptV1) -> None:
    with _RECEIPT_LOCK:
        current = _RECEIPT_REGISTRY.get(id(receipt))
        if current is None or current[0]() is not receipt or current[1] != receipt.receipt_sha256:
            raise Schema67GoldenQualityGateError("QUALITY_GATE_RECEIPT_INVALID")


def _normalized(value: str | None) -> str | None:
    return None if value is None else value.strip()


def _join_projection(join: Schema67CitationAuthorityJoinReceiptV1) -> tuple[object, ...]:
    return (
        join.source_role,
        join.live_revision_source_receipt_sha256,
        join.live_revision_source_receipt.revision_source_id,
        join.knowledge_id,
        join.evidence_parse_attempt_id,
        join.weknora_parse_attempt,
        join.file_sha256,
        join.parsed_document_sha256,
        join.parse_manifest_sha256,
        join.weknora_manifest_algorithm,
        join.weknora_manifest_digest,
        join.chunk_id,
        join.page_number,
        join.locator_kind,
        join.locator_ref,
        join.quote_sha256,
        join.locator_content_sha256,
    )


def _target_projection(target: Schema67GoldenEvidenceTargetV1) -> tuple[object, ...]:
    return (
        target.source_role,
        target.live_revision_source_receipt_sha256,
        target.revision_source_id,
        target.knowledge_id,
        target.evidence_parse_attempt_id,
        target.weknora_parse_attempt,
        target.file_sha256,
        target.parsed_document_sha256,
        target.parse_manifest_sha256,
        target.weknora_manifest_algorithm,
        target.weknora_manifest_digest,
        target.chunk_id,
        target.page_number,
        target.locator_kind,
        target.locator_ref,
        target.quote_sha256,
        target.content_sha256,
    )


def _bbox_iou_ppm(
    join: Schema67CitationAuthorityJoinReceiptV1,
    target: Schema67GoldenEvidenceTargetV1,
) -> int | None:
    if target.bbox_evaluation == "not_evaluable":
        return None
    if (
        target.coordinate_space != join.target_coordinate_space
        or target.page_width != join.page_width
        or target.page_height != join.page_height
        or target.rotation_degrees != join.rotation_degrees
        or target.bbox is None
    ):
        return 0
    left = max(target.bbox.x0, join.normalized_bbox.x0)
    top = max(target.bbox.y0, join.normalized_bbox.y0)
    right = min(target.bbox.x1, join.normalized_bbox.x1)
    bottom = min(target.bbox.y1, join.normalized_bbox.y1)
    intersection = max(0, right - left) * max(0, bottom - top)
    target_area = (target.bbox.x1 - target.bbox.x0) * (target.bbox.y1 - target.bbox.y0)
    join_area = (join.normalized_bbox.x1 - join.normalized_bbox.x0) * (
        join.normalized_bbox.y1 - join.normalized_bbox.y0
    )
    union = target_area + join_area - intersection
    return 0 if union <= 0 else int(intersection * 1_000_000 / union)


def _decision(
    field: Schema67GoldenFieldV1,
    candidate_state: FieldState,
    candidate_value: str | None,
    joins: tuple[Schema67CitationAuthorityJoinReceiptV1, ...],
) -> Schema67GoldenFieldDecisionV1:
    state_correct = candidate_state == field.state
    value_correct = (
        candidate_state == "unknown" and field.state == "unknown" and candidate_value is None
    ) or (
        candidate_state == field.state != "unknown"
        and _normalized(candidate_value) in field.accepted_values
    )
    targets = {_target_projection(target): target for target in field.evidence_targets}
    matched = [join for join in joins if _join_projection(join) in targets]
    bbox_scores = [
        score
        for join in matched
        if (score := _bbox_iou_ppm(join, targets[_join_projection(join)])) is not None
    ]
    bbox_required = sum(target.bbox_evaluation == "required" for target in field.evidence_targets)
    bbox_passed = sum(score >= 800_000 for score in bbox_scores)
    evidence_exact = len(matched) == len(joins) and (field.state == "unknown" or bool(matched))
    conflict_resolved = field.conflict_status == "agreed" or field.adjudication_sha256 is not None
    high_risk_pass = field.risk_level == "standard" or (
        state_correct
        and value_correct
        and evidence_exact
        and all(score >= 900_000 for score in bbox_scores)
    )
    payload = {
        "field_id": field.field_id,
        "golden_field_sha256": field.field_sha256,
        "candidate_state": candidate_state,
        "golden_state": field.state,
        "state_correct": state_correct,
        "value_correct": value_correct,
        "evidence_fragments": len(joins),
        "evidence_fragments_matched": len(matched),
        "bbox_required": bbox_required,
        "bbox_passed": bbox_passed,
        "high_risk_pass": high_risk_pass,
        "conflict_resolved": conflict_resolved,
    }
    return Schema67GoldenFieldDecisionV1.model_validate(
        {
            **payload,
            "decision_sha256": schema_wiki_sha256("schema67-golden-field-decision.v1", payload),
        }
    )


def _wilson_ppm(numerator: int, denominator: int) -> tuple[int, int]:
    proportion = numerator / denominator
    z = 1.959963984540054
    denominator_term = 1 + z * z / denominator
    centre = (proportion + z * z / (2 * denominator)) / denominator_term
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / denominator + z * z / (4 * denominator * denominator)
        )
        / denominator_term
    )
    return (
        max(0, round((centre - margin) * 1_000_000)),
        min(1_000_000, round((centre + margin) * 1_000_000)),
    )


def _metric(
    metric_id: str,
    numerator: int | None,
    denominator: int | None,
    *,
    supports: tuple[int, ...] = (),
    passing: bool,
    binomial: bool = True,
) -> Schema67GoldenMetricV1:
    evaluable = denominator is not None and denominator > 0 and numerator is not None
    if evaluable:
        assert numerator is not None and denominator is not None
        value_ppm = round(numerator * 1_000_000 / denominator)
        interval: tuple[int | None, int | None] = (
            _wilson_ppm(numerator, denominator) if binomial else (None, None)
        )
        sample_size = "SMALL_SAMPLE" if denominator < 20 else "ADEQUATE"
    else:
        value_ppm = None
        interval = (None, None)
        sample_size = "NOT_EVALUABLE"
    payload = {
        "metric_id": metric_id,
        "numerator": numerator if evaluable else None,
        "denominator": denominator if evaluable else None,
        "value_ppm": value_ppm,
        "supports": supports,
        "evaluability": "EVALUABLE" if evaluable else "NOT_EVALUABLE",
        "sample_size": sample_size,
        "wilson_low_ppm": interval[0],
        "wilson_high_ppm": interval[1],
        "admission_status": "PASS" if evaluable and passing else "FAIL",
    }
    return Schema67GoldenMetricV1.model_validate(
        {
            **payload,
            "metric_sha256": schema_wiki_sha256("schema67-golden-metric.v1", payload),
        }
    )


def _metrics(
    fields: tuple[Schema67GoldenFieldV1, ...],
    decisions: tuple[Schema67GoldenFieldDecisionV1, ...],
    candidate_states: tuple[FieldState, ...],
) -> tuple[Schema67GoldenMetricV1, ...]:
    supports = Counter(field.state for field in fields)
    correct = Counter(
        field.state
        for field, decision in zip(fields, decisions, strict=True)
        if decision.state_correct
    )
    state_accuracy = sum(row.state_correct for row in decisions)
    class_recall_ppm = tuple(
        round(correct[state] * 1_000_000 / supports[state]) if supports[state] else 0
        for state in ("present", "absent_explicitly", "unknown")
    )
    macro_numerator = sum(class_recall_ppm)
    present_indexes = tuple(index for index, field in enumerate(fields) if field.state == "present")
    present_predicted = sum(state == "present" for state in candidate_states)
    present_correct = sum(decisions[index].value_correct for index in present_indexes)
    macro_f1_numerator = sum(
        1_000_000 if decisions[index].value_correct else 0 for index in present_indexes
    )
    absent_to_unknown = sum(
        field.state == "absent_explicitly" and candidate_states[index] == "unknown"
        for index, field in enumerate(fields)
    )
    unknown_to_absent = sum(
        field.state == "unknown" and candidate_states[index] == "absent_explicitly"
        for index, field in enumerate(fields)
    )
    present_present = sum(
        field.state == "present" and candidate_states[index] == "present"
        for index, field in enumerate(fields)
    )
    wrong_fills = sum(
        field.state == "present"
        and candidate_states[index] == "present"
        and not decisions[index].value_correct
        for index, field in enumerate(fields)
    )
    absent_unknown_support = supports["absent_explicitly"] + supports["unknown"]
    hallucinations = sum(
        field.state in {"absent_explicitly", "unknown"} and candidate_states[index] == "present"
        for index, field in enumerate(fields)
    )
    evidence_total = sum(row.evidence_fragments for row in decisions)
    evidence_matched = sum(row.evidence_fragments_matched for row in decisions)
    known_indexes = tuple(index for index, field in enumerate(fields) if field.state != "unknown")
    known_supported = sum(
        decisions[index].evidence_fragments_matched > 0 for index in known_indexes
    )
    bbox_total = sum(row.bbox_required for row in decisions)
    bbox_passed = sum(row.bbox_passed for row in decisions)
    high_indexes = tuple(
        index for index, field in enumerate(fields) if field.risk_level in {"critical", "high"}
    )
    high_passed = sum(decisions[index].high_risk_pass for index in high_indexes)
    conflict_indexes = tuple(
        index for index, field in enumerate(fields) if field.conflict_status == "resolved"
    )
    conflict_passed = sum(decisions[index].conflict_resolved for index in conflict_indexes)
    return (
        _metric(GOLDEN_METRIC_IDS[0], state_accuracy, 67, passing=state_accuracy >= 65),
        _metric(
            GOLDEN_METRIC_IDS[1],
            macro_numerator,
            (
                3_000_000
                if all(supports[state] > 0 for state in ("present", "absent_explicitly", "unknown"))
                else None
            ),
            supports=tuple(
                supports[state] for state in ("present", "absent_explicitly", "unknown")
            ),
            passing=all(value >= 950_000 for value in class_recall_ppm),
            binomial=False,
        ),
        _metric(
            GOLDEN_METRIC_IDS[2],
            present_correct,
            present_predicted,
            passing=present_predicted > 0 and present_correct * 100 >= present_predicted * 95,
        ),
        _metric(
            GOLDEN_METRIC_IDS[3],
            present_correct,
            len(present_indexes),
            passing=bool(present_indexes) and present_correct * 100 >= len(present_indexes) * 95,
        ),
        _metric(
            GOLDEN_METRIC_IDS[4],
            macro_f1_numerator,
            len(present_indexes) * 1_000_000 if present_indexes else None,
            passing=bool(present_indexes)
            and macro_f1_numerator * 10 >= len(present_indexes) * 9_000_000,
            binomial=False,
        ),
        _metric(
            GOLDEN_METRIC_IDS[5],
            absent_to_unknown,
            supports["absent_explicitly"],
            passing=absent_to_unknown == 0,
        ),
        _metric(
            GOLDEN_METRIC_IDS[6],
            unknown_to_absent,
            supports["unknown"],
            passing=unknown_to_absent == 0,
        ),
        _metric(
            GOLDEN_METRIC_IDS[7],
            wrong_fills,
            present_present,
            passing=present_present > 0 and wrong_fills * 100 <= present_present * 2,
        ),
        _metric(
            GOLDEN_METRIC_IDS[8],
            hallucinations,
            absent_unknown_support,
            passing=absent_unknown_support > 0 and hallucinations == 0,
        ),
        _metric(
            GOLDEN_METRIC_IDS[9],
            evidence_matched,
            evidence_total,
            passing=evidence_total > 0 and evidence_matched == evidence_total,
        ),
        _metric(
            GOLDEN_METRIC_IDS[10],
            known_supported,
            len(known_indexes),
            passing=bool(known_indexes) and known_supported == len(known_indexes),
        ),
        _metric(
            GOLDEN_METRIC_IDS[11],
            bbox_passed,
            bbox_total,
            passing=bbox_total > 0 and bbox_passed == bbox_total,
        ),
        _metric(
            GOLDEN_METRIC_IDS[12],
            bbox_passed,
            bbox_total,
            passing=bbox_total > 0 and bbox_passed == bbox_total,
        ),
        _metric(
            GOLDEN_METRIC_IDS[13],
            high_passed,
            len(high_indexes),
            passing=bool(high_indexes) and high_passed == len(high_indexes),
        ),
        _metric(
            GOLDEN_METRIC_IDS[14],
            conflict_passed,
            len(conflict_indexes),
            passing=bool(conflict_indexes) and conflict_passed == len(conflict_indexes),
        ),
    )


def validate_schema67_golden_quality_gate_receipt_596_1(
    receipt: object,
    *,
    candidate: object,
    evidence_authority: object,
) -> Schema67GoldenQualityGateReceiptV1:
    try:
        exact_candidate = validate_schema67_candidate_v2(candidate)
        exact_authority = validate_schema67_candidate_evidence_authority_596_1(
            candidate=exact_candidate,
            authority=evidence_authority,
        )
        if type(receipt) is not Schema67GoldenQualityGateReceiptV1:
            raise TypeError
        _require_registered_receipt(receipt)
        if (
            receipt.candidate_sha256 != exact_candidate.candidate_sha256
            or receipt.candidate_evidence_authority_sha256 != exact_authority.authority_sha256
            or receipt.evaluator_identity_sha256 != EVALUATOR_IDENTITY_SHA256
            or receipt.metric_policy_sha256 != METRIC_POLICY_SHA256
        ):
            raise ValueError
        return receipt
    except (CandidateEvidenceAuthorityError, TypeError, ValueError, ValidationError):
        raise Schema67GoldenQualityGateError("QUALITY_GATE_RECEIPT_INVALID") from None


def evaluate_schema67_golden_quality_596_1(
    *,
    candidate: object,
    evidence_authority: object,
    golden: Schema67GoldenSet5961V1,
) -> Schema67GoldenEvaluationResultV1:
    if candidate is None:
        raise Schema67GoldenQualityGateError("CANDIDATE_ABSENT")
    try:
        exact_candidate = validate_schema67_candidate_v2(candidate)
        exact_authority = validate_schema67_candidate_evidence_authority_596_1(
            candidate=exact_candidate,
            authority=evidence_authority,
        )
        exact_golden = Schema67GoldenSet5961V1.model_validate(
            golden.model_dump(mode="python", round_trip=True)
        )
        candidate_source_rows = tuple(
            (row["role"], row["source_sha256"]) for row in exact_candidate.source_roles
        )
        golden_source_rows = tuple(
            (row.source_role, row.source_sha256) for row in exact_golden.source_authorities
        )
        if (
            candidate_source_rows != golden_source_rows
            or exact_golden.source_authorities != exact_authority.source_authorities
        ):
            raise ValueError
        outputs = {row.field_id: row for row in exact_candidate.fields}
        joins: dict[str, list[Schema67CitationAuthorityJoinReceiptV1]] = {}
        for row in exact_authority.join_receipts:
            joins.setdefault(row.field_id, []).append(row)
        decisions = tuple(
            _decision(
                field,
                outputs[field.field_id].state,
                outputs[field.field_id].value_snapshot,
                tuple(joins.get(field.field_id, ())),
            )
            for field in exact_golden.fields
        )
        metrics = _metrics(
            exact_golden.fields,
            decisions,
            tuple(outputs[field_id].state for field_id in APPROVED_ORDERED_FIELD_IDS),
        )
        fixture = exact_candidate.candidate_sha256 == PROVIDER_ZERO_FIXTURE_CANDIDATE_SHA256
        passed = not fixture and all(row.admission_status == "PASS" for row in metrics)
        status: EvaluationStatus = "FIXTURE_ONLY" if fixture else "PASS" if passed else "FAIL"
        reasons = (
            ("PROVIDER_ZERO_FIXTURE_ONLY",)
            if fixture
            else ()
            if passed
            else tuple(row.metric_id for row in metrics if row.admission_status == "FAIL")
        )
        dossier_payload = {
            "contract": "schema67-golden-private-dossier.v1",
            "candidate_sha256": exact_candidate.candidate_sha256,
            "candidate_evidence_authority_sha256": exact_authority.authority_sha256,
            "golden_set_sha256": exact_golden.golden_set_sha256,
            "field_decisions": decisions,
            "metrics": metrics,
            "status": status,
            "reason_codes": reasons,
        }
        dossier = Schema67GoldenPrivateDossierV1.model_validate(
            {
                **dossier_payload,
                "dossier_sha256": schema_wiki_sha256(
                    "schema67-golden-private-dossier.v1", dossier_payload
                ),
            }
        )
        aggregate_payload = {
            "contract": "schema67-golden-public-aggregate.v1",
            "product_version_id": "596-1",
            "candidate_sha256": exact_candidate.candidate_sha256,
            "golden_set_sha256": exact_golden.golden_set_sha256,
            "evaluator_identity_sha256": EVALUATOR_IDENTITY_SHA256,
            "metrics": metrics,
            "status": status,
            "reason_codes": reasons,
        }
        aggregate = Schema67GoldenPublicAggregateV1.model_validate(
            {
                **aggregate_payload,
                "aggregate_sha256": schema_wiki_sha256(
                    "schema67-golden-public-aggregate.v1", aggregate_payload
                ),
            }
        )
        receipt = None
        if passed:
            receipt_payload = {
                "contract": "schema67-golden-quality-gate-receipt.v1",
                "status": "PASS",
                "product_version_id": "596-1",
                "candidate_sha256": exact_candidate.candidate_sha256,
                "candidate_evidence_authority_sha256": exact_authority.authority_sha256,
                "golden_set_sha256": exact_golden.golden_set_sha256,
                "golden_version": exact_golden.golden_version,
                "evaluator_identity_sha256": EVALUATOR_IDENTITY_SHA256,
                "metric_policy_sha256": METRIC_POLICY_SHA256,
                "ordered_field_decision_sha256s": tuple(row.decision_sha256 for row in decisions),
                "metric_receipt_sha256s": tuple(row.metric_sha256 for row in metrics),
                "private_dossier_sha256": dossier.dossier_sha256,
                "public_aggregate_sha256": aggregate.aggregate_sha256,
            }
            receipt = Schema67GoldenQualityGateReceiptV1.model_validate(
                {
                    **receipt_payload,
                    "receipt_sha256": schema_wiki_sha256(
                        "schema67-golden-quality-gate-receipt.v1", receipt_payload
                    ),
                }
            )
            _register_receipt(receipt)
        result = Schema67GoldenEvaluationResultV1(
            status=status,
            private_dossier=dossier,
            public_aggregate=aggregate,
            quality_gate_receipt=receipt,
        )
        if result.quality_gate_receipt is not None:
            _register_receipt(result.quality_gate_receipt)
        return result
    except Schema67GoldenQualityGateError:
        raise
    except (
        AttributeError,
        CandidateEvidenceAuthorityError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        raise Schema67GoldenQualityGateError("SCHEMA67_GOLDEN_QUALITY_GATE_FAILED") from None


__all__ = [
    "EVALUATOR_IDENTITY_SHA256",
    "GOLDEN_METRIC_IDS",
    "METRIC_POLICY_SHA256",
    "PROVIDER_ZERO_FIXTURE_CANDIDATE_SHA256",
    "Schema67GoldenEvidenceTargetV1",
    "Schema67GoldenEvaluationResultV1",
    "Schema67GoldenFieldDecisionV1",
    "Schema67GoldenFieldV1",
    "Schema67GoldenMetricV1",
    "Schema67GoldenPrivateDossierV1",
    "Schema67GoldenPublicAggregateV1",
    "Schema67GoldenQualityGateError",
    "Schema67GoldenSet5961V1",
    "evaluate_schema67_golden_quality_596_1",
    "validate_schema67_golden_quality_gate_receipt_596_1",
]
