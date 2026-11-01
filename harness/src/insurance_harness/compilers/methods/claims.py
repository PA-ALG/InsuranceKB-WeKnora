"""A method's Claims and entity from a checked answer (Spec §4.3, §4.4).

One Claim per card, keyed `<method_id>/<predicate>` and never tied to a product version (SK-0 §7).
Each item is checked on its own against the method's paragraphs and dropped with a code when it
fails, so a value only ever holds items with their own evidence. A list value and its evidence are
aligned position by position (`evidence[i]` supports `value[i]`): the contract keeps a list of
strings and a list of evidence, and the sales-method list predicates add the convention that both
have one entry per item (SK-0 §2.1, read the same way by SK-3). Every quote is cut from the original
page, so it equals its page slice by construction.
"""

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from insurance_harness.bundle.assemble import ACCESS_SCOPE, BundleError
from insurance_harness.catalog.method_cards import MethodCard, MethodCards
from insurance_harness.compilers.methods.paragraphs import MethodParagraphs
from insurance_harness.compilers.methods.parse import AnswerItem, MethodResponse
from insurance_harness.compilers.methods.product_info import NOTICE, product_signals
from insurance_harness.compilers.methods.prompt import METHOD_PROTOCOL_VERSION
from insurance_harness.contracts.enums import ClaimState, EvidenceMatch, SourceClass, UnknownReason
from insurance_harness.contracts.knowledge import Claim, Entity, Evidence, Provenance
from insurance_harness.identity.text import fold
from insurance_harness.ingest.method_registry import MethodEntry

COMPILER = "sales_methods"


def compiler_version(cards: MethodCards) -> str:
    return f"{cards.version}+method:{METHOD_PROTOCOL_VERSION}"


@dataclass(frozen=True)
class MethodContent:
    claims: tuple[Claim, ...]
    labels: tuple[str, ...]  # the answer's labels that passed
    dropped: dict[str, int]  # items and labels dropped, by code
    signals: dict[str, frozenset[str]]  # product signals of each Claim that shows any


def _item(item: AnswerItem, card: MethodCard, paragraphs: MethodParagraphs) -> list[Evidence] | str:
    """The evidence of one item, or why it is dropped (Spec §4.3)."""
    resolved = paragraphs.resolve(item.refs)
    if isinstance(resolved, str):
        return resolved
    material, spans = resolved
    if card.value_type == "list" and len(spans) != 1:
        return "ITEM_SPANS_MULTIPLE"
    if card.verbatim and not all(fold(item.text) in fold(span.quote) for span in spans):
        return "PHRASE_NOT_VERBATIM"
    return [
        Evidence(
            source_ref=material.revision.ref(span.document_sha256.lower()),
            file_sha256=span.document_sha256.lower(),
            locator=material.source.locator(span),
            quote=span.quote,
            match=EvidenceMatch.EXACT,
            access_scope=ACCESS_SCOPE,
        )
        for span in spans
    ]


def _claim(
    method_id: str,
    card: MethodCard,
    kept: Sequence[tuple[str, list[Evidence]]],
    reason: UnknownReason | None,
    cards: MethodCards,
    model: str,
) -> Claim:
    key = f"{method_id}/{card.predicate}"
    value: str | list[str] | None
    evidence: list[Evidence]
    if not kept:
        value, evidence = None, []
    elif card.value_type == "text":
        value, evidence = kept[0][0], kept[0][1]
    else:
        value, evidence = [text for text, _ in kept], [found[0] for _, found in kept]
    try:
        return Claim(
            claim_id=key,
            logical_key=key,
            subject_ref=method_id,
            product_version_ref=None,
            predicate=card.predicate,
            state=ClaimState.PRESENT if kept else ClaimState.UNKNOWN,
            value=value,
            evidence=evidence,
            provenance=Provenance(
                compiler=COMPILER, compiler_version=compiler_version(cards), model=model
            ),
            origin=SourceClass.SOURCE_SUPPORTED,
            unknown_reason=None if kept else reason,
        )
    except ValidationError:
        raise BundleError("CLAIM_INVALID") from None


def method_content(
    method_id: str,
    response: MethodResponse,
    paragraphs: MethodParagraphs,
    cards: MethodCards,
    offered: Collection[str],
    product_names: Sequence[str],
    model: str,
) -> MethodContent:
    dropped: Counter[str] = Counter()
    claims = []
    for card, row in zip(cards.cards, response.predicates, strict=True):
        kept: list[tuple[str, list[Evidence]]] = []
        for item in row.items:
            outcome = _item(item, card, paragraphs)
            if isinstance(outcome, str):
                dropped[outcome] += 1
            else:
                kept.append((item.text.strip(), outcome))
        # Answered unknown: nothing in the paragraphs; answered but every item dropped: failed.
        unknown = row.state == "unknown"
        reason = UnknownReason.NOT_IN_MATERIAL if unknown else UnknownReason.EXTRACTION_FAILED
        claims.append(_claim(method_id, card, kept, reason, cards, model))
    labels: list[str] = []
    for answer in response.labels:
        if answer.label not in offered or not paragraphs.known(answer.refs):
            dropped["LABEL_INVALID"] += 1
        elif answer.label not in labels:
            labels.append(answer.label)
    signals = {}
    for claim in claims:
        texts = claim.value if isinstance(claim.value, list) else [claim.value]
        found = frozenset(
            signal
            for text in texts
            if isinstance(text, str)
            for signal in product_signals(text, cards, product_names)
        )
        if found:
            signals[claim.logical_key] = found
    return MethodContent(
        tuple(claims), tuple(sorted(labels)), dict(sorted(dropped.items())), signals
    )


def method_entity(
    method: MethodEntry, categories: Collection[str], content: MethodContent, cards: MethodCards
) -> Entity:
    """The method's entity: its names, applicability labels and the product-information flag."""
    canonical = method.names[0]
    others = {*method.names[1:], *method.aliases} - {canonical}
    return Entity(
        entity_id=method.method_id,
        entity_type=cards.entity_type,
        names=[canonical],
        aliases=sorted(others),
        identifiers=dict(NOTICE) if content.signals else {},
        classification_labels=sorted({*categories, *content.labels}),
        owner_module=cards.owner_module,
    )
