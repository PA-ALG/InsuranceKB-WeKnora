from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import typing
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


def module() -> typing.Any:
    path = Path(__file__).parents[2] / "src/insurance_harness/product_ingestion/extraction.py"
    assert path.is_file(), "platform single-window extraction executor is not implemented"
    return importlib.import_module("insurance_harness.product_ingestion.extraction")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def source() -> SourceBlock:
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


def tasks(
    source: typing.Any, keys: typing.Any = ("benefit", "duration"), *, discovery: bool = False
) -> typing.Any:
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
            {
                **r.model_dump(exclude={"task_sha256", "contract"}),
                "adapter_kind": "CATALOG_SCHEMA",
            }
        )
        for r in rows
    )


def response(fields: typing.Any) -> bytes:
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


def row(
    task: typing.Any,
    request: typing.Any,
    *,
    state: str = "present",
    value: typing.Any = "100",
    quote: typing.Any = "赔付金额为100元。",
) -> dict[str, typing.Any]:
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
    def __init__(self, make_response: typing.Any) -> None:
        self.make_response = make_response
        self.events: list[str] = []
        self.request: bytes | None = None
        self.saved_raw: bytes | None = None
        self.diagnostic: str | None = None

    async def begin(self, call_id: object, request_sha256: str, request_bytes: bytes) -> None:
        assert request_sha256 == sha(request_bytes)
        self.events.append("begin")
        self.request = request_bytes

    async def transport(self, request_bytes: bytes) -> typing.Any:
        assert self.events == ["begin"]
        self.events.append("transport")
        return self.make_response(json.loads(request_bytes))

    async def persist(
        self,
        call_id: object,
        request_sha256: str,
        raw: bytes | None,
        diagnostic: str | None,
    ) -> str:
        assert self.request is not None
        assert request_sha256 == sha(self.request)
        self.events.append("persist")
        self.saved_raw, self.diagnostic = raw, diagnostic
        return "raw-artifact-1"


def execute(
    source: typing.Any, selected: typing.Any, port: typing.Any, **kwargs: typing.Any
) -> typing.Any:
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


def test_mixed_fields_keep_valid_result_and_save_raw_before_projection(source: typing.Any) -> None:
    selected = tasks(source)
    port = Port(
        lambda request: response(
            [
                row(selected[0], request),
                row(selected[1], request, quote="原文不存在的引用"),
            ]
        )
    )

    def decode(raw: bytes) -> typing.Any:
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
def test_unknown_is_valid_not_provided_and_cached_without_transport(
    source: typing.Any, discovery: typing.Any
) -> None:
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


def test_partial_cache_omits_successful_tasks_from_new_request(source: typing.Any) -> None:
    selected = tasks(source)
    first = Port(lambda request: response([row(selected[0], request)]))
    known = execute(source, selected[:1], first)[0]

    def remaining(request: typing.Any) -> typing.Any:
        assert [r["field_ref"] for r in request["field_targets"]] == [selected[1].task_sha256]
        return response([row(selected[1], request, state="unknown", value=None)])

    port = Port(remaining)
    outputs = execute(source, selected, port, cached={(known.entity_id, known.field_key): known})
    assert [r.outcome for r in outputs] == ["verified", "not_provided"]


@pytest.mark.parametrize("mutation", ["no_value", "no_evidence", "unknown_value", "blank_reason"])
def test_invalid_tristate_never_exposes_value(source: typing.Any, mutation: typing.Any) -> None:
    selected = tasks(source, ("benefit",))

    def wire(request: typing.Any) -> typing.Any:
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
def test_value_constraint_failure_is_per_field(
    source: typing.Any, kind: typing.Any, value: typing.Any, allowed: typing.Any
) -> None:
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
def test_missing_duplicate_refs_do_not_discard_valid_siblings(
    source: typing.Any, variant: typing.Any
) -> None:
    selected = tasks(source)

    def wire(request: typing.Any) -> typing.Any:
        values = [row(selected[1], request)]
        if variant == "duplicate":
            values += [row(selected[0], request)] * 2
        return response(values)

    assert [x.outcome for x in execute(source, selected, Port(wire))] == [
        "extraction_failed",
        "verified",
    ]


