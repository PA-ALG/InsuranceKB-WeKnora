from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json

import pytest

from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    CompileOutput,
    CompileResult,
    ExecutionRecord,
    PageMember,
    ReviewOutput,
    ReviewResult,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    FieldAssertion,
    FreeWikiPage,
    SourceBlock,
    concept_canonical_bytes,
    evidence_for,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    schema_wiki_canonical_bytes,
    schema_wiki_sha256,
)


def _canonical_api() -> tuple[object, object]:
    name = "insurance_harness.knowledge_compiler.batch_canonical_830_g3"
    if importlib.util.find_spec(name) is None:
        return schema_wiki_canonical_bytes, schema_wiki_sha256
    module = importlib.import_module(name)
    return module.batch_canonical_bytes_830_g3, module.batch_sha256_830_g3


def _canonical_module() -> object:
    return importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_canonical_830_g3"
    )


def test_multiline_body_is_preserved_and_line_endings_are_distinct() -> None:
    canonical, sha256 = _canonical_api()
    lf = _source("first\nsecond")
    crlf = _source("first\r\nsecond")

    lf_bytes = canonical("corpus-entry.830.g3.v1", lf)  # type: ignore[operator]
    crlf_bytes = canonical("corpus-entry.830.g3.v1", crlf)  # type: ignore[operator]

    assert b'"text":"first\\nsecond"' in lf_bytes
    assert b'"text":"first\\r\\nsecond"' in crlf_bytes
    assert lf_bytes != crlf_bytes
    assert sha256("corpus-entry.830.g3.v1", lf) == hashlib.sha256(lf_bytes).hexdigest()  # type: ignore[operator]
    assert sha256("corpus-entry.830.g3.v1", crlf) == hashlib.sha256(crlf_bytes).hexdigest()  # type: ignore[operator]


def test_control_free_payload_is_byte_identical_to_shared_canonical() -> None:
    canonical, sha256 = _canonical_api()
    payload = {"contract": "fixture.v1", "id": "m1", "values": ["中文", 1, True, None]}

    assert canonical("fixture.v1", payload) == concept_canonical_bytes("fixture.v1", payload)  # type: ignore[operator]
    assert sha256("fixture.v1", payload) == schema_wiki_sha256("fixture.v1", payload)  # type: ignore[operator]


def test_domain_and_body_invalid_values_remain_rejected() -> None:
    canonical, _ = _canonical_api()
    for domain in ("", "域.v1", "bad\ndomain"):
        with pytest.raises((TypeError, ValueError, UnicodeEncodeError)):
            canonical(domain, {"value": "ok"})  # type: ignore[operator]
    for value in ("bad\x00body", "bad\x7fbody", "e\u0301"):
        with pytest.raises((TypeError, ValueError)):
            canonical("fixture.v1", {"value": value})  # type: ignore[operator]
    with pytest.raises((TypeError, ValueError)):
        canonical("fixture.v1", {"value": 1.5})  # type: ignore[operator]
    with pytest.raises((TypeError, ValueError)):
        canonical("fixture.v1", {"bad\nkey": "value"})  # type: ignore[operator]


def _source(text: str) -> SourceBlock:
    return SourceBlock(
        tenant_id=7,
        space_id="space-g3",
        raw_kb_id="raw-g3",
        knowledge_id="knowledge-g3",
        parse_attempt=1,
        revision_id="revision-g3",
        source_hash="1" * 64,
        parse_hash="2" * 64,
        parser_identity="parser-g3",
        block_id="block-g3",
        page_number=1,
        text=text,
        source_type="DOCUMENT",
    )


def test_exact_typed_source_body_preserves_non_nfc_without_plain_mapping_bypass() -> None:
    canonical, sha256 = _canonical_api()
    raw = "actual-\uf99c-source"
    source = _source(raw)

    payload = canonical("source-block.830.g3.v1", source)  # type: ignore[operator]

    assert raw.encode() in payload
    assert sha256("source-block.830.g3.v1", source) == hashlib.sha256(payload).hexdigest()  # type: ignore[operator]
    with pytest.raises(ValueError):
        canonical("fixture.v1", {"text": raw})  # type: ignore[operator]


