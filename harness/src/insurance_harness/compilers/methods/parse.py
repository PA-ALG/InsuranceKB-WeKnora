"""The method value answer, checked for its shape before any value is used (Spec §4.2).

The answer is untrusted model output. Only its structure is checked here: one row per card in the
cards' order, a text card with exactly one item, items only when present. Whether each item's
paragraphs exist and support it is checked item by item later (claims.py), so one bad item costs
only itself, while a malformed answer costs the whole method and nothing else.
"""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from insurance_harness.catalog.method_cards import MethodCards

_Text = Annotated[str, StringConstraints(pattern=r"\S")]


class MethodResponseError(ValueError):
    def __init__(self) -> None:
        self.code = "VALUE_RESPONSE_INVALID"
        super().__init__(self.code)


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class AnswerItem(_Strict):
    text: _Text
    refs: tuple[str, ...] = Field(min_length=1)


class PredicateAnswer(_Strict):
    predicate: str
    state: Literal["present", "unknown"]
    items: tuple[AnswerItem, ...] = ()


class LabelAnswer(_Strict):
    label: str
    refs: tuple[str, ...] = Field(min_length=1)


class MethodResponse(_Strict):
    predicates: tuple[PredicateAnswer, ...]
    labels: tuple[LabelAnswer, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_method_response(raw: str, cards: MethodCards) -> MethodResponse:
    try:
        json.loads(raw, object_pairs_hook=_unique_object)
        response = MethodResponse.model_validate_json(raw)
    except (ValueError, ValidationError, RecursionError):
        raise MethodResponseError() from None
    if [row.predicate for row in response.predicates] != [card.predicate for card in cards.cards]:
        raise MethodResponseError()
    for row, card in zip(response.predicates, cards.cards, strict=True):
        if (row.state == "present") != bool(row.items):
            raise MethodResponseError()
        if card.value_type == "text" and len(row.items) > 1:
            raise MethodResponseError()
    return response
