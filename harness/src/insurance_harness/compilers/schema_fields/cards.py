"""Field cards: each field's boundary and three-state rule as versioned data (S4d Spec §3.4).

Cards are keyed by field_key and shared across packs; the per-pack wording of a field stays
in its FieldDefinition. Examples come from held-out products reviewed by an independent
judge, and a request only carries examples of its own pack, because the same field is
asked for differently by different insurance types.
"""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, cast

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition

_RULES = (
    "title",
    "definition",
    "includes",
    "excludes",
    "absent_rule",
    "unknown_rule",
    "good",
    "bad",
)


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    data = json.loads(files(__package__).joinpath("field_cards.json").read_text(encoding="utf-8"))
    if not isinstance(data.get("version"), str) or not isinstance(data.get("cards"), dict):
        raise ValueError("field_cards.json lacks a version or cards")
    return cast(dict[str, Any], data)


def cards_version() -> str:
    return str(_data()["version"])


def all_cards() -> dict[str, dict[str, Any]]:
    return dict(_data()["cards"])


# Examples teach step one which segments belong to a field; a long value adds little to
# that and invites copying, so it is cut. Step two writes values from selected text only.
EXAMPLE_VALUE_CHARS = 300


def card_payload(
    definition: FieldDefinition, *, examples: bool = True, entity_id: str | None = None
) -> dict[str, Any] | None:
    """What a request carries for one field: the rules, plus same-pack examples for step one.

    With examples=False (the value step) only the rules are sent: no examples and no generic
    illustration, so the value can only come from the segments in the request. Examples taken
    from the product being compiled (entity_id) are never sent: they would hand it the answers
    (S4h). The example's product_id only drives that exclusion and is not sent.
    """
    card = _data()["cards"].get(definition.field_key)
    if card is None:
        return None
    rules = _RULES if examples else tuple(key for key in _RULES if key != "good")
    payload: dict[str, Any] = {key: card[key] for key in rules if card.get(key)}
    payload["excludes"] = [f"{content}（归入 {target}）" for content, target in card["excludes"]]
    if not examples:
        # S12c-9: a writing rule says what the value leaves out of a passage it still uses. It
        # reaches step two only, so step one keeps selecting the passage (S12c-5: tightening a
        # card's selection rules on long mixed passages dropped the field's own evidence).
        if card.get("writing_rule"):
            payload["writing_rule"] = card["writing_rule"]
        return payload
    same_pack = [
        {
            key: _clip(example[key]) if key == "value" else example[key]
            for key in ("schema_pack_id", "product", "state", "value", "reason", "pitfalls")
            if example.get(key)
        }
        for example in card.get("examples", [])
        if example["schema_pack_id"] == definition.pack_id and example["product_id"] != entity_id
    ]
    if same_pack:
        payload["examples"] = same_pack
    return payload


def _clip(value: str) -> str:
    return (
        value
        if len(value) <= EXAMPLE_VALUE_CHARS
        else value[:EXAMPLE_VALUE_CHARS] + "……（示例截断）"
    )