@pytest.mark.parametrize("wire", [b"not json", b'{"fields":[],"fields":[]}', b'{"fields":[]}'])
def test_bad_envelope_preserves_bytes_and_fails_window(
    source: typing.Any, wire: typing.Any
) -> None:
    selected = tasks(source)
    port = Port(lambda _: wire)
    outcomes = execute(source, selected, port)
    assert port.saved_raw == wire
    assert all(x.outcome == "extraction_failed" and x.validated_result is None for x in outcomes)


def test_foreign_field_ref_fails_window(source: typing.Any) -> None:
    selected = tasks(source)

    def wire(request: typing.Any) -> typing.Any:
        values = [row(t, request) for t in selected]
        values.append({**values[0], "field_ref": "foreign"})
        return response(values)

    assert all(x.outcome == "extraction_failed" for x in execute(source, selected, Port(wire)))


def test_line_joined_quote_cannot_be_normalized_into_evidence(source: typing.Any) -> None:
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


def test_transport_error_is_recorded_without_retry(source: typing.Any) -> None:
    selected = tasks(source)

    def fail(_: object) -> None:
        raise TimeoutError("secret-like provider body must not enter public reasons")

    port = Port(fail)
    results = execute(source, selected, port)
    assert port.events == ["begin", "transport", "persist"]
    assert port.saved_raw is None and port.diagnostic == "transport:TimeoutError"
    assert all(x.outcome == "extraction_failed" for x in results)
    assert "secret-like" not in json.dumps([x.to_dict() for x in results])


def test_recorded_raw_replay_has_zero_provider_effects(source: typing.Any) -> None:
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
def test_uncertain_dispatch_never_calls_transport(source: typing.Any, state: typing.Any) -> None:
    selected = tasks(source)
    port = Port(lambda _: pytest.fail("uncertain dispatch cannot be retried"))
    outcomes = execute(source, selected, port, call_state=state)
    assert port.events == []
    assert all(
        x.outcome == "extraction_failed" and x.reason == "CALL_INTERRUPTED" for x in outcomes
    )


