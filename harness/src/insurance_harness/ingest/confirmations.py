"""Questions for a person go to the platform as confirmation items; answers come back (S5b-3c-2).

One run reconciles what an earlier run left half done, pushes every material waiting for a person
(quarantined ones included, S11a),
settles the items a person answered and closes the items no longer asked. Closing is the commit
point: the platform checks under its lock that the answer is still the latest, and no answer can
follow. So a run first saves what it is about to do (the settlement), then closes, then executes
exactly what it saved; an interrupted run is completed from the settlement, never re-derived.
"""

from collections import Counter
from collections.abc import Callable, Iterable

from pydantic import BaseModel, ConfigDict, ValidationError

from insurance_harness.bundle.client import (
    MAX_CONFIRMATION_BYTES,
    MAX_CONFIRMATIONS,
    ConfirmationInput,
    ConfirmationItem,
    PlatformClient,
    PlatformError,
    confirmation_body,
)
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.identity.attribution import Attribution, Upload
from insurance_harness.identity.confirmation import ConfirmationError, conclude
from insurance_harness.ingest.confirmation_matching import (
    closed_as,
    content_of,
    same_answer,
    same_question,
    unsourced,
)
from insurance_harness.ingest.confirmation_questions import (
    SUBJECT_PREFIX,
    ConfirmationsError,
    ConfirmationWording,
    load_wording,
    question_of,
)
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    ConfirmationRef,
    PendingEntry,
    ProductRegistry,
    RegistryError,
    Settlement,
    head_of,
    record,
)
from insurance_harness.ingest.source_map import PageReader

# Re-exported: the wording and the questions belong to this command's public surface.
__all__ = [
    "ConfirmationReport",
    "ConfirmationRun",
    "ConfirmationWording",
    "ConfirmationsError",
    "load_wording",
    "question_of",
    "sync",
]
_ENVELOPE = len(b'{"items": []}')


class WithdrawnAnswer(BaseModel):
    """A person's answer on an item closed as obsolete that no recorded decision applied."""
    model_config = ConfigDict(extra="forbid")
    knowledge_id: str
    item_id: str
    answer_id: str
    option_key: str


class ConfirmationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pushed: list[str]
    applied: list[str]
    reopened: list[str]
    obsoleted: list[str]
    answers_withdrawn: list[WithdrawnAnswer] = []  # S5b-7 Spec §2.5
    waiting: int
    skipped: dict[str, int]


class ConfirmationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: ProductRegistry
    report: ConfirmationReport


def _source(entry: PendingEntry) -> RawSource:
    return RawSource(
        knowledge_id=entry.knowledge_id,
        parse_attempt=entry.parse_attempt,
        file_name=entry.file_name,
        sha256=entry.sha256,
    )


def _settlement(
    entry: PendingEntry,
    item: ConfirmationItem,
    ref: ConfirmationRef | None = None,
    conclusion: Attribution | None = None,
) -> Settlement:
    """A settlement for this material version and this item's question (Spec §3.5)."""
    return Settlement(
        item_id=item.id,
        knowledge_id=entry.knowledge_id,
        parse_attempt=entry.parse_attempt,
        sha256=entry.sha256,
        revision=item.revision,
        reason="applied" if ref is not None else "obsolete",
        confirmation=ref,
        conclusion=conclusion,
    )


def _applies(registry: ProductRegistry, conclusion: Attribution) -> bool:
    """The saved conclusion can still be recorded as it stands (Spec §2.2, review R2)."""
    product = registry.products.get(conclusion.product_id or "")
    if conclusion.outcome in {"CREATE", "NEW_VERSION"}:  # a new version adds a new entry (PV-1)
        return product is None
    if conclusion.outcome == "IGNORED" or (
        conclusion.outcome == "NEEDS_CONFIRM" and not conclusion.product_id
    ):
        return True
    if product is None:
        return False
    current = {m.knowledge_id for m in product.materials}
    return set(conclusion.replaces) <= current


def _batches(questions: list[ConfirmationInput]) -> list[list[ConfirmationInput]]:
    """Batches the platform accepts: at most 200 items and 512 KiB of body (review R8)."""
    batches: list[list[ConfirmationInput]] = []
    batch: list[ConfirmationInput] = []
    size = _ENVELOPE
    for question in questions:
        item = len(confirmation_body([question])) - _ENVELOPE  # its exact part of the body
        if batch and (len(batch) == MAX_CONFIRMATIONS or size + item + 2 > MAX_CONFIRMATION_BYTES):
            batches.append(batch)
            batch, size = [], _ENVELOPE
        batch.append(question)
        size += item + 2
    return [*batches, batch] if batch else batches


