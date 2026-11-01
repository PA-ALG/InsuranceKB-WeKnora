"""The material-level method-use record of a v2 registry (SK-1 Spec §2.3; SK-0 §4.3 (a)).

A record is keyed by the material's source revision (knowledge id, parse attempt, SHA-256): the
same identity a product material has, so both uses of one material name one source. It holds the
blocks that make the material a method material, its insurance-category labels and who decided
them, and never a method identity, which only admission assigns (SK-2). A record is kept after it
expires (for audit) and never revived: a new revision is a new record.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

METHOD_ROLE: Literal["sales_method"] = "sales_method"
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_Label = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]*(:[a-z][a-z_]*)?$")]
_Block = Annotated[str, StringConstraints(pattern=r"^P[1-9][0-9]*S[1-9][0-9]*$")]
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


class ScopeSettlement(_Strict):
    """What a run decided for an answered scope question, saved before closing its item (§4.3)."""

    revision: _Identifier
    answer: ScopeAnswer
    categories: tuple[_Label, ...]  # empty: the answer ignores the material as a method material


class MethodUse(_Strict):
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    file_name: str = Field(min_length=1)
    role: Literal["sales_method"] = METHOD_ROLE
    block_scheme: Literal["segments.v1"]
    block_ids: tuple[_Block, ...] = Field(min_length=1)
    signals: tuple[str, ...] = Field(min_length=1)
    category_hits: tuple[_Label, ...]
    general_hit: bool
    taxonomy_version: str = Field(min_length=1)
    evidence_digest: _Digest
    state: Literal["awaiting_scope", "active", "ignored", "invalidated"]
    categories: tuple[_Label, ...] = ()
    decided_by: Literal["machine", "person"] | None = None
    confirmation: ScopeAnswer | None = None
    invalidated_reason: Literal["source_revised", "withdrawn", "detached", "ignored"] | None = None
    settlement: ScopeSettlement | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "MethodUse":
        if len(set(self.block_ids)) != len(self.block_ids):
            raise ValueError("a block is listed twice")
        if (self.state == "invalidated") != (self.invalidated_reason is not None):
            raise ValueError("an invalidated record, and only one, names why")
        if self.state == "awaiting_scope" and (self.categories or self.decided_by):
            raise ValueError("a record waiting for its scope has no conclusion yet")
        if self.state == "active" and not (self.categories and self.decided_by):
            raise ValueError("an active record has its categories and who decided them")
        if self.state == "ignored" and (self.categories or self.decided_by != "person"):
            raise ValueError("only a person ignores a method use, without categories")
        if (self.decided_by == "person") != (self.confirmation is not None):
            raise ValueError("a person's decision, and only one, names its answer")
        if self.settlement is not None and self.state != "awaiting_scope":
            raise ValueError("only a record waiting for its scope has a settlement")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("a category is listed twice")
        return self

    @property
    def triple(self) -> tuple[str, int, str]:
        return (self.knowledge_id, self.parse_attempt, self.sha256)


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