@pytest.mark.parametrize("failure", ["begin", "persist"])
def test_checkpoint_failure_cannot_settle_or_reissue(
    source: typing.Any, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tasks(source)
    port = Port(lambda request: response([row(t, request) for t in selected]))

    async def broken(*args: object) -> None:
        raise RuntimeError("store fence rejected")

    monkeypatch.setattr(port, failure, broken)
    with pytest.raises(RuntimeError, match="store fence rejected"):
        execute(source, selected, port)
    assert port.events == ([] if failure == "begin" else ["begin", "transport"])


@pytest.mark.parametrize("mutation", ["tenant", "hash", "missing"])
def test_source_scope_is_verified_before_any_dispatch(
    source: typing.Any, mutation: typing.Any
) -> None:
    selected = tasks(source)
    if mutation == "tenant":
        source = source.model_copy(update={"tenant_id": 2})
    elif mutation == "hash":
        source = source.model_copy(update={"source_hash": sha(b"other")})
    else:
        selected = tuple(
            _task(
                {
                    **t.model_dump(exclude={"task_sha256", "contract"}),
                    "allowed_sources": (),
                }
            )
            for t in selected
        )
    port = Port(lambda _: pytest.fail("invalid custody must not dispatch"))
    with pytest.raises(ValueError, match="source|scope"):
        execute(source, selected, port)
    assert port.events == []


def test_recorded_response_keeps_original_scope_when_sibling_is_now_cached(
    source: typing.Any,
) -> None:
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


def test_cache_json_cannot_claim_verified_without_value_or_evidence(source: typing.Any) -> None:
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


@pytest.fixture
def many_source_tasks(source: typing.Any) -> tuple[typing.Any, ...]:
    sources = tuple(
        source.model_copy(
            update={
                "knowledge_id": "00000000-0000-0000-0000-000000000001",
                "revision_id": "a" * 64,
                "parser_identity": "b" * 64,
                "block_id": f"00000000-0000-0000-0000-{i:012d}",
                "text": "赔付金额为100元。\n" + "费率数据" * 600,
            }
        )
        for i in range(1401)
    )
    scope = tuple(
        FieldTaskSourceV1(
            material_id="00000000-0000-0000-0000-000000000001",
            revision_id=s.revision_id,
            block_id=s.block_id,
            source_hash=s.source_hash,
            parser_identity=s.parser_identity,
        )
        for s in sources
    )
    selected = tuple(
        _task(
            {
                **t.model_dump(exclude={"task_sha256", "contract"}),
                "material_ids": ("00000000-0000-0000-0000-000000000001",),
                "allowed_sources": scope,
            }
        )
        for t in tasks(source, tuple(f"field_{i:02d}" for i in range(10)))
    )
    return sources, selected


@pytest.mark.parametrize("count", [1, 10])
def test_compact_v2_large_source_scope_fits_real_preflight(
    many_source_tasks: typing.Any, count: typing.Any
) -> None:
    from insurance_harness.product_ingestion.model_execution import (
        _template_and_request,
    )
    from insurance_harness.product_ingestion.models import ProductScope
    from tests.product_ingestion.test_model_execution import configured

    sources, all_tasks = many_source_tasks
    selected = all_tasks[:count]
    original = tuple(t.model_dump_json() for t in selected)
    scope = ProductScope(
        tenant_id="1",
        space_id="space-1",
        raw_knowledge_base_id="raw-1",
        wiki_knowledge_base_id="wiki-1",
    )
    config = configured(scope)
    settings = type(config).model_validate(
        {
            **config.model_dump(),
            "api_key": config.api_key,
            "templates": tuple(
                t.model_copy(update={"max_context_bytes": 300_000}) for t in config.templates
            ),
            "max_request_bytes": 2_000_000,
        }
    )
    raw = module().render_window_request(
        selected, sources, tenant_id=1, space_id="space-1", raw_kb_id="raw-1"
    )
    _, prepared = _template_and_request(
        settings,
        scope=scope,
        content=raw,
        input_sha256=sha(raw),
        prompt=b"field prompt",
        template_id=settings.field_template_id,
    )
    context = json.loads(raw)
    assert context["contract"] == "product-field-window-request.v2"
    assert len(raw) <= 300_000 and len(prepared.request_bytes) <= 2_000_000
    offered = {row["source_ref"] for row in context["source_options"]}
    assert 0 < len(offered) < 1401
    for target, task in zip(context["field_targets"], selected, strict=True):
        assert "allowed_sources" not in target
        assert set(target["allowed_source_refs"]) == offered
        assert target["field_ref"] == task.task_sha256
        assert len(task.allowed_sources) == 1401
    assert tuple(t.model_dump_json() for t in selected) == original


def recorded_request_version(source: typing.Any, selected: typing.Any, version: int) -> typing.Any:
    request = json.loads(
        module().render_window_request(
            selected, (source,), tenant_id=1, space_id="space-1", raw_kb_id="raw-1"
        )
    )
    request["contract"] = f"product-field-window-request.v{version}"
    if version == 1:
        request["field_targets"] = [
            {**t.model_dump(mode="json"), "field_ref": t.task_sha256} for t in selected
        ]
    return request


@pytest.mark.parametrize("version", [1, 2])
def test_compact_v2_and_original_v1_recorded_success_replay_without_dispatch(
    source: typing.Any, version: typing.Any
) -> None:
    selected = tasks(source)
    current = Port(lambda request: response([row(t, request) for t in selected]))
    expected = execute(source, selected, current)
    request = recorded_request_version(source, selected, version)
    original_request = json.dumps(request, ensure_ascii=False).encode()
    original_raw = response([row(t, request) for t in selected])
    unused = Port(lambda _: pytest.fail("recorded response must not redispatch"))
    actual = execute(
        source,
        selected,
        unused,
        call_state="recorded",
        recorded_request_bytes=original_request,
        recorded_raw=original_raw,
        recorded_raw_ref="raw-artifact-1",
    )
    assert actual == expected and unused.events == []
    assert json.loads(original_request) == request
    assert original_raw == response([row(t, request) for t in selected])


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("mutation", ["task", "scope", "span"])
def test_compact_recorded_versions_refuse_changed_task_scope_or_span(
    source: typing.Any, version: typing.Any, mutation: typing.Any
) -> None:
    selected = tasks(source, ("benefit",))
    request = recorded_request_version(source, selected, version)
    if mutation == "task":
        request["field_targets"][0]["description"] = "changed"
    elif mutation == "scope":
        request["source_options"][0]["source"]["tenant_id"] = 2
    else:
        request["source_options"][0]["spans"][0]["quote"] = "forged"
    unused = Port(lambda _: pytest.fail("invalid recorded custody must not dispatch"))
    with pytest.raises(ValueError, match="scope|span"):
        execute(
            source,
            selected,
            unused,
            call_state="recorded",
            recorded_request_bytes=json.dumps(request).encode(),
            recorded_raw=response([row(selected[0], request)]),
            recorded_raw_ref="raw-artifact-1",
        )
    assert unused.events == []


def test_compact_v2_recorded_refs_cannot_expand_local_task_sources(source: typing.Any) -> None:
    selected = tasks(source, ("benefit",))
    request = recorded_request_version(source, selected, 2)
    request["field_targets"][0]["allowed_source_refs"] = ["source_foreign"]
    unused = Port(lambda _: pytest.fail("foreign source refs must not dispatch"))
    with pytest.raises(ValueError, match="scope"):
        execute(
            source,
            selected,
            unused,
            call_state="recorded",
            recorded_request_bytes=json.dumps(request).encode(),
            recorded_raw=response([row(selected[0], request)]),
            recorded_raw_ref="raw-artifact-1",
        )
    assert unused.events == []


@pytest.mark.parametrize("version", [1, 2])
def test_compact_recorded_versions_reject_quote_outside_offered_spans(
    source: typing.Any, version: typing.Any
) -> None:
    selected = tasks(source, ("benefit",))
    request = recorded_request_version(source, selected, version)
    # The source contains the insurance term, but this call offered only the first sentence.
    request["source_options"][0]["spans"] = [
        {"start": 0, "end": 10, "quote": source.text[:10], "heading": ""}
    ]
    raw = response([row(selected[0], request, quote="保险期间一年。")])
    unused = Port(lambda _: pytest.fail("recorded response must not redispatch"))
    actual = execute(
        source,
        selected,
        unused,
        call_state="recorded",
        recorded_request_bytes=json.dumps(request, ensure_ascii=False).encode(),
        recorded_raw=raw,
        recorded_raw_ref="raw-artifact-1",
    )
    assert actual[0].outcome == "extraction_failed" and actual[0].validated_result is None
    assert unused.events == []


def test_window_source_check_does_not_serialize_a_redundant_full_batch(
    source: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from insurance_harness.knowledge_compiler import g3_field_tasks

    selected = tasks(source)
    serialized_batches = []
    original = g3_field_tasks._json_bytes

    def observe(value: typing.Any) -> typing.Any:
        if isinstance(value, dict) and value.get("contract") == "g3-field-task-batch.830.v1":
            serialized_batches.append(value)
        return original(value)

    monkeypatch.setattr(g3_field_tasks, "_json_bytes", observe)
    module().render_window_request(
        selected, (source,), tenant_id=1, space_id="space-1", raw_kb_id="raw-1"
    )
    assert not serialized_batches, "window validation serializes every source dependency again"
