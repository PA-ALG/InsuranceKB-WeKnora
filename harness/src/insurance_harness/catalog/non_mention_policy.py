"""Versioned recognition of values that only say the material states nothing (RV6a Spec §2).

The value step must write a non-empty value, so a field selected as present whose segments do
not state it comes back as "材料未提及……". Such a value is no fact: the compiler records the
field as unknown. The rule errs towards keeping a value: one sentence with material content, or
a sentence without a material subject, keeps the whole value present.
"""

import re
import unicodedata
from functools import lru_cache
from importlib.resources import files
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    ValidationError,
    model_validator,
)

NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]
Phrases = tuple[NonBlank, ...]

# Sentence breaks after NFKC, which turns full-width ；：， into ; : ,.
_SENTENCES = re.compile(r"[。;\n]")
_ITEM_NUMBER = re.compile(r"^(?:\d+(?:\.\d+)*[.、)]|\(\d+\))\s*")
# Text after the verb is what was not stated; a comma or colon starts something else.
_CLAUSE_MARKS = (",", ":")


class NonMentionPolicyError(ValueError):
    """A stable code, without policy content or a local path."""

    def __init__(self) -> None:
        self.code = "NON_MENTION_POLICY_INVALID"
        super().__init__(self.code)


class NonMentionPolicy(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: NonBlank
    subjects: Phrases = Field(min_length=1)
    connectors: Phrases = Field(min_length=1)
    negations: Phrases = Field(min_length=1)
    verbs: Phrases = Field(min_length=1)
    continuations: Phrases = Field(min_length=1)
    label_max_chars: int = Field(ge=1, le=40)
    _sentence: re.Pattern[str] = PrivateAttr()
    _label: re.Pattern[str] = PrivateAttr()

    @model_validator(mode="after")
    def _compile(self) -> "NonMentionPolicy":
        groups = (self.subjects, self.connectors, self.negations, self.verbs, self.continuations)
        for phrases in groups:
            if len(set(phrases)) != len(phrases):
                raise ValueError("duplicate phrase")
            for phrase in phrases:
                # Values are matched in NFKC form; a phrase in another form could never match.
                if unicodedata.normalize("NFKC", phrase) != phrase or _SENTENCES.search(phrase):
                    raise ValueError("phrase must be NFKC text within one sentence")
        self._sentence = re.compile(
            f"(?:{_any(self.subjects)})(?:{_any(self.connectors)})*"
            f"(?:{_any(self.negations)})(?:{_any(self.verbs)})(?P<rest>.*)",
            re.DOTALL,
        )
        self._label = re.compile(f"^[^,:]{{1,{self.label_max_chars}}}:\\s*")
        return self

    def only_non_mention(self, value: str) -> bool:
        """Every sentence only says the material does not state something."""
        sentences = [s.strip() for s in _SENTENCES.split(unicodedata.normalize("NFKC", value))]
        sentences = [s for s in sentences if s]
        return bool(sentences) and all(self._non_mention(s) for s in sentences)

    def _non_mention(self, sentence: str) -> bool:
        sentence = self._label.sub("", _ITEM_NUMBER.sub("", sentence), count=1).strip()
        match = self._sentence.fullmatch(sentence)
        if match is None:
            return False
        rest = match.group("rest")
        return not any(mark in rest for mark in (*_CLAUSE_MARKS, *self.continuations))


def _any(phrases: Phrases) -> str:
    # Longest first, so a phrase is never cut short by another one it starts with.
    return "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))


def parse_non_mention_policy(text: str) -> NonMentionPolicy:
    try:
        return NonMentionPolicy.model_validate_json(text)
    except (ValidationError, ValueError) as error:
        raise NonMentionPolicyError() from error


@lru_cache(maxsize=1)
def load_non_mention_policy() -> NonMentionPolicy:
    try:
        return parse_non_mention_policy(
            files(__package__).joinpath("non_mention_policy.json").read_text(encoding="utf-8")
        )
    except OSError as error:
        raise NonMentionPolicyError() from error
