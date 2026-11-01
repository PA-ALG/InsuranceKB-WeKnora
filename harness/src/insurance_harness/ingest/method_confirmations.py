"""The scope-label question of a method use, and how its answer is applied (SK-1 Spec §4).

The machine labels every method use whose blocks hit a label; the question is asked only for one
that hit none, or whose labels a person asked to correct (`request_relabel`). It is asked under its
own subject (`method:<knowledge id>`), apart from the product questions (`material:`), whose run
never touches these items. The page offers one choice per answer, so several labels are chosen one
at a time: each answer adds or removes one label and the next question follows at once, until the
person answers "done" or ignores the material. The revision covers the source revision, the
evidence, the labels in force and the last answer, so every step is a new question and an answer to
an older one is stale. As for product questions, closing is the commit point: a run saves what it
is about to do (the settlement) on the record, closes the item, then executes exactly what it saved;
an interrupted run completes it from the settlement.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from insurance_harness.bundle.client import (
    ConfirmationInput,
    ConfirmationItem,
    ConfirmationOption,
    PlatformClient,
    PlatformError,
)
from insurance_harness.catalog.sales_taxonomy import SalesTaxonomy, load_sales_taxonomy
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.identity.attribution import Attribution, load_attribution_policy
from insurance_harness.ingest.confirmation_matching import content_of
from insurance_harness.ingest.confirmation_questions import (
    ConfirmationsError,
    confirmation_batches,
    trim,
)
from insurance_harness.ingest.method_use_model import (
    LIVE,
    METHOD_ROLE,
    MethodUse,
    ScopeAnswer,
    ScopeSettlement,
    check_method_uses,
)
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    ConfirmationRef,
    ProductRegistry,
    RegistryError,
    record,
)

SUBJECT_PREFIX = "method:"
_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")  # the platform's (S5b-3a)
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")
_LIMITS = {"title": 200, "detail": 2000, "label": 200}
_KINDS = ("add", "remove", "done", "ignore")


def _every_label(taxonomy: SalesTaxonomy) -> tuple[str, ...]:
    return (*taxonomy.insurance_labels(), taxonomy.general.label)


class MethodWording(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    title: str
    detail: str
    no_hits: str
    no_labels: str
    ignore_method_only: str
    ignore_dual: str
    options: dict[str, str]
    labels: dict[str, str]

    @model_validator(mode="after")
    def _complete(self) -> "MethodWording":
        labels = set(_every_label(load_sales_taxonomy()))
        if set(self.options) != set(_KINDS) or set(self.labels) != labels:
            raise ValueError("the wording must cover every choice kind and scope label")
        return self


@lru_cache(maxsize=1)
def load_method_wording() -> MethodWording:
    try:
        text = files(__package__).joinpath("method_wording.json").read_text(encoding="utf-8")
        return MethodWording.model_validate_json(text)
    except (OSError, ValidationError):
        raise ConfirmationsError("WORDING_INVALID") from None


@dataclass(frozen=True)
class ScopeChoice:
    key: str
    kind: str
    label: str | None  # the label added or removed
    labels: tuple[str, ...]  # the labels after the answer; empty for ignoring
    editing: bool  # another question follows


def method_choices(
    use: MethodUse, taxonomy: SalesTaxonomy | None = None
) -> tuple[ScopeChoice, ...]:
    """One step of choosing labels, in a fixed order: add each label not in force, remove one of
    several in force (the last one is replaced by adding another first), done, ignore (§4.1)."""
    taxonomy = taxonomy or load_sales_taxonomy()
    current = use.categories
    offered = [
        ScopeChoice(f"add:{label}", "add", label, tuple(sorted({*current, label})), True)
        for label in _every_label(taxonomy)
        if label not in current
    ]
    if len(current) > 1:
        for label in current:
            rest = tuple(other for other in current if other != label)
            offered.append(ScopeChoice(f"remove:{label}", "remove", label, rest, True))
    if current:
        offered.append(ScopeChoice("done", "done", None, current, False))
    offered.append(ScopeChoice("ignore", "ignore", None, (), False))
    return tuple(offered)


def _fill(template: str, limit: int, values: dict[str, str]) -> str:
    try:
        text = trim(template.format(**values))
    except (KeyError, IndexError, ValueError):
        raise ConfirmationsError("WORDING_INVALID") from None
    if not text or len(text) > limit or _CONTROL.search(text):
        raise ConfirmationsError("WORDING_INVALID")
    return text


def method_question(
    use: MethodUse,
    wording: MethodWording | None = None,
    *,
    taxonomy: SalesTaxonomy | None = None,
    method_only: bool = True,
) -> ConfirmationInput:
    """The confirmation item for one step of a method use's labels (Spec §4.1)."""
    wording = wording or load_method_wording()
    subject = SUBJECT_PREFIX + use.knowledge_id
    if not _SUBJECT.fullmatch(subject) or not use.asked:
        raise ConfirmationsError("QUESTION_INVALID")
    identity = {
        "triple": list(use.triple),
        "evidence": use.evidence_digest,
        "taxonomy": use.taxonomy_version,
        "wording": wording.version,
        "method_only": method_only,
        "labels": list(use.categories),
        "after": use.confirmation.answer_id if use.confirmation is not None else None,
    }
    canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def shown(labels: tuple[str, ...], empty: str) -> str:
        return "、".join(wording.labels.get(label, label) for label in labels) or empty

    facts = {
        "file": use.file_name,
        "signals": "、".join(use.signals),
        "hits": shown(tuple(hit.label for hit in use.label_hits), wording.no_hits),
        "labels": shown(use.categories, wording.no_labels),
        "ignore_note": wording.ignore_method_only if method_only else wording.ignore_dual,
    }
    options = []
    for choice in method_choices(use, taxonomy):
        values = facts | {"label": shown((choice.label,), "") if choice.label else ""}
        options.append(
            ConfirmationOption(
                key=choice.key,
                label=_fill(wording.options[choice.kind], _LIMITS["label"], values),
            )
        )
    return ConfirmationInput(
        subject=subject,
        revision=hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32],
        title=_fill(wording.title, _LIMITS["title"], facts),
        detail=_fill(wording.detail, _LIMITS["detail"], facts),
        options=options,
        source_ref=SourceRevision(use.knowledge_id, use.parse_attempt).ref(use.sha256),
    )


class MethodConfirmationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pushed: list[str]
    applied: list[str]
    obsoleted: list[str]
    waiting: int
    skipped: dict[str, int]


class MethodConfirmationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: ProductRegistry
    report: MethodConfirmationReport


class _MethodSync:
    def __init__(
        self,
        registry: ProductRegistry,
        client: PlatformClient,
        write: bool,
        save: Callable[[ProductRegistry], None],
        wording: MethodWording,
        taxonomy: SalesTaxonomy,
    ) -> None:
        self.current = registry.model_copy(deep=True)
        self.client, self.write, self.save = client, write, save
        self.wording, self.taxonomy = wording, taxonomy
        self.space = self.current.space_id
        self.pushed: set[str] = set()
        self.applied: set[str] = set()
        self.obsoleted: set[str] = set()
        self.skipped: Counter[str] = Counter()
        self.handled: set[str] = set()
        self.submitted: set[tuple[object, ...]] = set()
        self.following: set[tuple[str, int, str]] = set()  # edited on: the next step is asked

    # The registry ---------------------------------------------------------------------------

    def put(self, use: MethodUse) -> MethodUse:
        """Replace the record with this one, checked, and persist."""
        checked = MethodUse.model_validate(use.model_dump())
        uses = [checked if u.triple == use.triple else u for u in self.current.method_uses]
        check_method_uses(uses)
        self.current.method_uses = uses
        if self.write:
            self.save(self.current)
        return checked

    def method_only(self, use: MethodUse) -> bool:
        return any(
            p.knowledge_id == use.knowledge_id and p.attribution.outcome == "METHOD_MATERIAL"
            for p in self.current.pending
        )

    def question(self, use: MethodUse) -> ConfirmationInput:
        return method_question(
            use, self.wording, taxonomy=self.taxonomy, method_only=self.method_only(use)
        )

    # Steps ----------------------------------------------------------------------------------

    def reconcile(self, listed: list[ConfirmationItem]) -> None:
        """Complete or drop the settlements an earlier run left (Spec §4.3)."""
        by_id = {item.id: item for item in listed}
        for use in list(self.current.method_uses):
            settlement = use.settlement
            if settlement is None:
                continue
            item = by_id.get(settlement.answer.item_id)
            answer = item.answer if item is not None else None
            if item is None or item.revision != settlement.revision:
                self.put(use.model_copy(update={"settlement": None}))
                self.skipped["CONFIRMATION_NOT_FOUND"] += 1
            elif item.closure is not None:
                if (item.closure.reason, item.closure.answer_id) == (
                    "applied",
                    settlement.answer.answer_id,
                ):
                    self.execute(use, settlement)
                else:
                    self.put(use.model_copy(update={"settlement": None}))
                    self.skipped["CONFIRMATION_CLOSED"] += 1
            elif answer is None or answer.id != settlement.answer.answer_id:
                self.put(use.model_copy(update={"settlement": None}))  # settled afresh below
            else:
                self.commit(use, settlement)

    def ask(
        self, listed: list[ConfirmationItem], only: set[tuple[str, int, str]] | None = None
    ) -> set[tuple[object, ...]]:
        """Push every asked question (or `only` those records') and settle the answered ones;
        the wanted contents. Questions go in the batches the platform accepts (Spec §4.1): a batch
        that fails ends the run, after what earlier batches settled is saved."""
        asked = []
        for use in self.current.method_uses:
            if not use.asked or (only is not None and use.triple not in only):
                continue
            try:
                asked.append((use, self.question(use)))
            except ConfirmationsError as error:
                self.skipped[error.code] += 1
        wanted = {content_of(question) for _, question in asked}
        fresh = [
            (use, question)
            for use, question in asked
            if use.settlement is None and content_of(question) not in self.submitted
        ]
        self.submitted |= {content_of(question) for _, question in fresh}
        self.pushed.update(use.knowledge_id for use, _ in fresh)
        if not self.write:  # a dry run finds what the platform would return, open or closed
            existing = {content_of(item): item for item in listed}
            self.answered([(use, existing.get(content_of(q))) for use, q in fresh])
            return wanted
        sent = 0
        for batch in confirmation_batches([question for _, question in fresh]):
            uses = [use for use, _ in fresh[sent : sent + len(batch)]]
            sent += len(batch)
            stored = self.client.submit_confirmations(self.space, batch)  # in input order
            self.answered(list(zip(uses, stored, strict=True)))  # settled batch by batch
        return wanted

    def answered(self, pairs: list[tuple[MethodUse, ConfirmationItem | None]]) -> None:
        """Settle the items a person answered; a closed one was closed elsewhere."""
        for use, item in pairs:
            if item is None or item.id in self.handled:
                continue
            if item.closure is not None:
                self.skipped["CONFIRMATION_CLOSED"] += 1
            elif item.answer is not None:
                self.settle(use, item)

    def settle(self, use: MethodUse, item: ConfirmationItem) -> None:
        """Decide, save the settlement, close, execute (Spec §4.2, §4.3)."""
        answer = item.answer
        assert answer is not None
        current = self.question(use)
        offered = method_choices(use, self.taxonomy)
        choice = next((c for c in offered if c.key == answer.option_key), None)
        if choice is None or item.revision != current.revision:
            self.skipped["CHOICE_STALE"] += 1
            return
        try:
            ref = ScopeAnswer(
                item_id=item.id,
                answer_id=answer.id,
                option_key=answer.option_key,
                answerer=answer.answerer,
            )
        except ValidationError:
            self.skipped["ANSWER_INVALID"] += 1
            return
        ignore: Literal["material", "method_use"] | None = None
        if not choice.labels:  # what the ignore covers is fixed now, as the question was asked
            ignore = "material" if self.method_only(use) else "method_use"
        settlement = ScopeSettlement(
            revision=item.revision,
            answer=ref,
            categories=choice.labels,
            editing=choice.editing,
            ignore=ignore,
        )
        self.commit(self.put(use.model_copy(update={"settlement": settlement})), settlement)

    def commit(self, use: MethodUse, settlement: ScopeSettlement) -> None:
        if self.write:
            try:
                self.client.close_confirmation(
                    self.space, settlement.answer.item_id, "applied", settlement.answer.answer_id
                )
            except PlatformError as error:
                if error.code not in {"ANSWER_STALE", "CONFIRMATION_CLOSED"}:
                    raise  # the settlement stays: the next run reconciles it
                self.put(use.model_copy(update={"settlement": None}))
                self.skipped[error.code] += 1
                return
        self.execute(use, settlement)

    def execute(self, use: MethodUse, settlement: ScopeSettlement) -> None:
        """Do exactly what the settlement says, never re-derived from the registry as it is now
        (Spec §4.3, §4.4). An ignore of the whole material that can no longer be recorded fails
        closed: the record keeps its settlement and every run reports it."""
        self.handled.add(settlement.answer.item_id)
        if settlement.ignore == "material" and not self._ignore_material(use, settlement.answer):
            self.skipped["SETTLEMENT_NOT_APPLICABLE"] += 1
            return
        decided = {"decided_by": "person", "confirmation": settlement.answer, "settlement": None}
        if settlement.categories:
            labels = {"categories": settlement.categories, "editing": settlement.editing}
            self.put(use.model_copy(update={**decided, **labels, "state": "active"}))
            if settlement.editing:
                self.following.add(use.triple)
        else:
            ignored = {"state": "ignored", "categories": (), "editing": False}
            self.put(use.model_copy(update={**decided, **ignored}))
        self.applied.add(use.knowledge_id)

    def _ignore_material(self, use: MethodUse, answer: ScopeAnswer) -> bool:
        """The IGNORED decision of a method-only material, recorded in place; False if refused."""
        source = RawSource(
            knowledge_id=use.knowledge_id,
            parse_attempt=use.parse_attempt,
            file_name=use.file_name,
            sha256=use.sha256,
        )
        conclusion = Attribution(
            outcome="IGNORED",
            reason="confirmed_ignore",
            role=METHOD_ROLE,
            policy_ref=load_attribution_policy().policy_ref,
        )
        ref = ConfirmationRef(
            item_id=answer.item_id,
            answer_id=answer.answer_id,
            option_key=answer.option_key,
            answerer=answer.answerer,
        )
        try:
            record(self.current, source, conclusion, ref)
        except RegistryError:  # no longer waiting at this revision, or the answer is recorded
            return False
        return True

    def clean(self, wanted: set[tuple[object, ...]], listed: list[ConfirmationItem]) -> None:
        """Close the method items no longer asked; an answered one was answered too late."""
        if self.write:
            open_items = self.client.confirmations(self.space, "open")
        else:
            open_items = [item for item in listed if item.closure is None]
        settling = {u.settlement.answer.item_id for u in self.current.method_uses if u.settlement}
        for item in open_items:
            if (
                not item.subject.startswith(SUBJECT_PREFIX)
                or item.id in self.handled
                or item.id in settling
                or content_of(item) in wanted
            ):
                continue
            if self.write:
                try:
                    self.client.close_confirmation(self.space, item.id, "obsolete")
                except PlatformError as error:
                    if error.code != "CONFIRMATION_CLOSED":
                        raise
                    self.skipped[error.code] += 1
                    continue
            if item.answer is not None:
                self.skipped["CHOICE_STALE"] += 1  # answered on evidence that has changed
            self.handled.add(item.id)
            self.obsoleted.add(item.subject.removeprefix(SUBJECT_PREFIX))

    def report(self) -> MethodConfirmationReport:
        return MethodConfirmationReport(
            pushed=sorted(self.pushed),
            applied=sorted(self.applied),
            obsoleted=sorted(self.obsoleted),
            waiting=sum(1 for u in self.current.method_uses if u.asked),
            skipped=dict(sorted(self.skipped.items())),
        )


