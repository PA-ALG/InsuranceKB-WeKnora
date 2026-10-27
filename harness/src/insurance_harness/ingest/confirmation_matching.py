"""How a platform confirmation item is recognised as a question or a settlement (S5b-3c-2).

The platform keeps one item per (subject, revision, content); a run compares what it asks, and what
an earlier run saved, with the items the platform lists. Since S5b-3d-2b the content includes the
material's source reference, which items asked before then lack.
"""

from insurance_harness.bundle.client import ConfirmationClosure, ConfirmationInput, ConfirmationItem
from insurance_harness.ingest.confirmation_questions import SUBJECT_PREFIX
from insurance_harness.ingest.registry import PendingEntry, Settlement


def content_of(item: ConfirmationInput | ConfirmationItem) -> tuple[object, ...]:
    """What the platform's content identity covers: the question and its source reference."""
    return (*unsourced(item), item.source_ref or "")


def unsourced(item: ConfirmationInput | ConfirmationItem) -> tuple[object, ...]:
    """The question without its source reference, which items asked before S5b-3d-2b lack."""
    options = tuple((o.key, o.label) for o in item.options)
    return (item.subject, item.revision, item.title, item.detail, options)


def closed_as(closure: ConfirmationClosure, settlement: Settlement) -> bool:
    """The item was closed the way the settlement says: reason and applied answer."""
    answer = settlement.confirmation.answer_id if settlement.confirmation else None
    return (closure.reason, closure.answer_id or None) == (settlement.reason, answer)


def same_question(item: ConfirmationItem, entry: PendingEntry, settlement: Settlement) -> bool:
    return (item.subject, item.revision) == (
        SUBJECT_PREFIX + entry.knowledge_id,
        settlement.revision,
    )


def same_answer(item: ConfirmationItem, settlement: Settlement) -> bool:
    """The item's answer is the settlement's in full: id, choice and answerer (review R5)."""
    ref = settlement.confirmation
    if ref is None:
        return True
    answer = item.answer
    return answer is not None and (answer.id, answer.option_key, answer.answerer) == (
        ref.answer_id,
        ref.option_key,
        ref.answerer,
    )
