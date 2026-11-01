"""The method-scope question of a method use, and how its answer is applied (SK-1 Spec §4).

A method use whose insurance category the machine could not decide is asked under its own subject
(`method:<knowledge id>`), apart from the product questions (`material:`), whose run never touches
these items. The revision covers the source revision, the evidence and the wording, so changed
evidence is a new question and an answer to the old one is stale. As for product questions, closing
is the commit point: a run saves what it is about to do (the settlement) on the record, closes the
item, then executes exactly what it saved; an interrupted run completes it from the settlement.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

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
from insurance_harness.ingest.confirmation_questions import ConfirmationsError, trim
from insurance_harness.ingest.method_use_model import (
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
_KINDS = ("suggested", "general", "category", "ignore")


class MethodWording(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    title: str
    detail: str
    no_categories: str
    ignore_method_only: str
    ignore_dual: str
    options: dict[str, str]
    categories: dict[str, str]

    @model_validator(mode="after")
    def _complete(self) -> "MethodWording":
        labels = set(load_sales_taxonomy().insurance_labels())
        if set(self.options) != set(_KINDS) or set(self.categories) != labels:
            raise ValueError("the wording must cover every choice kind and insurance category")
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
    labels: tuple[str, ...]  # empty for ignoring


def method_choices(
    use: MethodUse, taxonomy: SalesTaxonomy | None = None
) -> tuple[ScopeChoice, ...]:
    """The single choices, in a fixed order: the taxonomy's combination when it hit several
    categories, general, each category, then ignoring (Spec §4.1)."""
    taxonomy = taxonomy or load_sales_taxonomy()
    offered = []
    if len(use.category_hits) > 1:
        offered.append(ScopeChoice("scope:suggested", "suggested", use.category_hits))
    offered.append(ScopeChoice(taxonomy.general.label, "general", (taxonomy.general.label,)))
    offered += [
        ScopeChoice(f"scope:{label}", "category", (label,))
        for label in taxonomy.insurance_labels()
    ]
    offered.append(ScopeChoice("ignore", "ignore", ()))
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
    """The confirmation item for one method use waiting for its scope (Spec §4.1)."""
    wording = wording or load_method_wording()
    subject = SUBJECT_PREFIX + use.knowledge_id
    if not _SUBJECT.fullmatch(subject) or use.state != "awaiting_scope":
        raise ConfirmationsError("QUESTION_INVALID")
    identity = {
        "triple": list(use.triple),
        "evidence": use.evidence_digest,
        "taxonomy": use.taxonomy_version,
        "wording": wording.version,
        "method_only": method_only,
    }
    canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    names = wording.categories
    categories = "、".join(names[label] for label in use.category_hits) or wording.no_categories
    facts = {
        "file": use.file_name,
        "signals": "、".join(use.signals),
        "categories": categories,
        "ignore_note": wording.ignore_method_only if method_only else wording.ignore_dual,
    }
    options = []
    for choice in method_choices(use, taxonomy):
        values = facts | {
            "category": names.get(choice.labels[0], "") if choice.kind == "category" else "",
            "categories": "、".join(names.get(label, label) for label in choice.labels),
        }
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

    def ask(self, listed: list[ConfirmationItem]) -> set[tuple[object, ...]]:
        """Push every waiting question and settle the answered ones; the wanted contents."""
        waiting = [u for u in self.current.method_uses if u.state == "awaiting_scope"]
        asked = []
        for use in waiting:
            try:
                asked.append((use, self.question(use)))
            except ConfirmationsError as error:
                self.skipped[error.code] += 1
        wanted = {content_of(question) for _, question in asked}
        fresh = [(use, question) for use, question in asked if use.settlement is None]
        self.pushed.update(use.knowledge_id for use, _ in fresh)
        if not fresh:
            return wanted
        if self.write:
            stored: list[ConfirmationItem | None] = list(
                self.client.submit_confirmations(self.space, [q for _, q in fresh])
            )
        else:
            existing = {content_of(item): item for item in listed}
            stored = [existing.get(content_of(question)) for _, question in fresh]
        for (use, _), item in zip(fresh, stored, strict=True):
            if item is None or item.id in self.handled:
                continue
            if item.closure is not None:
                self.skipped["CONFIRMATION_CLOSED"] += 1
            elif item.answer is not None:
                self.settle(use, item)
        return wanted

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
        settlement = ScopeSettlement(revision=item.revision, answer=ref, categories=choice.labels)
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
        """Do what the settlement says (Spec §4.4)."""
        self.handled.add(settlement.answer.item_id)
        decided = {"decided_by": "person", "confirmation": settlement.answer, "settlement": None}
        if settlement.categories:
            active = {**decided, "state": "active", "categories": settlement.categories}
            self.put(use.model_copy(update=active))
        else:
            if self.method_only(use):  # a method-only material is ignored as a whole
                self._ignore_material(use, settlement.answer)
            self.put(use.model_copy(update={**decided, "state": "ignored", "categories": ()}))
        self.applied.add(use.knowledge_id)

    def _ignore_material(self, use: MethodUse, answer: ScopeAnswer) -> None:
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
        except RegistryError as error:
            self.skipped[error.code] += 1

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
            waiting=sum(1 for u in self.current.method_uses if u.state == "awaiting_scope"),
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
    """One run over the method-scope questions; the given registry is not modified."""
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
    run.clean(wanted, listed)
    final = ProductRegistry.model_validate(run.current.model_dump())
    return MethodConfirmationRun(registry=final, report=run.report())
