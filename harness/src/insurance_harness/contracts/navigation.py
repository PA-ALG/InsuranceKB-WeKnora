"""Navigation contract: how readers organise a release's entries (S3e) and the question vocabulary
the platform matches against them (QA3, PV-4b, SK-3)."""

from __future__ import annotations

import unicodedata
from typing import Literal, Self

from pydantic import Field, model_validator

from insurance_harness.contracts.knowledge import ContractModel, NonBlank

QuestionIntent = Literal["sales", "service", "method"]


class NavigationGroup(ContractModel):
    group_key: NonBlank
    display_name: NonBlank
    classification_labels: list[NonBlank] = Field(default_factory=list)


class NavigationDomain(ContractModel):
    domain_key: NonBlank
    display_name: NonBlank
    entity_types: list[NonBlank] = Field(min_length=1)
    groups: list[NavigationGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def group_keys_are_unique(self) -> Self:
        keys = [group.group_key for group in self.groups]
        if len(set(keys)) != len(keys):
            raise ValueError("group keys must be unique within a domain")
        return self


def question_term_text(term: str) -> str:
    """A question term exactly as the platform's Go normalizeQuestionTerm compares it (QA3
    Spec §2): NFKC, lower case, without whitespace or punctuation; symbols stay. A term must
    keep at least two characters."""
    folded = unicodedata.normalize("NFKC", term).lower()
    return "".join(
        ch
        for ch in folded
        if not _platform_space(ch) and not unicodedata.category(ch).startswith("P")
    )


def _platform_space(ch: str) -> bool:
    # Go unicode.IsSpace, plus the BOM its normalize also drops. str.isspace differs from it only
    # by the information separators U+001C-U+001F, which Go keeps (checked over every code point).
    return (ch.isspace() and not "\x1c" <= ch <= "\x1f") or ch == "\ufeff"


class NavigationProfile(ContractModel):
    """How readers organise a release's entries (S3e): domains by entity type, then groups by
    classification label. Versioned data published with the release, replaced whole each time.
    """

    navigation_id: NonBlank
    navigation_version: NonBlank
    # S3f-2: the Space's display name and the fields of its product overview, in column order.
    display_name: NonBlank | None = None
    overview_fields: list[NonBlank] = Field(default_factory=list)
    domains: list[NavigationDomain] = Field(min_length=1)
    # QA3: per field key, groups of 1-3 terms; a question asks a field when it contains every
    # term of one group. Absent in navigations published before QA3.
    question_terms: dict[NonBlank, list[list[NonBlank]]] | None = None
    # PV-4b: per question intent, term groups shaped like question_terms. The platform narrows
    # product versions by intent from these alone (Spec PV-4b §4). Absent before PV-4b. SK-3 adds
    # "method": questions on how to sell or explain, which take method knowledge first.
    question_intents: dict[QuestionIntent, list[list[NonBlank]]] | None = None

    @model_validator(mode="after")
    def keys_are_unique(self) -> Self:
        keys = [domain.domain_key for domain in self.domains]
        if len(set(keys)) != len(keys):
            raise ValueError("domain keys must be unique")
        if len(set(self.overview_fields)) != len(self.overview_fields):
            raise ValueError("overview fields must be unique")
        intents = (self.question_intents or {}).values()
        for groups in [*(self.question_terms or {}).values(), *intents]:
            _check_term_groups(groups)
        return self


def _check_term_groups(groups: list[list[str]]) -> None:
    # A group matches when every term occurs, so its order carries nothing: compare sets.
    seen: set[frozenset[str]] = set()
    for group in groups:
        texts = frozenset(question_term_text(term) for term in group)
        if not 1 <= len(group) <= 3 or any(len(text) < 2 for text in texts):
            raise ValueError("a question-term group has 1 to 3 terms of 2+ characters")
        if len(texts) != len(group):
            raise ValueError("a question-term group repeats a term")
        if texts in seen:
            raise ValueError("the term groups of one key must be distinct")
        seen.add(texts)
