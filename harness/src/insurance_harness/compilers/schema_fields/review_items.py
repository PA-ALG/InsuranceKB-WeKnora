"""What the independent reviewer sees of one schema-field compile output (RV2a Spec §3.2).

Only fields with content are reviewed: present and absent_explicitly state something the source
must support. Unknown fields publish no fact and are skipped. Each item carries the field's
definition and its card rules without examples: examples name other products and their answers,
and the review must judge this value against its own quotes only.
"""

import json
from collections.abc import Mapping

from insurance_harness.compilers.schema_fields.cards import card_payload
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.review.scorer import ReviewItem


def logical_key(entity_id: str, field_key: str) -> str:
    """One field of one entity; the claim and its review score share this key."""
    return f"{entity_id}/{field_key}"


def review_items(
    output: CompileOutput, definitions: Mapping[str, FieldDefinition]
) -> list[ReviewItem]:
    """One item per field with content, in output order; a field without a definition stops."""
    items: list[ReviewItem] = []
    for field in output.fields:
        if field.state == "unknown":
            continue
        definition = definitions.get(field.field_key)
        if definition is None:
            raise ValueError("DEFINITION_MISSING")
        items.append(
            ReviewItem(
                logical_key=logical_key(output.entity_id, field.field_key),
                title=definition.short_title,
                rules=_rules(definition),
                state=field.state,
                value=field.value if field.state == "present" else None,
                quotes=tuple(quote.quote for quote in field.evidence),
            )
        )
    return items


def _rules(definition: FieldDefinition) -> str:
    """Stable JSON text: the definition's wording plus the card rules, never examples."""
    rules: dict[str, object] = {
        name: value
        for name, value in (
            ("short_title", definition.short_title),
            ("description", definition.description),
            ("value_spec", definition.value_spec),
            ("source_guidance", definition.source_guidance),
        )
        if value
    }
    card = card_payload(definition, examples=False)
    if card:
        rules["card"] = card
    return json.dumps(rules, ensure_ascii=False, sort_keys=True)
