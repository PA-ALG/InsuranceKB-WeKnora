from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import SourceBlock
from insurance_harness.knowledge_compiler.g3_field_tasks import (
    DiscoveryFieldProposalV1,
    FieldTaskSourceV1,
    FieldValueConstraintV1,
    _task,
    adapt_discovery_field_tasks,
)


def module():
    path = Path(__file__).parents[2] / "src/insurance_harness/product_ingestion/extraction.py"
    assert path.is_file(), "platform single-window extraction executor is not implemented"
    return importlib.import_module("insurance_harness.product_ingestion.extraction")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def source():
    return SourceBlock(
        tenant_id=1,
        space_id="space-1",
        raw_kb_id="raw-1",
        knowledge_id="knowledge-1",
        parse_attempt=1,
        revision_id="revision-1",
        source_hash=sha(b"pdf"),
        parse_hash=sha(b"parsed"),
        parser_identity="native-v1",
        block_id="block-1",
        page_number=4,
        text="赔付金额为100元。\r\n保险期间一年。赔付金额为100元。",
        source_type="DOCUMENT",
    )


def tasks(source, keys=("benefit", "duration"), *, discovery=False):
    rows = adapt_discovery_field_tasks(
        entity_id="product-1",
        entity_version="version-1",
        material_ids=("material-1",),
        proposals=tuple(DiscoveryFieldProposalV1(field_key=k, short_title=k) for k in keys),
        discovery_protocol_version="discovery-v1",
        allowed_sources=(
            FieldTaskSourceV1(
                material_id="material-1",
                revision_id=source.revision_id,
                block_id=source.block_id,
                source_hash=source.source_hash,
                parser_identity=source.parser_identity,
            ),
        ),
    )
    if discovery:
        return rows
    return tuple(
        _task(
            {**r.model_dump(exclude={"task_sha256", "contract"}), "adapter_kind": "CATALOG_SCHEMA"}
        )
        for r in rows
    )


def response(fields):
    return json.dumps(
        {
            "contract": "g3-d-compile-semantic-references.local.v1",
            "transformation": "EXTRACT",
            "definitions": [],
            "fields": fields,
            "pages": [],
        },
        ensure_ascii=False,
        indent=2,
    ).encode()


def row(task, request, *, state="present", value="100", quote="赔付金额为100元。"):
    return {
        "field_ref": task.task_sha256,
        "state": state,
        "value": value,
        "unknown_reason": "材料未提供该字段" if state == "unknown" else None,
        "evidence": []
        if state == "unknown"
        else [
            {
                "source_ref": request["source_options"][0]["source_ref"],
                "quote": quote,
            }
        ],
        "concept_refs": [],
        "conditions": [],
        "exceptions": [],
        "valid_time": "",
        "audit_reason": "原始来源核验",
    }


class Port:
    def __init__(self, make_response):
        self.make_response = make_response
        self.events = []
        self.request = None
        self.saved_raw = None
        self.diagnostic = None

    async def begin(self, call_id, request_sha256, request_bytes):
        assert request_sha256 == sha(request_bytes)
        self.events.append("begin")
        self.request = request_bytes

    async def transport(self, request_bytes):
        assert self.events == ["begin"]
        self.events.append("transport")
        return self.make_response(json.loads(request_bytes))

    async def persist(self, call_id, request_sha256, raw, diagnostic):
        assert request_sha256 == sha(self.request)
        self.events.append("persist")
        self.saved_raw, self.diagnostic = raw, diagnostic
        return "raw-artifact-1"


def execute(source, selected, port, **kwargs):
    return asyncio.run(
        module().execute_window(
            call_id="call-1",
            tasks=selected,
            sources=(source,),
            tenant_id=1,
            space_id="space-1",
            raw_kb_id="raw-1",
            transport=port.transport,
            begin_call=port.begin,
            persist_raw=port.persist,
            **kwargs,
        )
    )


def test_mixed_fields_keep_valid_result_and_save_raw_before_projection(source):
    selected = tasks(source)
    port = Port(
        lambda request: response(
            [
                row(selected[0], request),
                row(selected[1], request, quote="原文不存在的引用"),
            ]
        )
    )

    def decode(raw):
        assert port.events == ["begin", "transport", "persist"]
        assert port.saved_raw == raw
        return raw

    outcomes = execute(source, selected, port, decode_response=decode)
    assert [x.outcome for x in outcomes] == ["verified", "extraction_failed"]
    assert outcomes[0].validated_result.value == "100"
    assert outcomes[1].validated_result is None
    assert "原文不存在" not in json.dumps(outcomes[1].to_dict(), ensure_ascii=False)
    assert len(outcomes[0].validated_result.evidence) == 2
    assert [(e.start, e.end, e.page_number) for e in outcomes[0].validated_result.evidence] == [
        (0, 10, 4),
        (19, 29, 4),
    ]


