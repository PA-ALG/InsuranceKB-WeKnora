"""The material-level method-use record of a v2 registry (SK-1 Spec §2.3; SK-0 §4.3 (a)).

A record is keyed by the material's source revision (knowledge id, parse attempt, SHA-256): the
same identity a product material has, so both uses of one material name one source. It holds the
blocks that make the material a method material, the scope labels its blocks hit (each with its
evidence), the labels in force and who decided them, and never a method identity, which only
admission assigns (SK-2). Labels are applicability tags: the machine assigns every label hit, a
person chooses when none is, and a person may later correct them through the same question
(`editing`). A record is kept after it expires (for audit) and never revived: a new revision is a
new record.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from insurance_harness.identity.method_signals import Block, Label, LabelHit

METHOD_ROLE: Literal["sales_method"] = "sales_method"
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_OptionKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9:._-]{0,127}$")]
_Principal = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f-\x9f]{1,256}$")]
LIVE = frozenset({"awaiting_scope", "active"})


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ScopeAnswer(_Strict):
    """The platform answer a person's scope decision came from."""

    item_id: _Identifier
    answer_id: _Identifier
    option_key: _OptionKey
    answerer: _Principal


def _ordered(labels: tuple[str, ...]) -> bool:
    return list(labels) == sorted(set(labels))


class ScopeSettlement(_Strict):
    """What a run decided for an answered scope question, saved before closing its item (§4.3)."""

    revision: _Identifier
    answer: ScopeAnswer
    categories: tuple[Label, ...]  # the labels after the answer; empty: ignored
    editing: bool  # the person goes on choosing: the next question is asked

    @model_validator(mode="after")
    def _consistent(self) -> "ScopeSettlement":
        if not _ordered(self.categories) or (self.editing and not self.categories):
            raise ValueError("labels are sorted and unique; only a labelled record goes on editing")
        return self


class MethodUse(_Strict):
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    file_name: str = Field(min_length=1)
    role: Literal["sales_method"] = METHOD_ROLE
    block_scheme: Literal["segments.v1"]
    block_ids: tuple[Block, ...] = Field(min_length=1)
    signals: tuple[str, ...] = Field(min_length=1)
    label_hits: tuple[LabelHit, ...]  # every label the blocks hit, with its blocks and words
    taxonomy_version: str = Field(min_length=1)
    evidence_digest: _Digest
    state: Literal["awaiting_scope", "active", "ignored", "invalidated"]
    categories: tuple[Label, ...] = ()  # the scope labels in force, sorted
    decided_by: Literal["machine", "person"] | None = None
    confirmation: ScopeAnswer | None = None  # the person's latest answer
    editing: bool = False  # a person is choosing or correcting the labels: the question is asked
    invalidated_reason: Literal["source_revised", "withdrawn", "detached", "ignored"] | None = None
    settlement: ScopeSettlement | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "MethodUse":
        hit = tuple(h.label for h in self.label_hits)
        if len(set(self.block_ids)) != len(self.block_ids) or not _ordered(hit):
            raise ValueError("a block or a label hit is listed twice")
        if (self.state == "invalidated") != (self.invalidated_reason is not None):
            raise ValueError("an invalidated record, and only one, names why")
        if self.state == "awaiting_scope" and (hit or self.categories or self.decided_by):
            raise ValueError("only a record without any label hit waits for a person")
        if self.state == "active" and not (self.categories and self.decided_by):
            raise ValueError("an active record has its labels and who decided them")
        if self.decided_by == "machine" and self.categories != hit:
            raise ValueError("the machine assigns exactly the labels the blocks hit")
        if self.state == "ignored" and (self.categories or self.decided_by != "person"):
            raise ValueError("only a person ignores a method use, without labels")
        if (self.decided_by == "person") != (self.confirmation is not None):
            raise ValueError("a person's decision, and only one, names its answer")
        if self.editing and self.state != "active":
            raise ValueError("only an active record is being edited")
        if self.settlement is not None and not self.asked:
            raise ValueError("only a record whose question is asked has a settlement")
        if not _ordered(self.categories):
            raise ValueError("labels are sorted and listed once")
        return self

    @property
    def triple(self) -> tuple[str, int, str]:
        return (self.knowledge_id, self.parse_attempt, self.sha256)

    @property
    def asked(self) -> bool:
        """Its scope question is on the page: no label hit yet, or a person is editing."""
        return self.state == "awaiting_scope" or (self.state == "active" and self.editing)


def check_method_uses(uses: Sequence[MethodUse]) -> None:
    """The registry-wide rules (Spec §2.3), raised as ValueError for the model validator."""
    triples = Counter(use.triple for use in uses)
    if any(count > 1 for count in triples.values()):
        raise ValueError("two method-use records for one source revision")
    live = Counter(use.knowledge_id for use in uses if use.state in LIVE)
    if any(count > 1 for count in live.values()):
        raise ValueError("two live method-use records for one material")
    answers = [u.confirmation.answer_id for u in uses if u.confirmation is not None]
    answers += [u.settlement.answer.answer_id for u in uses if u.settlement is not None]
    if len(set(answers)) != len(answers):
        raise ValueError("an answer is recorded twice")