class _Sync:
    """One run's state: the registry so far, the platform, and what the report will say."""

    def __init__(
        self,
        registry: ProductRegistry,
        client: PlatformClient,
        pages: PageReader,
        write: bool,
        save: Callable[[ProductRegistry], None],
        wording: ConfirmationWording,
    ) -> None:
        self.current = registry.model_copy(deep=True)
        self.client, self.pages, self.write, self.save = client, pages, write, save
        self.wording = wording
        self.space = self.current.space_id
        self.pushed: set[str] = set()
        self.applied: set[str] = set()
        self.reopened: set[str] = set()
        self.obsoleted: set[str] = set()
        self.skipped: Counter[str] = Counter()
        self.unaskable: dict[str, str] = {}  # knowledge id -> why its question cannot be built
        self.handled: set[str] = set()  # items closed (in a dry run: taken as closed) in this run
        # One page read per material per run: its opening, or the code of the failed read.
        self.heads: dict[tuple[str, int], tuple[str | None, str]] = {}

    # The registry ---------------------------------------------------------------------------

    def waiting(self) -> list[PendingEntry]:
        """Materials waiting for a person: NEEDS_CONFIRM, and quarantined ones (S11a Spec §2.1)."""
        return sorted(self.current.pending, key=lambda p: p.knowledge_id)

    def mark(self, entry: PendingEntry, settlement: Settlement | None) -> PendingEntry:
        """Save the entry with this settlement (or without one) in place of the current one."""
        marked = entry.model_copy(update={"settlement": settlement})
        self.current.pending = [
            marked if p.knowledge_id == entry.knowledge_id else p for p in self.current.pending
        ]
        self.persist()
        return marked

    def persist(self) -> None:
        if self.write:
            self.save(self.current)

    def questions(
        self, entries: Iterable[PendingEntry]
    ) -> list[tuple[PendingEntry, ConfirmationInput]]:
        asked = []
        for entry in entries:
            try:
                head = self.head(entry)
                if head is None:
                    continue  # not asked this run; an item already asked stays open
                asked.append((entry, question_of(entry, self.current, self.wording, head=head)))
            except ConfirmationsError as error:
                self.unaskable[entry.knowledge_id] = error.code
        return asked

    def head(self, entry: PendingEntry) -> str | None:
        """The text of the material's first pages, read once per run (S5b-3d-1).

        A failed read makes the material unaskable for this run: nothing is pushed for it and its
        open item is kept, since a question worded differently would close an answered item.
        """
        key = (entry.knowledge_id, entry.parse_attempt)
        if key not in self.heads:
            try:
                self.heads[key] = (head_of(self.pages, self.space, _source(entry)), "")
            except SourcePagesError as error:
                self.heads[key] = (None, error.code)
        head, code = self.heads[key]
        if head is None:
            self.unaskable[entry.knowledge_id] = code
        return head

    # Settling one answered item ---------------------------------------------------------------

    def settle(self, entry: PendingEntry, item: ConfirmationItem) -> None:
        """Decide, save the settlement, close, execute (Spec §2.2)."""
        answer = item.answer
        assert answer is not None
        source = _source(entry)
        head = self.head(entry)
        if head is None:
            return  # counted once for the material, retried next run
        upload = Upload(
            knowledge_id=source.knowledge_id,
            file_name=source.file_name,
            sha256=source.sha256,
            head=head,
        )
        try:
            conclusion = conclude(
                entry.attribution, answer.option_key, upload, self.current.registered()
            )
        except ConfirmationError:  # the registry has changed since the question (Spec §2.3)
            self.commit(entry, _settlement(entry, item))
            return
        try:
            ref = ConfirmationRef(
                item_id=item.id,
                answer_id=answer.id,
                option_key=answer.option_key,
                answerer=answer.answerer,
            )
            record(self.current.model_copy(deep=True), source, conclusion, ref)  # it would apply
        except ValidationError:
            self.skipped["ANSWER_INVALID"] += 1
            return
        except RegistryError as error:
            self.skipped[error.code] += 1
            return
        self.commit(entry, _settlement(entry, item, ref, conclusion))

    def commit(self, entry: PendingEntry, settlement: Settlement) -> None:
        marked = self.mark(entry, settlement)
        if self.write:
            answer = settlement.confirmation.answer_id if settlement.confirmation else None
            try:
                self.client.close_confirmation(
                    self.space, settlement.item_id, settlement.reason, answer
                )
            except PlatformError as error:
                if error.code == "ANSWER_STALE":
                    self.mark(marked, None)
                    self.skipped[error.code] += 1
                    return
                if error.code != "CONFIRMATION_CLOSED":
                    raise  # the settlement stays: the next run reconciles it
                closed = self.find(settlement.item_id, "closed")
                # As in reconcile: the item's identity first, then how it was closed.
                if closed is not None and not same_question(closed, marked, settlement):
                    self.skipped["SETTLEMENT_MISMATCH"] += 1  # kept: never cleared by another item
                    return
                if (
                    closed is None
                    or closed.closure is None
                    or not closed_as(closed.closure, settlement)
                ):
                    self.mark(marked, None)
                    self.skipped[error.code] += 1
                    return
                if not same_answer(closed, settlement):
                    self.skipped["SETTLEMENT_MISMATCH"] += 1
                    return
        self.execute(marked, settlement)

    def execute(self, entry: PendingEntry, settlement: Settlement) -> None:
        """Do what the settlement says: record its conclusion, or set the material aside."""
        self.handled.add(settlement.item_id)
        if settlement.reason == "obsolete":
            self.current.pending = [
                p for p in self.current.pending if p.knowledge_id != entry.knowledge_id
            ]
            self.reopened.add(entry.knowledge_id)
            self.persist()
            return
        conclusion, ref = settlement.conclusion, settlement.confirmation
        assert conclusion is not None and ref is not None
        if not _applies(self.current, conclusion):
            self.skipped["CONFIRMATION_CONFLICT"] += 1  # never re-derived: kept for a person
            return
        try:
            record(self.current, _source(entry), conclusion, ref)
        except RegistryError as error:
            self.skipped[error.code] += 1
            return
        self.applied.add(entry.knowledge_id)
        self.persist()

    def recordable(self, entry: PendingEntry, settlement: Settlement) -> bool:
        """An applied settlement's conclusion can still be recorded as it stands (review R10)."""
        conclusion, ref = settlement.conclusion, settlement.confirmation
        if conclusion is None or ref is None:
            return True
        if not _applies(self.current, conclusion):
            return False
        try:
            record(self.current.model_copy(deep=True), _source(entry), conclusion, ref)
        except RegistryError:
            return False
        return True

    def find(self, item_id: str, status: str) -> ConfirmationItem | None:
        listed = self.client.confirmations(self.space, "closed" if status == "closed" else "open")
        return next((item for item in listed if item.id == item_id), None)

    # The run's steps --------------------------------------------------------------------------

    def reconcile(self, listed: list[ConfirmationItem]) -> None:
        """Complete or drop the settlements an earlier run left (Spec §2.2)."""
        by_id = {item.id: item for item in listed}
        for entry in self.waiting():
            settlement = entry.settlement
            if settlement is None:
                continue
            item = by_id.get(settlement.item_id)
            if item is None:
                self.mark(entry, None)
                self.skipped["CONFIRMATION_NOT_FOUND"] += 1
            elif not same_question(item, entry, settlement):
                self.skipped["SETTLEMENT_MISMATCH"] += 1  # kept: never executed on another item
            elif item.closure is not None:
                if not closed_as(item.closure, settlement):
                    self.mark(entry, None)
                    self.skipped["CONFIRMATION_CLOSED"] += 1
                elif not same_answer(item, settlement):
                    self.skipped["SETTLEMENT_MISMATCH"] += 1
                else:
                    self.execute(entry, settlement)
            elif settlement.confirmation is not None and (
                item.answer is None or item.answer.id != settlement.confirmation.answer_id
            ):
                self.mark(entry, None)  # a newer answer: settled afresh below
            elif not same_answer(item, settlement):
                self.skipped["SETTLEMENT_MISMATCH"] += 1
            elif not self.recordable(entry, settlement):
                self.skipped["CONFIRMATION_CONFLICT"] += 1  # still open: a person can answer again
            else:
                self.commit(entry, settlement)

    def ask(self, listed: list[ConfirmationItem]) -> None:
        """Push the questions, settle answered ones, and push the questions settling raises."""
        asked: set[tuple[object, ...]] = set()
        for _ in range(8):  # each round asks only new questions; a choice raises at most a few
            fresh = [
                (entry, question)
                for entry, question in self.questions(self.waiting())
                if entry.settlement is None and content_of(question) not in asked
            ]
            if not fresh:
                break
            asked.update(content_of(question) for _, question in fresh)
            self.pushed.update(entry.knowledge_id for entry, _ in fresh)
            stored = self.stored([question for _, question in fresh], listed)
            for (entry, _), item in zip(fresh, stored, strict=True):
                if item is None or item.id in self.handled:
                    continue
                if item.closure is not None:
                    self.skipped["CONFIRMATION_CLOSED"] += 1
                elif item.answer is not None:
                    self.settle(entry, item)

    def stored(
        self, questions: list[ConfirmationInput], listed: list[ConfirmationItem]
    ) -> list[ConfirmationItem | None]:
        """The platform item of each question. An open item asked before questions carried their
        source reference is the same question: kept as it is, not asked again (Spec §2.4)."""
        earlier = {unsourced(i): i for i in listed if i.closure is None and not i.source_ref}
        kept = [earlier.get(unsourced(question)) for question in questions]
        rest = [question for question, item in zip(questions, kept, strict=True) if item is None]
        if not self.write:  # a dry run finds what the platform would return, open or closed
            existing = {content_of(item): item for item in listed}
            found: list[ConfirmationItem | None] = [existing.get(content_of(q)) for q in rest]
        else:
            found = []
            for batch in _batches(rest):
                found.extend(self.client.submit_confirmations(self.space, batch))
        sent = iter(found)
        return [item if item is not None else next(sent) for item in kept]

    def clean(self, listed: list[ConfirmationItem]) -> None:
        """Close the material items no longer asked; keep those whose question cannot be built."""
        waiting = {entry.knowledge_id: entry for entry in self.waiting()}
        asked = [question for _, question in self.questions(waiting.values())]
        wanted = {content_of(question) for question in asked}
        same = {unsourced(question) for question in asked}  # asked before S5b-3d-2b (Spec §2.4)
        if self.write:
            open_items = self.client.confirmations(self.space, "open")
        else:
            open_items = [item for item in listed if item.closure is None]
        for item in open_items:
            if not item.subject.startswith(SUBJECT_PREFIX) or item.id in self.handled:
                continue
            kid = item.subject.removeprefix(SUBJECT_PREFIX)
            entry = waiting.get(kid)
            if entry is not None and (kid in self.unaskable or entry.settlement is not None):
                continue
            if content_of(item) in wanted or (not item.source_ref and unsourced(item) in same):
                continue
            if self.write:
                try:
                    self.client.close_confirmation(self.space, item.id, "obsolete")
                except PlatformError as error:
                    if error.code != "CONFIRMATION_CLOSED":
                        raise
                    self.skipped[error.code] += 1
                    continue
            self.handled.add(item.id)
            self.obsoleted.add(kid)

    def withdrawn(self, listed: list[ConfirmationItem]) -> list[WithdrawnAnswer]:
        """Answers on items closed as obsolete that no recorded decision applied (S5b-7 §2.5).

        Read from the platform's closed items, not from this run's memory: an answer is reported
        even when a close receipt was lost (by the next run) or it came between listing and closing.
        """
        if self.write:
            closed = self.client.confirmations(self.space, "closed")
        else:  # a dry run takes the items it would close as closed obsolete
            closed = [i for i in listed if i.closure is not None or i.id in self.handled]
        applied = {d.knowledge_id for d in self.current.decisions if d.confirmation}
        found = []
        for item in closed:
            kid = item.subject.removeprefix(SUBJECT_PREFIX)
            if (
                item.answer is None
                or not item.subject.startswith(SUBJECT_PREFIX)
                or (item.closure is not None and item.closure.reason != "obsolete")
                or kid in applied
            ):
                continue
            answer = item.answer
            found.append(WithdrawnAnswer(
                knowledge_id=kid, item_id=item.id, answer_id=answer.id, option_key=answer.option_key
            ))
        return sorted(found, key=lambda w: (w.knowledge_id, w.item_id))

    def report(self, withdrawn: list[WithdrawnAnswer]) -> ConfirmationReport:
        return ConfirmationReport(
            pushed=sorted(self.pushed),
            applied=sorted(self.applied),
            reopened=sorted(self.reopened),
            obsoleted=sorted(self.obsoleted),
            answers_withdrawn=withdrawn,
            waiting=len(self.waiting()),
            skipped=dict(sorted((self.skipped + Counter(self.unaskable.values())).items())),
        )


def sync(
    registry: ProductRegistry,
    client: PlatformClient,
    pages: PageReader,
    *,
    write: bool,
    save: Callable[[ProductRegistry], None],
    wording: ConfirmationWording | None = None,
) -> ConfirmationRun:
    """One run (Spec §3.3); the given registry is not modified."""
    run = _Sync(registry, client, pages, write, save, wording or load_wording())
    listed = [*client.confirmations(run.space, "open"), *client.confirmations(run.space, "closed")]
    run.reconcile(listed)
    run.ask(listed)
    run.clean(listed)
    return ConfirmationRun(registry=run.current, report=run.report(run.withdrawn(listed)))