@pytest.mark.parametrize("discovery", [False, True])
def test_unknown_is_valid_not_provided_and_cached_without_transport(source, discovery):
    selected = tasks(source, ("missing",), discovery=discovery)
    port = Port(lambda request: response([row(selected[0], request, state="unknown", value=None)]))
    outcomes = execute(source, selected, port)
    assert outcomes[0].outcome == "not_provided"
    assert outcomes[0].validated_result.value is None
    unused = Port(lambda _: pytest.fail("cached result must not dispatch"))
    changed = _task(
        {
            **selected[0].model_dump(exclude={"task_sha256", "contract"}),
            "adapter_version": "new-audit-version",
        }
    )
    reused = execute(
        source,
        (changed,),
        unused,
        cached={
            (selected[0].entity_id, selected[0].field_key): outcomes[0],
        },
    )
    assert reused == outcomes
    assert unused.events == []


def test_partial_cache_omits_successful_tasks_from_new_request(source):
    selected = tasks(source)
    first = Port(lambda request: response([row(selected[0], request)]))
    known = execute(source, selected[:1], first)[0]

    def remaining(request):
        assert [r["field_ref"] for r in request["field_targets"]] == [selected[1].task_sha256]
        return response([row(selected[1], request, state="unknown", value=None)])

    port = Port(remaining)
    outputs = execute(source, selected, port, cached={(known.entity_id, known.field_key): known})
    assert [r.outcome for r in outputs] == ["verified", "not_provided"]


@pytest.mark.parametrize("mutation", ["no_value", "no_evidence", "unknown_value", "blank_reason"])
def test_invalid_tristate_never_exposes_value(source, mutation):
    selected = tasks(source, ("benefit",))

    def wire(request):
        value = row(selected[0], request, state="absent_explicitly")
        if mutation == "no_value":
            value["value"] = None
        elif mutation == "no_evidence":
            value["evidence"] = []
        elif mutation == "unknown_value":
            value.update(state="unknown", unknown_reason="未知")
        else:
            value.update(state="unknown", value=None, evidence=[], unknown_reason="   ")
        return response([value])

    out = execute(source, selected, Port(wire))[0]
    assert out.outcome == "extraction_failed" and out.validated_result is None


@pytest.mark.parametrize(
    "kind,value,allowed",
    [
        ("DATE", "2026-02-30", ()),
        ("NUMBER", "NaN", ()),
        ("ENUM", "other", ("yes",)),
    ],
)
def test_value_constraint_failure_is_per_field(source, kind, value, allowed):
    original = tasks(source, ("a_bad", "b_good"))
    bad = _task(
        {
            **original[0].model_dump(exclude={"task_sha256", "contract"}),
            "value_constraint": FieldValueConstraintV1(kind=kind, allowed_values=allowed),
        }
    )
    selected = (bad, original[1])
    port = Port(
        lambda request: response(
            [
                row(bad, request, value=value),
                row(original[1], request),
            ]
        )
    )
    assert [x.outcome for x in execute(source, selected, port)] == [
        "extraction_failed",
        "verified",
    ]


@pytest.mark.parametrize("variant", ["missing", "duplicate"])
def test_missing_duplicate_refs_do_not_discard_valid_siblings(source, variant):
    selected = tasks(source)

    def wire(request):
        values = [row(selected[1], request)]
        if variant == "duplicate":
            values += [row(selected[0], request)] * 2
        return response(values)

    assert [x.outcome for x in execute(source, selected, Port(wire))] == [
        "extraction_failed",
        "verified",
    ]


@pytest.mark.parametrize("wire", [b"not json", b'{"fields":[],"fields":[]}', b'{"fields":[]}'])
def test_bad_envelope_preserves_bytes_and_fails_window(source, wire):
    selected = tasks(source)
    port = Port(lambda _: wire)
    outcomes = execute(source, selected, port)
    assert port.saved_raw == wire
    assert all(x.outcome == "extraction_failed" and x.validated_result is None for x in outcomes)


def test_foreign_field_ref_fails_window(source):
    selected = tasks(source)

    def wire(request):
        values = [row(t, request) for t in selected]
        values.append({**values[0], "field_ref": "foreign"})
        return response(values)

    assert all(x.outcome == "extraction_failed" for x in execute(source, selected, Port(wire)))


