"""Reproduce the full 596 Golden score using a deliberately partial offline response.

The fixture is authored from repository PDF text, not a live model recording.
Expected values are loaded only after compilation, never passed to the engine.
Run with pytest -q -s tests/compilers/schema_fields/test_offline_replay.py.
"""

import hashlib
import json
import socket
from pathlib import Path

import pytest
from pydantic import BaseModel

from insurance_harness.compilers.schema_fields.definitions import pack_definitions
from insurance_harness.compilers.schema_fields.engine import SchemaFieldsCompiler, to_candidate
from insurance_harness.eval.convert import predictions_from_candidate
from insurance_harness.eval.evaluator import evaluate
from insurance_harness.eval.golden import GoldenItem
from insurance_harness.evidence.quote_verification import PageText

ROOT = Path(__file__).resolve().parents[4]


class Recording(BaseModel):
    provenance: str
    entity_id: str
    display_name: str
    product_id: str
    pack_id: str
    document_path: str
    field_keys: list[str]
    pages: list[PageText]
    responses: list[str]


class RecordedCompletion:
    model = "offline-authored-replay"

    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.requests: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.requests.append((system, user))
        return next(self.responses)


def test_repository_golden_replay_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline replay attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    fixture = Path(__file__).with_name("fixtures") / "medical_replay.json"
    recording = Recording.model_validate_json(fixture.read_text(encoding="utf-8"))
    document = ROOT / recording.document_path
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    assert all(page.document_sha256 == digest for page in recording.pages)
    definitions = [
        field
        for field in pack_definitions(
            ROOT / "internal/handler/schema_pack_catalog_830_g3.generated.json",
            recording.pack_id,
        )
        if field.field_key in recording.field_keys
    ]

    port = RecordedCompletion(recording.responses)
    compiler = SchemaFieldsCompiler(port)
    requests = compiler.build_requests(recording.entity_id, definitions, recording.pages)
    output = compiler.compile(recording.entity_id, definitions, recording.pages)
    assert port.requests == [(request.system, request.user) for request in requests]
    assert (
        output.calls == 1 and [field.field_key for field in output.fields] == recording.field_keys
    )
    candidate = to_candidate(
        output,
        display_name=recording.display_name,
        schema_pack_id=recording.pack_id,
    )
    predictions = predictions_from_candidate(
        candidate, {recording.display_name: recording.product_id}
    )
    golden = [
        GoldenItem.model_validate_json(line)
        for line in (ROOT / "dataset/golden/v1/596.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = evaluate(golden, predictions)
    assert (report.micro.tp, report.micro.fp, report.micro.fn) == (1, 1, 29)
    assert report.micro.precision == 0.5
    assert report.micro.recall == pytest.approx(1 / 30)
    assert report.missing_predictions == 38
    repeated = SchemaFieldsCompiler(RecordedCompletion(recording.responses)).compile(
        recording.entity_id,
        definitions,
        recording.pages,
    )
    assert repeated == output
    print(
        json.dumps(
            {
                "recording": "offline-authored; no model-quality claim",
                "calls": output.calls,
                "golden_items": len(golden),
                "predicted_fields": len(predictions),
                "metrics": report.micro.model_dump(mode="json"),
                "missing_predictions": report.missing_predictions,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