def _compile_result(text: str = "actual-\uf99c-source") -> CompileResult:
    source = _source(text)
    evidence = evidence_for(source, 0, len(source.text))
    definition = ConceptDefinition(
        space_id=source.space_id,
        canonical_key="coverage",
        sense_key="primary",
        title="Coverage",
        body="Grounded definition",
        evidence=(evidence,),
    )
    output = CompileOutput(
        request_hash="3" * 64,
        definitions=(definition,),
        fields=(),
    )
    module = _canonical_module()
    raw = module.batch_json_bytes_830_g3(output).decode("utf-8")  # type: ignore[attr-defined]
    execution = ExecutionRecord(
        run_id="compile-run",
        implementation="fixture-compiler",
        context_hash="4" * 64,
        raw_output=raw,
        raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
    )
    return CompileResult(output=output, execution=execution)


def _review_result() -> ReviewResult:
    output = ReviewOutput(
        request_hash="3" * 64,
        output_hash="5" * 64,
        decision="PASS",
    )
    module = _canonical_module()
    raw = module.batch_json_bytes_830_g3(output).decode("utf-8")  # type: ignore[attr-defined]
    return ReviewResult(
        output=output,
        execution=ExecutionRecord(
            run_id="review-run",
            implementation="fixture-reviewer",
            context_hash="6" * 64,
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )


def test_exact_paired_results_preserve_only_their_bound_raw_output() -> None:
    module = _canonical_module()
    result = _compile_result()
    raw = module.batch_json_bytes_830_g3(result)  # type: ignore[attr-defined]
    assert "actual-\uf99c-source".encode() in raw
    assert json.loads(raw)["execution"]["raw_output"] == result.execution.raw_output

    review = _review_result()
    assert json.loads(module.batch_json_bytes_830_g3(review))["output"][  # type: ignore[attr-defined]
        "decision"
    ] == "PASS"


def test_paired_execution_hash_keeps_execution_domain_and_rejects_open_routes() -> None:
    module = _canonical_module()
    result = _compile_result("ordinary NFC source")
    helper = module.paired_execution_sha256_830_g3  # type: ignore[attr-defined]
    domain = "batch-concept-model-execution.830.g3.v1"
    assert helper(domain, result) == module.batch_sha256_830_g3(  # type: ignore[attr-defined]
        domain, result.execution
    )

    non_nfc = _compile_result()
    non_nfc_wire = json.loads(module.batch_json_bytes_830_g3(non_nfc))  # type: ignore[attr-defined]
    expected_preimage = (
        b"schema-wiki-canonical.v1\0"
        + domain.encode("ascii")
        + b"\0"
        + json.dumps(
            non_nfc_wire["execution"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    assert helper(domain, non_nfc) == hashlib.sha256(expected_preimage).hexdigest()
    for value in (
        non_nfc.execution,
        non_nfc.execution.raw_output,
        non_nfc.model_dump(mode="json"),
    ):
        with pytest.raises((TypeError, ValueError)):
            module.batch_json_bytes_830_g3(value)  # type: ignore[attr-defined]

    class DerivedCompileResult(CompileResult):
        pass

    derived = DerivedCompileResult.model_validate(non_nfc.model_dump(mode="python"))
    with pytest.raises((TypeError, ValueError)):
        module.batch_json_bytes_830_g3(derived)  # type: ignore[attr-defined]
    with pytest.raises((TypeError, ValueError)):
        helper(domain, derived)


def test_paired_result_rejects_raw_output_output_and_hash_drift() -> None:
    module = _canonical_module()
    result = _compile_result()
    different_raw = module.batch_json_bytes_830_g3(  # type: ignore[attr-defined]
        result.output.model_copy(update={"transformation": "NORMALIZE"})
    ).decode()
    noncanonical_raw = json.dumps(json.loads(result.execution.raw_output), ensure_ascii=False)
    attacks = (
        result.model_copy(
            update={
                "execution": result.execution.model_copy(
                    update={
                        "raw_output": different_raw,
                        "raw_output_hash": hashlib.sha256(different_raw.encode()).hexdigest(),
                    }
                )
            }
        ),
        result.model_copy(
            update={
                "execution": result.execution.model_copy(
                    update={
                        "raw_output": noncanonical_raw,
                        "raw_output_hash": hashlib.sha256(
                            noncanonical_raw.encode()
                        ).hexdigest(),
                    }
                )
            }
        ),
        CompileResult.model_construct(
            output=result.output,
            execution=ExecutionRecord.model_construct(
                **{**result.execution.model_dump(), "raw_output_hash": "0" * 64}
            ),
        ),
    )
    for attack in attacks:
        with pytest.raises((TypeError, ValueError)):
            module.batch_json_bytes_830_g3(attack)  # type: ignore[attr-defined]


def test_page_member_dispatches_body_payload_by_fixed_kind() -> None:
    module = _canonical_module()
    definition = _compile_result().output.definitions[0]
    payload = definition.model_dump(mode="json")
    member = PageMember(
        kind="concept",
        member_id=definition.concept_id,
        owner_id=definition.space_id,
        title=definition.title,
        content=definition.body,
        payload=payload,
    )
    raw = module.batch_json_bytes_830_g3(member)  # type: ignore[attr-defined]
    assert "actual-\uf99c-source".encode() in raw

    evidence = definition.evidence
    field = FieldAssertion(
        space_id=definition.space_id,
        entity_id="entity-1",
        field_key="coverage",
        state="present",
        value="Covered",
        attempted=True,
        evidence=evidence,
        entity_version="version-1",
    )
    page = FreeWikiPage(
        space_id=definition.space_id,
        entity_id="entity-1",
        stable_key="details",
        title="Details",
        body="Grounded page",
        evidence=evidence,
        entity_version="version-1",
    )
    typed_members = (
        PageMember(
            kind="field_assertion",
            member_id=field.assertion_id,
            owner_id=field.entity_id,
            title=field.field_key,
            content=field.value or "",
            payload=field.model_dump(mode="json"),
        ),
        PageMember(
            kind="free_wiki_item",
            member_id="free-details",
            owner_id=page.entity_id,
            title=page.title,
            content=page.body,
            payload=page.model_dump(mode="json"),
        ),
    )
    for typed_member in typed_members:
        assert "actual-\uf99c-source".encode() in module.batch_json_bytes_830_g3(  # type: ignore[attr-defined]
            typed_member
        )

    for kind, changed_payload in (
        ("field_assertion", payload),
        ("concept", {**payload, "extra": "forbidden"}),
        ("entity_overview", {"member_ids": ["actual-\uf99c-source"]}),
    ):
        attack = member.model_copy(update={"kind": kind, "payload": changed_payload})
        with pytest.raises((TypeError, ValueError)):
            module.batch_json_bytes_830_g3(attack)  # type: ignore[attr-defined]

    coerced_payload = json.loads(json.dumps(payload))
    coerced_payload["evidence"][0]["page_number"] = True
    coercion = member.model_copy(update={"payload": coerced_payload})
    with pytest.raises((TypeError, ValueError)):
        module.batch_json_bytes_830_g3(coercion)  # type: ignore[attr-defined]

    class DerivedPageMember(PageMember):
        pass

    derived = DerivedPageMember.model_validate(member.model_dump(mode="python"))
    with pytest.raises((TypeError, ValueError)):
        module.batch_json_bytes_830_g3(derived)  # type: ignore[attr-defined]


def test_existing_nfc_result_and_member_bytes_stay_generic_canonical() -> None:
    module = _canonical_module()
    result = _compile_result("ordinary NFC source")
    expected = json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert module.batch_json_bytes_830_g3(result) == expected  # type: ignore[attr-defined]
