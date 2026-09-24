"""Provider refs bind original bytes; the strict domain projector stays authoritative."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from insurance_harness.product_ingestion.native_admission_preflight import (
    preflight_native_admission_response,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_native_admission_preflight import sample

pytest_plugins = ("tests.product_ingestion.test_discovery",)
PROTOCOL = "native-knowledge-admission.830.v3"


def wire_sample(case: Any) -> tuple[Any, ...]:
    request, entity, snapshot, source, context, payload = sample(case)
    payload = deepcopy(payload)
    payload["contract"] = PROTOCOL
    page = payload["pages"][0]
    del page["evidence"]
    segment = page["content_provenance"]["segments"][0]
    del segment["evidence_indexes"]
    segment["evidence_refs"] = ["s1:1"]
    return request, entity, snapshot, source, context, payload


def run_wire(values: tuple[Any, ...]) -> Any:
    request, entity, snapshot, source, context, payload = values
    return preflight_native_admission_response(
        raw=json_bytes(payload),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        context=context,
        wire_protocol=PROTOCOL,
    )


def test_refs_bind_crlf_unicode_without_rewriting_body_or_origin(case: Any) -> None:
    values = wire_sample(case)
    outcome = run_wire(values)
    assert outcome.failure is None
    page = outcome.projection.output.pages[0]
    assert page.evidence[0].quote == values[3].blocks[0].text
    assert "\r\n🙂" in page.evidence[0].quote
    assert page.evidence[0].start == 0
    assert page.content_provenance.segments[0].origin == "SOURCE_SUPPORTED"
    assert page.body == values[-1]["pages"][0]["body"]


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "duplicate",
        "model_with_ref",
        "source_empty",
        "body_gap",
        "legacy_evidence",
        "context_tamper",
    ],
)
def test_refs_reject_invalid_or_unbound_claims(case: Any, fault: str) -> None:
    values = wire_sample(case)
    page = values[-1]["pages"][0]
    segment = page["content_provenance"]["segments"][0]
    if fault == "unknown":
        segment["evidence_refs"] = ["other:1"]
    elif fault == "duplicate":
        segment["evidence_refs"] *= 2
    elif fault == "model_with_ref":
        segment["origin"] = "MODEL_GENERATED"
    elif fault == "source_empty":
        segment["evidence_refs"] = []
    elif fault == "body_gap":
        page["body"] += "未标记正文"
    elif fault == "legacy_evidence":
        page["evidence"] = []
    else:
        values[-2]["source_options"][0]["spans"][0]["quote"] += "篡改"
    outcome = run_wire(values)
    assert outcome.projection is None and outcome.failure


def test_source_paraphrase_and_generated_explanation_keep_separate_marks(case: Any) -> None:
    values = wire_sample(case)
    page = values[-1]["pages"][0]
    explanation = "这是模型补充的阅读提示。"
    page["body"] += explanation
    page["content_provenance"]["segments"].append(
        {"text": explanation, "origin": "MODEL_GENERATED", "evidence_refs": []}
    )
    outcome = run_wire(values)
    assert outcome.failure is None
    segments = outcome.projection.output.pages[0].content_provenance.segments
    assert [s.origin for s in segments] == ["SOURCE_SUPPORTED", "MODEL_GENERATED"]
    assert [s.evidence_indexes for s in segments] == [(0,), ()]


def test_wire_value_hash_is_distinct_from_original_bytes(case: Any) -> None:
    values = wire_sample(case)
    request, entity, snapshot, source, context, payload = values
    raw = json.dumps(payload, ensure_ascii=False, indent=4).encode()
    assert raw != json_bytes(payload)
    outcome = preflight_native_admission_response(
        raw=raw,
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        context=context,
        wire_protocol=PROTOCOL,
    )
    assert outcome.failure is None
    assert outcome.receipt["original_sha256"] == hashlib.sha256(raw).hexdigest()
    expansion = outcome.receipt["wire_expansion"]
    assert expansion.get("wire_value_sha256") == hashlib.sha256(json_bytes(payload)).hexdigest()
    assert "original_sha256" not in expansion


def test_multiple_refs_require_catalog_order(case: Any) -> None:
    from insurance_harness.product_ingestion.native_admission_wire import expand_wire_response

    *_, context, payload = wire_sample(case)
    other = deepcopy(context["source_options"][0])
    other["source_ref"] = "s2"
    context["source_options"].append(other)
    segment = payload["pages"][0]["content_provenance"]["segments"][0]
    segment["evidence_refs"] = ["s1:1", "s2:1"]
    expanded, _ = expand_wire_response(payload, context)
    assert [e["source_ref"] for e in expanded["pages"][0]["evidence"]] == ["s1", "s2"]
    segment["evidence_refs"].reverse()
    with pytest.raises(ValueError, match="invalid evidence refs"):
        expand_wire_response(payload, context)