def sync_methods(
    registry: ProductRegistry,
    client: PlatformClient,
    *,
    write: bool,
    save: Callable[[ProductRegistry], None],
    wording: MethodWording | None = None,
    taxonomy: SalesTaxonomy | None = None,
) -> MethodConfirmationRun:
    """One run over the scope-label questions; the given registry is not modified."""
    run = _MethodSync(
        registry,
        client,
        write,
        save,
        wording or load_method_wording(),
        taxonomy or load_sales_taxonomy(),
    )
    listed = [*client.confirmations(run.space, "open"), *client.confirmations(run.space, "closed")]
    run.reconcile(listed)
    wanted = run.ask(listed)
    wanted |= run.ask(listed, run.following)  # an answer's next step is asked at once (§4.1)
    run.clean(wanted, listed)
    final = ProductRegistry.model_validate(run.current.model_dump())
    return MethodConfirmationRun(registry=final, report=run.report())


def request_relabel(registry: ProductRegistry, knowledge_id: str) -> ProductRegistry:
    """A person's request to correct a material's labels (Spec §4.5): its live record is asked
    again through the same question; one already asked stays as it is."""
    current = registry.model_copy(deep=True)
    live = [u for u in current.method_uses if u.knowledge_id == knowledge_id and u.state in LIVE]
    if not live:
        raise ConfirmationsError("METHOD_USE_NOT_FOUND")
    current.method_uses = [
        u.model_copy(update={"editing": True}) if u in live and not u.asked else u
        for u in current.method_uses
    ]
    return ProductRegistry.model_validate(current.model_dump())
