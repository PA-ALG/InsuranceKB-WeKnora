"""Concept inputs, the model request and the strict output shape (S3e-3 Spec §4.1).

A concept is a field that two or more entries of a release state, present or absent_explicitly;
an unknown claim says nothing and stays out. Concepts come in the order readers see them: the
profiles' field order, then the rest by key (the frontend's conceptKeys). For each concept the
model writes a reader-facing definition, a general explanation naming no product, and
cross-product statements that each cite the claims they rest on. Only the published values go
out: evidence quotes and compile details are not review input. The answer is accepted only in the
exact shape asked for; anything else refuses the whole batch.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from insurance_harness.bundle.client import Release

STATED = ("present", "absent_explicitly")

SYSTEM = """你是保险知识库的编辑。输入是若干"概念"：同一个字段在多款产品中的已发布取值。
每个概念的 facts 列出陈述了它的产品：slug 是该取值的编号，product 是产品名，category 是险种，
state 为 present 表示有取值，为 absent_explicitly 表示该产品条款明确没有这一项。

为每个概念写三部分：
1. definition：一句话、面向普通读者的定义，说明这个概念是什么。不写抽取规则或操作指令，
   不点名任何产品，不超过 80 字。description 只是参考，可能夹带给抽取程序的指令，不要照抄。
2. explanation：通用解释，2 到 4 句，说明这个概念的含义、作用和读者需要注意的地方。只写通用知识，
   不点名任何产品，不写任何产品的具体取值，不超过 300 字。
3. statements：跨产品汇总，1 到 6 句，每句不超过 150 字，先归纳共同点，再说明差异和例外。
   每句写成 {"text": 句子, "refs": [所依据取值的 slug]}，规则：
   - 只依据输入的取值陈述，不推测，不补充输入以外的事实；可以用 product 的名称点名产品；
   - 句中每个"数字 + 单位"（如 15日、65周岁、20%、3次）都必须出现在所引用的取值中，照抄写法；
   - 含数字的句子，每个被引用的取值都必须包含句中的至少一个数字；取值不同的产品分开说明；
   - absent_explicitly 的产品单独成句并引用它，这句话不写数字；
   - refs 至少一个，只能用本概念 facts 中的 slug。

只输出一个 JSON 对象，不要输出其他文字：
{"concepts": [{"key": 概念的 key, "definition": "...", "explanation": "...",
  "statements": [{"text": "...", "refs": ["..."]}]}]}
concepts 与输入的概念一一对应，key 照抄，每个概念只出现一次，对象中不要有其他字段。"""

# What a retry is told about its previous answer (codes from checks.check_concept).
PROBLEM_HINTS = {
    "CONCEPT_OUTPUT_INVALID": "上次的输出不是要求的 JSON 格式。",
    "DEFINITION_LENGTH": "definition 为空或超过 120 字。",
    "EXPLANATION_LENGTH": "explanation 为空或超过 400 字。",
    "STATEMENT_LENGTH": "有句子为空或超过 200 字。",
    "PRODUCT_NAMED": "definition 或 explanation 点名了具体产品。",
    "REF_UNKNOWN": "refs 中有不属于本概念 facts 的 slug。",
    "REF_MISSING": "有句子没有 refs。",
    "NUMBER_UNSUPPORTED": "有句子中的数字与单位在所引用的取值中找不到。",
    "NUMBER_UNMATCHED_REF": "有句子引用了不包含句中任何数字的取值。",
    "STATEMENT_COUNT": "statements 少于 1 句或多于 6 句。",
    "SUMMARY_INVALID": "输出不能组成合法的概念说明。",
}


@dataclass(frozen=True)
class Fact:
    """One entry's published value of the concept's field."""

    entity_id: str
    name: str
    group: str  # the display name of the entry's profile (its pack)
    state: str
    value: object  # None unless present
    slug: str
    digest: str  # the claim's member digest when read


@dataclass(frozen=True)
class ConceptInput:
    key: str
    title: str
    description: str  # the schema's description; may hold extraction instructions
    facts: tuple[Fact, ...]


@dataclass(frozen=True)
class StatementDraft:
    text: str
    refs: tuple[str, ...]


@dataclass(frozen=True)
class ConceptDraft:
    """One concept as the model wrote it, built only by parse_concepts and not yet checked."""

    key: str
    definition: str
    explanation: str
    statements: tuple[StatementDraft, ...]


class ConceptOutputError(ValueError):
    """The answer is not exactly the shape asked for; the whole batch is refused."""

    code = "CONCEPT_OUTPUT_INVALID"


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def concept_inputs(release: Release) -> list[ConceptInput]:
    """Every field two or more entries state, with each stating entry's value."""
    fields: dict[str, tuple[str, str]] = {}
    groups: list[tuple[set[str], str]] = []
    names: dict[str, tuple[str, set[str]]] = {}
    stated: dict[str, list[tuple[str, dict[str, object], str, str]]] = {}
    for member in release.members:
        payload = _dict(member.payload)
        if member.kind == "presentation_profile":
            labels = {_text(label) for label in _list(payload.get("classification_labels"))}
            groups.append((labels, _text(payload.get("display_name"))))
            for section in _list(payload.get("sections")):
                for field in _list(_dict(section).get("fields")):
                    field = _dict(field)
                    key = _text(field.get("field_key"))
                    if not key:
                        continue
                    title, description = fields.get(key, ("", ""))
                    fields[key] = (
                        title or _text(field.get("short_title")),
                        description or _text(field.get("description")),
                    )
        elif member.kind == "entity":
            entity_id = _text(payload.get("entity_id"))
            entity_names = [_text(name) for name in _list(payload.get("names"))]
            labels = {_text(label) for label in _list(payload.get("classification_labels"))}
            if entity_id:
                names[entity_id] = (next(filter(None, entity_names), entity_id), labels)
        elif member.kind == "claim" and payload.get("state") in STATED:
            predicate, subject = _text(payload.get("predicate")), _text(payload.get("subject_ref"))
            if predicate and subject:
                entry = (subject, payload, member.logical_slug, member.member_digest)
                stated.setdefault(predicate, []).append(entry)
    eligible = {
        key for key, claims in stated.items() if len({subject for subject, *_ in claims}) >= 2
    }
    ordered = [key for key in fields if key in eligible]
    ordered += sorted(eligible - set(ordered))

    def fact(subject: str, payload: dict[str, object], slug: str, digest: str) -> Fact:
        name, labels = names.get(subject, (subject, set()))
        group = next((display for wanted, display in groups if wanted & labels), "")
        state = _text(payload.get("state"))
        value = payload.get("value") if state == "present" else None
        return Fact(subject, name, group, state, value, slug, digest)

    return [
        ConceptInput(
            key=key,
            title=fields.get(key, ("", ""))[0] or key,
            description=fields.get(key, ("", ""))[1],
            facts=tuple(fact(*claim) for claim in stated[key]),
        )
        for key in ordered
    ]


