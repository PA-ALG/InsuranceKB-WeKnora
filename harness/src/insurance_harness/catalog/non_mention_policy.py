"""Versioned recognition of values that only say the material states nothing (RV6a Spec §2).

The value step must write a non-empty value, so a field selected as present whose segments do
not state it comes back as "材料未提及……". Such a value is no fact: the compiler records the
field as unknown. The rule errs towards keeping a value: one sentence with material content, or
a sentence without a material subject, keeps the whole value present. A leading "xxx：" is never
taken off, because what precedes the colon may itself be a fact (review R1).
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
# A whole item number such as 2.1 ends in a delimiter or a space; a number glued to text is not one.
_ITEM_NUMBER = re.compile(r"^(?:(?>\d+(?:\.\d+)*)(?:[.、)]|\s)|\(\d+\))\s*")
# Text after the verb is what was not stated; a comma or colon starts something else, and a
# digit is a value of some rule.
_MORE_CONTENT = re.compile(r"[,:\d]")


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
    relative_particles: Phrases = Field(min_length=1)
    content_markers: Phrases = Field(min_length=1)
    _sentence: re.Pattern[str] = PrivateAttr()

    @model_validator(mode="after")
    def _compile(self) -> "NonMentionPolicy":
        groups = (
            self.subjects,
            self.connectors,
            self.negations,
            self.verbs,
            self.relative_particles,
            self.content_markers,
        )
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
        return self

    def only_non_mention(self, value: str) -> bool:
        """Every sentence only says the material does not state something."""
        sentences = [s.strip() for s in _SENTENCES.split(unicodedata.normalize("NFKC", value))]
        sentences = [s for s in sentences if s]
        return bool(sentences) and all(self._non_mention(s) for s in sentences)

    def _non_mention(self, sentence: str) -> bool:
        match = self._sentence.fullmatch(_ITEM_NUMBER.sub("", sentence, count=1).strip())
        if match is None:
            return False
        rest = match.group("rest")
        # "条款未约定的事项按……执行": the negated verb qualifies a noun that a rule follows.
        if rest.startswith(self.relative_particles) or _MORE_CONTENT.search(rest):
            return False
        return not any(marker in rest for marker in self.content_markers)


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
    except (OSError, UnicodeDecodeError) as error:
        raise NonMentionPolicyError() from error
