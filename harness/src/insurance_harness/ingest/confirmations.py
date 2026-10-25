"""Questions for a person go to the platform as confirmation items; answers come back (S5b-3c-2).

One run pushes every material waiting for a person, settles the items a person answered and closes
the items no longer asked. Closing comes first: the platform checks under its lock that the answer
is still the latest, and once closed no answer can follow, so the registry is written only after a
successful close. A run cut off in between is completed from the closed items on the next run.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
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
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.identity.attribution import Upload, load_attribution_policy
from insurance_harness.identity.confirmation import Choice, ConfirmationError, choices, conclude
from insurance_harness.identity.material_roles import load_material_roles
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    ConfirmationRef,
    PendingEntry,
    ProductRegistry,
    RegistryError,
    head_of,
    record,
)
from insurance_harness.ingest.source_map import PageReader

SUBJECT_PREFIX = "material:"
_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")  # the platform's (S5b-3a)
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")
_REASONS = {"multiple_products", "pack_unresolved", "role_unresolved", "same_role_differs"}
_KINDS = {"product", "pack", "role", "replace", "supplement", "ignore"}
_BATCH = 200
_LIMITS = {"title": 200, "detail": 2000, "label": 200}


class ConfirmationsError(ValueError):
    """WORDING_INVALID or QUESTION_INVALID; never the material's text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ConfirmationWording(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    title: str
    details: dict[str, str]
    options: dict[str, str]
    roles: dict[str, str]

    @model_validator(mode="after")
    def _complete(self) -> "ConfirmationWording":
        roles = {role.role for role in load_material_roles().roles}
        if set(self.details) != _REASONS or set(self.options) != _KINDS or set(self.roles) != roles:
            raise ValueError("the wording must cover every reason, choice and role")
        return self


class ConfirmationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pushed: list[str]
    applied: list[str]
    reopened: list[str]
    obsoleted: list[str]
    waiting: int
    skipped: dict[str, int]


class ConfirmationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: ProductRegistry
    report: ConfirmationReport


@lru_cache(maxsize=1)
def load_wording() -> ConfirmationWording:
    try:
        text = files(__package__).joinpath("confirmation_wording.json").read_text(encoding="utf-8")
        return ConfirmationWording.model_validate_json(text)
    except (OSError, ValidationError):
        raise ConfirmationsError("WORDING_INVALID") from None


def _fill(template: str, limit: int, values: dict[str, str]) -> str:
    """The template with its values; an overlong file name is cut and ends with "…"."""
    try:
        text = template.format(**values)
        overflow = len(text) - limit
        if overflow > 0 and len(values.get("file", "")) > overflow:
            text = template.format(**(values | {"file": values["file"][: -overflow - 1] + "…"}))
    except (KeyError, IndexError, ValueError):
        raise ConfirmationsError("WORDING_INVALID") from None
    if not text.strip() or len(text) > limit or _CONTROL.search(text):
        raise ConfirmationsError("WORDING_INVALID")
    return text