def test_line_joined_quote_cannot_be_normalized_into_evidence(source):
    selected = tasks(source, ("benefit",))
    port = Port(
        lambda request: response(
            [
                row(
                    selected[0],
                    request,
                    quote="赔付金额为100元。保险期间一年。",
                )
            ]
        )
    )
    assert execute(source, selected, port)[0].outcome == "extraction_failed"


def test_transport_error_is_recorded_without_retry(source):
    selected = tasks(source)

    def fail(_):
        raise TimeoutError("secret-like provider body must not enter public reasons")

    port = Port(fail)
    results = execute(source, selected, port)
    assert port.events == ["begin", "transport", "persist"]
    assert port.saved_raw is None and port.diagnostic == "transport:TimeoutError"
    assert all(x.outcome == "extraction_failed" for x in results)
    assert "secret-like" not in json.dumps([x.to_dict() for x in results])


def test_recorded_raw_replay_has_zero_provider_effects(source):
    selected = tasks(source)
    first = Port(lambda request: response([row(t, request) for t in selected]))
    expected = execute(source, selected, first)
    second = Port(lambda _: pytest.fail("recorded raw must never redispatch"))
    actual = execute(
        source,
        selected,
        second,
        call_state="recorded",
        recorded_request_bytes=first.request,
        recorded_raw=first.saved_raw,
        recorded_raw_ref="raw-artifact-1",
    )
    assert actual == expected and second.events == []


@pytest.mark.parametrize("state", ["dispatching", "interrupted"])
def test_uncertain_dispatch_never_calls_transport(source, state):
    selected = tasks(source)
    port = Port(lambda _: pytest.fail("uncertain dispatch cannot be retried"))
    outcomes = execute(source, selected, port, call_state=state)
    assert port.events == []
    assert all(
        x.outcome == "extraction_failed" and x.reason == "CALL_INTERRUPTED" for x in outcomes
    )


@pytest.mark.parametrize("failure", ["begin", "persist"])
def test_checkpoint_failure_cannot_settle_or_reissue(source, failure):
    selected = tasks(source)
    port = Port(lambda request: response([row(t, request) for t in selected]))

    async def broken(*args):
        raise RuntimeError("store fence rejected")

    if failure == "begin":
        port.begin = broken
    else:
        port.persist = broken
    with pytest.raises(RuntimeError, match="store fence rejected"):
        execute(source, selected, port)
    assert port.events == ([] if failure == "begin" else ["begin", "transport"])


@pytest.mark.parametrize("mutation", ["tenant", "hash", "missing"])
def test_source_scope_is_verified_before_any_dispatch(source, mutation):
    selected = tasks(source)
    if mutation == "tenant":
        source = source.model_copy(update={"tenant_id": 2})
    elif mutation == "hash":
        source = source.model_copy(update={"source_hash": sha(b"other")})
    else:
        selected = tuple(
            _task({**t.model_dump(exclude={"task_sha256", "contract"}), "allowed_sources": ()})
            for t in selected
        )
    port = Port(lambda _: pytest.fail("invalid custody must not dispatch"))
    with pytest.raises(ValueError, match="source|scope"):
        execute(source, selected, port)
    assert port.events == []


def test_recorded_response_keeps_original_scope_when_sibling_is_now_cached(source):
    selected = tasks(source)
    first = Port(lambda request: response([row(t, request) for t in selected]))
    expected = execute(source, selected, first)
    second = Port(lambda _: pytest.fail("recorded raw must never redispatch"))
    actual = execute(
        source,
        selected,
        second,
        call_state="recorded",
        recorded_request_bytes=first.request,
        recorded_raw=first.saved_raw,
        recorded_raw_ref="raw-artifact-1",
        cached={(expected[0].entity_id, expected[0].field_key): expected[0]},
    )
    assert actual == expected and second.events == []


def test_cache_json_cannot_claim_verified_without_value_or_evidence(source):
    selected = tasks(source, ("benefit",))
    first = Port(lambda request: response([row(selected[0], request)]))
    value = execute(source, selected, first)[0].to_dict()
    result = value["validated_result"]
    result.update(value=None, evidence=[])
    raw = {k: v for k, v in result.items() if k != "result_sha256"}
    result["result_sha256"] = sha(
        json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    )
    with pytest.raises(ValueError, match="validated|verified"):
        module().FieldOutcome.from_dict(value)
