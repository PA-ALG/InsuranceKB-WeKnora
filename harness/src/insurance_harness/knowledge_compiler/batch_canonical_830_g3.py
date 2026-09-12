"""Canonical hashing for typed G3 batch bodies with exact source text."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, datetime

from pydantic import BaseModel

from .concept_compile_830_g2 import (
    AuditDisposition,
    CompileOutput,
    CompileResult,
    ExecutionRecord,
    PageMember,
    ReviewOutput,
    ReviewResult,
    free_page_id,
)
from .concept_free_wiki_830_g2 import (
    ConceptDefinition,
    Evidence,
    FieldAssertion,
    FreeWikiPage,
    SourceBlock,
)

_PREFIX = b"schema-wiki-canonical.v1\0"
_MISSING = object()


def _structured(value: str, *, object_key: bool = False) -> str:
    if unicodedata.normalize("NFC", value) != value or any(
        ord(character) == 0x7F
        or (
            ord(character) < 0x20
            and (object_key or character not in "\t\n\r")
        )
        for character in value
    ):
        raise ValueError("G3 batch structured text is not canonical")
    return value


def _body(value: str) -> str:
    if any(
        ord(character) == 0x7F
        or (ord(character) < 0x20 and character not in "\t\n\r")
        for character in value
    ):
        raise ValueError("G3 batch source body contains a forbidden control")
    return value


def _encode_tree(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _paired_result_tree(value: CompileResult | ReviewResult) -> dict[str, object]:
    if type(value) is CompileResult:
        checked: CompileResult | ReviewResult = CompileResult.model_validate(value)
        output_type: type[CompileOutput] | type[ReviewOutput] = CompileOutput
    elif type(value) is ReviewResult:
        checked = ReviewResult.model_validate(value)
        output_type = ReviewOutput
    else:
        raise TypeError("paired execution requires an exact compile or review result")
    if type(checked.output) is not output_type or type(checked.execution) is not ExecutionRecord:
        raise TypeError("paired result contains a non-exact output or execution")

    output_tree = _tree(checked.output)
    output_raw = _encode_tree(output_tree)
    execution = checked.execution
    if execution.raw_output.encode("utf-8") != output_raw:
        raise ValueError("paired result raw output does not match its typed output")
    if hashlib.sha256(output_raw).hexdigest() != execution.raw_output_hash:
        raise ValueError("paired result raw output hash mismatch")

    execution_wire = execution.model_dump(
        mode="json", round_trip=True, warnings=False, exclude_computed_fields=True
    )
    execution_tree = {
        name: _tree(
            getattr(execution, name),
            execution_wire[name],
            body=name == "raw_output",
        )
        for name in type(execution).model_fields
    }
    return {"output": output_tree, "execution": execution_tree}


def _typed_model_tree(value: BaseModel, body_fields: frozenset[str]) -> dict[str, object]:
    wire = value.model_dump(
        mode="json", round_trip=True, warnings=False, exclude_computed_fields=True
    )
    return {
        name: _tree(getattr(value, name), wire[name], body=name in body_fields)
        for name in type(value).model_fields
    }


def _field_member_content(value: FieldAssertion) -> tuple[str, str]:
    simple = value.value if value.value is not None else "未知：" + (value.unknown_reason or "")
    if value.state == "present":
        lines = ["值：" + (value.value or "")]
    elif value.state == "absent_explicitly":
        lines = ["明确不提供：" + (value.value or "")]
    else:
        lines = ["未知：" + (value.unknown_reason or "")]
    lines.extend("条件：" + item for item in value.conditions)
    lines.extend("例外：" + item for item in value.exceptions)
    if value.valid_time:
        lines.append("有效期：" + value.valid_time)
    return simple, "\n".join(lines)


def _page_member_content(value: FreeWikiPage) -> tuple[str, str]:
    lines = [value.body]
    lines.extend("条件：" + item for item in value.conditions)
    lines.extend("例外：" + item for item in value.exceptions)
    if value.valid_time:
        lines.append("有效期：" + value.valid_time)
    return value.body, "\n".join(lines)


def _page_member_tree(value: PageMember) -> dict[str, object]:
    if type(value) is not PageMember:
        raise TypeError("page-member canonicalization requires the exact DTO")
    checked = PageMember.model_validate(value)
    if checked.kind == "concept":
        typed_payload: BaseModel | None = ConceptDefinition.model_validate(checked.payload)
    elif checked.kind == "field_assertion":
        typed_payload = FieldAssertion.model_validate(checked.payload)
    elif checked.kind == "free_wiki_item":
        typed_payload = FreeWikiPage.model_validate(checked.payload)
    else:
        typed_payload = None
    if typed_payload is None:
        payload_tree = _tree(checked.payload)
        body_fields: frozenset[str] = frozenset()
    else:
        wire = typed_payload.model_dump(
            mode="json", round_trip=True, warnings=False, exclude_computed_fields=True
        )
        if _encode_tree(wire) != _encode_tree(checked.payload):
            raise ValueError("page-member payload changed during exact DTO validation")
        if isinstance(typed_payload, ConceptDefinition):
            if (
                checked.member_id != typed_payload.concept_id
                or checked.owner_id != typed_payload.space_id
                or checked.title != typed_payload.title
                or checked.content != typed_payload.body
            ):
                raise ValueError("concept page-member projection mismatch")
            body_fields = frozenset(("title", "content"))
        elif isinstance(typed_payload, FieldAssertion):
            if (
                checked.member_id != typed_payload.assertion_id
                or checked.owner_id != typed_payload.entity_id
                or checked.content not in _field_member_content(typed_payload)
            ):
                raise ValueError("field page-member projection mismatch")
            body_fields = frozenset(("content",))
        else:
            assert isinstance(typed_payload, FreeWikiPage)
            if (
                checked.member_id != free_page_id(typed_payload)
                or checked.owner_id != typed_payload.entity_id
                or checked.title != typed_payload.title
                or checked.content not in _page_member_content(typed_payload)
            ):
                raise ValueError("free-page member projection mismatch")
            body_fields = frozenset(("title", "content"))
        payload_tree = _tree(typed_payload)
    wire = checked.model_dump(
        mode="json", round_trip=True, warnings=False, exclude_computed_fields=True
    )
    return {
        name: payload_tree
        if name == "payload"
        else _tree(
            getattr(checked, name), wire[name], body=name in body_fields
        )
        for name in type(checked).model_fields
    }


def _tree(value: object, serialized: object = _MISSING, *, body: bool = False) -> object:
    if type(value) is CompileResult or type(value) is ReviewResult:
        assert isinstance(value, CompileResult | ReviewResult)
        return _paired_result_tree(value)
    if isinstance(value, CompileResult | ReviewResult):
        raise TypeError("result subclasses do not receive body canonicalization")
    if type(value) is PageMember:
        return _page_member_tree(value)
    if isinstance(value, PageMember):
        raise TypeError("page-member subclasses do not receive body canonicalization")
    if type(value) is SourceBlock or type(value) is Evidence:
        assert isinstance(value, BaseModel)
        wire = value.model_dump(
            mode="json", round_trip=True, warnings=False, exclude_computed_fields=True
        )
        body_field = "text" if type(value) is SourceBlock else "quote"
        return {
            name: _tree(getattr(value, name), wire[name], body=name == body_field)
            for name in type(value).model_fields
        }
    if type(value) is ConceptDefinition:
        return _typed_model_tree(value, frozenset(("title", "body")))
    if type(value) is FieldAssertion:
        return _typed_model_tree(
            value,
            frozenset(
                (
                    "value",
                    "unknown_reason",
                    "conditions",
                    "exceptions",
                    "valid_time",
                )
            ),
        )
    if type(value) is FreeWikiPage:
        return _typed_model_tree(
            value,
            frozenset(("title", "body", "conditions", "exceptions", "valid_time")),
        )
    if type(value) is AuditDisposition:
        return _typed_model_tree(value, frozenset(("reason",)))
    if type(value) is ReviewOutput:
        return _typed_model_tree(value, frozenset(("reasons",)))
    if isinstance(value, BaseModel):
        wire = value.model_dump(
            mode="json", round_trip=True, warnings=False, exclude_computed_fields=True
        )
        return {
            name: _tree(getattr(value, name), wire[name])
            for name in type(value).model_fields
            if name in wire
        }
    if type(value) is str:
        return _body(value) if body else _structured(value)
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        raise TypeError("binary floats are not canonical G3 batch values")
    if isinstance(value, date | datetime):
        if type(serialized) is not str:
            raise TypeError("date value lacks its canonical JSON representation")
        return _structured(serialized)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        serialized_mapping = serialized if isinstance(serialized, Mapping) else None
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("G3 batch object keys must be strings")
            _structured(key, object_key=True)
            fallback = (
                serialized_mapping[key]
                if serialized_mapping is not None and key in serialized_mapping
                else _MISSING
            )
            result[key] = _tree(item, fallback)
        return result
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        wire_items = serialized if isinstance(serialized, Sequence) else ()
        return [
            _tree(
                item,
                wire_items[index] if index < len(wire_items) else _MISSING,
                body=body,
            )
            for index, item in enumerate(value)
        ]
    if serialized is not _MISSING and serialized is not value:
        return _tree(serialized)
    raise TypeError(f"unsupported canonical G3 batch type: {type(value).__name__}")


def batch_json_bytes_830_g3(payload: object) -> bytes:
    """Return canonical JSON for a typed G3 batch value without a hash prefix."""

    return _encode_tree(_tree(payload))


def _validate_object_type(object_type: str) -> None:
    if type(object_type) is not str or not object_type or not object_type.isascii():
        raise ValueError("G3 batch hash object type must be non-empty ASCII")
    _structured(object_type, object_key=True)


def batch_canonical_bytes_830_g3(object_type: str, payload: object) -> bytes:
    """Return the shared preimage with exemptions bound to exact G2 body types."""

    _validate_object_type(object_type)
    return _PREFIX + object_type.encode("ascii") + b"\0" + batch_json_bytes_830_g3(payload)


def batch_sha256_830_g3(object_type: str, payload: object) -> str:
    return hashlib.sha256(batch_canonical_bytes_830_g3(object_type, payload)).hexdigest()


def definition_sha256_830_g3(definition: ConceptDefinition) -> str:
    """Preserve the historical alias-excluded definition hash with typed body text."""

    if type(definition) is not ConceptDefinition:
        raise TypeError("definition hash requires the exact DTO")
    tree = _typed_model_tree(definition, frozenset(("title", "body")))
    del tree["aliases"]
    object_type = "concept-definition.830.g2.v1"
    return hashlib.sha256(
        _PREFIX + object_type.encode("ascii") + b"\0" + _encode_tree(tree)
    ).hexdigest()


def paired_execution_sha256_830_g3(
    object_type: str, result: CompileResult | ReviewResult
) -> str:
    """Hash only a paired result's closed execution wire under an existing domain."""

    _validate_object_type(object_type)
    tree = _paired_result_tree(result)
    return hashlib.sha256(
        _PREFIX + object_type.encode("ascii") + b"\0" + _encode_tree(tree["execution"])
    ).hexdigest()


__all__ = [
    "batch_canonical_bytes_830_g3",
    "batch_json_bytes_830_g3",
    "batch_sha256_830_g3",
    "definition_sha256_830_g3",
    "paired_execution_sha256_830_g3",
]
