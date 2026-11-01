"""Which questions asked under an older policy a person can no longer answer (S5b-9 Spec §2).

`uploads run` keeps such a question as it was asked while a person may be answering it (S5b-7).
That is only true while its item is open. Once every item asked for the material's current revision
is closed as obsolete — its answer withdrawn, nothing applied — nothing is left to protect, and the
run judges the material again under the current policy. The state is read from the platform's
items, the same record S5b-7 reads withdrawn answers from; when they cannot be read the questions
are kept and named as unknown, never guessed.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from insurance_harness.bundle.client import ConfirmationItem, PlatformClient, PlatformError
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.confirmation_questions import SUBJECT_PREFIX
from insurance_harness.ingest.registry import PendingEntry, ProductRegistry


@dataclass(frozen=True)
class QuestionStates:
    withdrawn: frozenset[str]  # knowledge ids whose question was withdrawn: judged again
    unknown: frozenset[str]  # knowledge ids kept because the platform could not be read


def older_questions(registry: ProductRegistry, policy_ref: str) -> list[PendingEntry]:
    """Questions to a person asked under another policy and not being settled: the ones a run
    would otherwise keep as asked (S5b-7 Spec §2.4)."""
    return [
        p
        for p in registry.pending
        if p.attribution.outcome == "NEEDS_CONFIRM"
        and p.settlement is None
        and p.attribution.policy_ref != policy_ref
    ]


def read_question_states(
    client: PlatformClient, registry: ProductRegistry, policy_ref: str
) -> QuestionStates:
    """The platform is read only when an older question waits (Spec §2.3)."""
    entries = older_questions(registry, policy_ref)
    if not entries:
        return QuestionStates(frozenset(), frozenset())
    try:
        items = [
            *client.confirmations(registry.space_id, "open"),
            *client.confirmations(registry.space_id, "closed"),
        ]
    except PlatformError:  # fail closed: every question stays as it was asked
        return QuestionStates(frozenset(), frozenset(e.knowledge_id for e in entries))
    return QuestionStates(_withdrawn(entries, items), frozenset())


def _withdrawn(
    entries: Sequence[PendingEntry], items: Sequence[ConfirmationItem]
) -> frozenset[str]:
    found = set()
    for entry in entries:
        ref = SourceRevision(entry.knowledge_id, entry.parse_attempt).ref(entry.sha256)
        own = [
            item
            for item in items
            if item.subject == SUBJECT_PREFIX + entry.knowledge_id
            and item.source_ref in {ref, ""}  # an item asked before S5b-3d-2b carries none
        ]
        if own and all(i.closure is not None and i.closure.reason == "obsolete" for i in own):
            found.add(entry.knowledge_id)  # never asked at this revision, or still open: kept
    return frozenset(found)