def question_of(
    entry: PendingEntry, registry: ProductRegistry, wording: ConfirmationWording | None = None
) -> ConfirmationInput:
    """The confirmation item for one material waiting for a person (Spec §2.1, §3.2)."""
    wording = wording or load_wording()
    attribution = entry.attribution
    subject = SUBJECT_PREFIX + entry.knowledge_id
    if not _SUBJECT.fullmatch(subject):
        raise ConfirmationsError("QUESTION_INVALID")
    history = sum(1 for d in registry.decisions if d.knowledge_id == entry.knowledge_id)
    identity = {
        "knowledge_id": entry.knowledge_id,
        "parse_attempt": entry.parse_attempt,
        "sha256": entry.sha256,
        "attribution": attribution.model_dump(mode="json"),
        "decisions": history,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    revision = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def name(product_id: str | None) -> str:
        product = registry.products.get(product_id or "")
        return product.names[0] if product else ""

    role = wording.roles.get(attribution.role or "", "")
    facts = {
        "file": entry.file_name,
        "product": name(attribution.product_id),
        "products": "、".join(name(p) for p in attribution.candidates if p in registry.products),
        "role": role,
        "name": attribution.display_name or "",
        "code": attribution.clause_code or "",
    }
    try:
        offered = choices(attribution, registry.registered())
    except ConfirmationError:
        raise ConfirmationsError("QUESTION_INVALID") from None
    options = [
        ConfirmationOption(
            key=c.key,
            label=_fill(
                wording.options[c.kind], _LIMITS["label"], _option_facts(c, facts, name, wording)
            ),
        )
        for c in offered
    ]
    return ConfirmationInput(
        subject=subject,
        revision=revision,
        title=_fill(wording.title, _LIMITS["title"], {"file": entry.file_name}),
        detail=_fill(wording.details[attribution.reason], _LIMITS["detail"], facts),
        options=options,
    )


def _option_facts(
    choice: Choice,
    facts: dict[str, str],
    name: Callable[[str | None], str],
    wording: ConfirmationWording,
) -> dict[str, str]:
    if choice.kind == "product":
        return facts | {"product": name(choice.value)}
    if choice.kind == "pack":
        return facts | {"pack": _pack_labels().get(choice.value or "", "")}
    if choice.kind == "role":
        return facts | {"role": wording.roles.get(choice.value or "", "")}
    return facts


def _pack_labels() -> dict[str, str]:
    """Each pack's first classification suffix in the policy, such as 重大疾病保险."""
    labels: dict[str, str] = {}
    for entry in load_attribution_policy().classifications:
        labels.setdefault(entry.schema_pack_id, entry.suffix)
    return labels


def _content(item: ConfirmationInput | ConfirmationItem) -> tuple[object, ...]:
    options = tuple((o.key, o.label) for o in item.options)
    return (item.subject, item.revision, item.title, item.detail, options)


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
        self.client, self.pages, self.write, self.save, self.wording = (
            client,
            pages,
            write,
            save,
            wording,
        )
        self.space = self.current.space_id
        self.pushed: set[str] = set()
        self.applied: set[str] = set()
        self.reopened: set[str] = set()
        self.obsoleted: set[str] = set()
        self.skipped: Counter[str] = Counter()
        self.unaskable: dict[str, str] = {}  # knowledge id -> why its question cannot be pushed
        self.handled: set[str] = set()  # items closed (or, in a dry run, taken as closed) here

    def waiting(self) -> list[PendingEntry]:
        return sorted(
            (p for p in self.current.pending if p.attribution.outcome == "NEEDS_CONFIRM"),
            key=lambda p: p.knowledge_id,
        )

    def questions(
        self, entries: Iterable[PendingEntry]
    ) -> list[tuple[PendingEntry, ConfirmationInput]]:
        asked = []
        for entry in entries:
            try:
                asked.append((entry, question_of(entry, self.current, self.wording)))
            except ConfirmationsError as error:
                self.unaskable[entry.knowledge_id] = error.code
        return asked

    def recover(self) -> None:
        """Complete answers closed as applied whose registry write did not happen (Spec §2.2)."""
        closed = self.client.confirmations(self.space, "closed")
        recorded = {d.confirmation.answer_id for d in self.current.decisions if d.confirmation}
        for entry, question in self.questions(self.waiting()):
            matches = [
                item
                for item in closed
                if (item.subject, item.revision) == (question.subject, question.revision)
                and item.closure is not None
                and item.closure.reason == "applied"
                and item.answer is not None
                and item.closure.answer_id == item.answer.id
                and item.answer.id not in recorded
            ]
            if len(matches) > 1:
                self.skipped["CONFIRMATION_AMBIGUOUS"] += 1
            elif matches:
                self.settle(entry, matches[0], closed_already=True)

    def settle(
        self, entry: PendingEntry, item: ConfirmationItem, closed_already: bool = False
    ) -> None:
        answer = item.answer
        assert answer is not None
        source = RawSource(
            knowledge_id=entry.knowledge_id,
            parse_attempt=entry.parse_attempt,
            file_name=entry.file_name,
            sha256=entry.sha256,
        )
        try:
            head = head_of(self.pages, self.space, source)
        except SourcePagesError as error:
            self.skipped[error.code] += 1
            return
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
            if not closed_already and not self.close(item, "obsolete"):
                return
            self.current.pending = [
                p for p in self.current.pending if p.knowledge_id != entry.knowledge_id
            ]
            self.reopened.add(entry.knowledge_id)
            self.persist()
            return
        # Check on a copy that the conclusion can be recorded before closing: an item closed as
        # applied must never be left without its registry decision.
        try:
            ref = ConfirmationRef(
                item_id=item.id,
                answer_id=answer.id,
                option_key=answer.option_key,
                answerer=answer.answerer,
            )
            record(self.current.model_copy(deep=True), source, conclusion, ref)
        except ValidationError:
            self.skipped["ANSWER_INVALID"] += 1
            return
        except RegistryError as error:
            self.skipped[error.code] += 1
            return
        if not closed_already and not self.close(item, "applied", answer.id):
            return
        record(self.current, source, conclusion, ref)
        self.applied.add(entry.knowledge_id)
        self.persist()

    def close(
        self,
        item: ConfirmationItem,
        reason: Literal["applied", "obsolete"],
        answer_id: str | None = None,
    ) -> bool:
        """Close on the platform; False when another answer or closure came first."""
        if self.write:
            try:
                self.client.close_confirmation(self.space, item.id, reason, answer_id)
            except PlatformError as error:
                if error.code not in {"ANSWER_STALE", "CONFIRMATION_CLOSED"}:
                    raise
                self.skipped[error.code] += 1
                return False
        self.handled.add(item.id)
        return True

    def persist(self) -> None:
        if self.write:
            self.save(self.current)

    def ask(self, listed_open: list[ConfirmationItem]) -> None:
        """Push the questions, settle answered ones, and push the questions settling raises."""
        asked: dict[tuple[object, ...], ConfirmationInput] = {}
        for _ in range(8):  # each round asks only new questions; a choice raises at most a few
            fresh = [(e, q) for e, q in self.questions(self.waiting()) if _content(q) not in asked]
            if not fresh:
                break
            asked.update((_content(q), q) for _, q in fresh)
            self.pushed.update(e.knowledge_id for e, _ in fresh)
            stored = self.stored([q for _, q in fresh], listed_open)
            for (entry, _), item in zip(fresh, stored, strict=True):
                if item is None or item.id in self.handled:
                    continue
                if item.closure is not None:
                    self.skipped["CONFIRMATION_CLOSED"] += 1
                elif item.answer is not None:
                    self.settle(entry, item)

    def stored(
        self, questions: list[ConfirmationInput], listed_open: list[ConfirmationItem]
    ) -> list[ConfirmationItem | None]:
        if not self.write:  # a dry run only finds what is already on the platform
            existing = {_content(item): item for item in listed_open}
            return [existing.get(_content(q)) for q in questions]
        found: list[ConfirmationItem | None] = []
        for start in range(0, len(questions), _BATCH):
            found.extend(
                self.client.submit_confirmations(self.space, questions[start : start + _BATCH])
            )
        return found

    def clean(self, listed_open: list[ConfirmationItem]) -> None:
        """Close the material items no longer asked (Spec §2.4)."""
        wanted = {_content(q) for _, q in self.questions(self.waiting())}
        listed = self.client.confirmations(self.space, "open") if self.write else listed_open
        for item in listed:
            if not item.subject.startswith(SUBJECT_PREFIX) or item.id in self.handled:
                continue
            if _content(item) in wanted:
                continue
            if self.close(item, "obsolete"):
                self.obsoleted.add(item.subject.removeprefix(SUBJECT_PREFIX))

    def report(self) -> ConfirmationReport:
        return ConfirmationReport(
            pushed=sorted(self.pushed),
            applied=sorted(self.applied),
            reopened=sorted(self.reopened),
            obsoleted=sorted(self.obsoleted),
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
    run.recover()
    listed_open = [] if write else client.confirmations(run.space, "open")
    run.ask(listed_open)
    run.clean(listed_open)
    return ConfirmationRun(registry=run.current, report=run.report())