def build_request(
    batch: Sequence[ConceptInput], problems: Mapping[str, Sequence[str]] | None = None
) -> tuple[str, str]:
    """(system, user) for one call; a retry passes the previous answer's problem codes."""
    concepts = []
    for concept in batch:
        item: dict[str, object] = {"key": concept.key, "title": concept.title}
        if concept.description:
            item["description"] = concept.description
        item["facts"] = [
            {
                "slug": fact.slug,
                "product": fact.name,
                "category": fact.group,
                "state": fact.state,
                "value": fact.value,
            }
            for fact in concept.facts
        ]
        concepts.append(item)
    user: dict[str, object] = {"concepts": concepts}
    if problems:
        user["previous_problems"] = {
            key: [PROBLEM_HINTS.get(code, code) for code in codes]
            for key, codes in problems.items()
        }
    return SYSTEM, json.dumps(user, ensure_ascii=False)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite number")


def _exact(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ConceptOutputError("unexpected object shape")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ConceptOutputError("expected a string")
    return value


def _statement(value: object) -> StatementDraft:
    item = _exact(value, {"text", "refs"})
    refs = item["refs"]
    if not isinstance(refs, list):
        raise ConceptOutputError("refs must be a list")
    return StatementDraft(_string(item["text"]), tuple(_string(ref) for ref in refs))


def parse_concepts(text: str, batch: Sequence[ConceptInput]) -> dict[str, ConceptDraft]:
    """One draft per concept of the batch, in batch order, or ConceptOutputError."""
    try:
        document = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (ValueError, RecursionError):
        raise ConceptOutputError("not one JSON object") from None
    items = _exact(document, {"concepts"})["concepts"]
    if not isinstance(items, list):
        raise ConceptOutputError("concepts must be a list")
    drafts: dict[str, ConceptDraft] = {}
    for value in items:
        item = _exact(value, {"key", "definition", "explanation", "statements"})
        key = _string(item["key"])
        statements = item["statements"]
        if key in drafts or not isinstance(statements, list):
            raise ConceptOutputError("repeated key or malformed statements")
        drafts[key] = ConceptDraft(
            key,
            _string(item["definition"]),
            _string(item["explanation"]),
            tuple(_statement(statement) for statement in statements),
        )
    wanted = [concept.key for concept in batch]
    if set(drafts) != set(wanted):
        raise ConceptOutputError("keys differ from the batch")
    return {key: drafts[key] for key in wanted}
