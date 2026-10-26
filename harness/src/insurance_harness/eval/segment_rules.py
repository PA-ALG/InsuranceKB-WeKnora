"""The ruled segment scoring of 2026-10-26 (S12a Spec §2).

The user's rulings after the S12 error analysis, as versioned data (segment_scoring_rules.json):
near copies that differ only by 本合同/本条款 or a footnote mark credit each other; headings and
reader-guide lines, footnote blocks and the definitions section, and brochure restatements of cited
terms are neutral where the rules say so. Neutral segments leave both the recall and the precision
denominator of a field; they can still credit a Golden segment through a copy. Scoring only: the
compiler, the cards and Golden are untouched.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from insurance_harness.compilers.schema_fields.cards import all_cards
from insurance_harness.evidence.segments import Segment, SegmentedSource


class ScoringRulesError(ValueError):
    """The rules cannot be read; scoring never falls back to other rules silently."""


class ScoringRules(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    copy_min_chars: int = Field(gt=0)
    copy_replacements: tuple[tuple[str, str], ...]
    copy_footnote_pattern: str
    heading_max_chars: int = Field(gt=0)
    sentence_terminators: str = Field(min_length=1)
    guide_markers: tuple[str, ...]
    heading_roles: tuple[str, ...]
    footnote_start_pattern: str
    footnote_body_pattern: str
    footnote_body_chars: int = Field(gt=0)
    clause_number_pattern: str
    definition_heading_word: str = Field(min_length=1)
    chapter_heading_pattern: str
    definition_card_markers: tuple[str, ...]
    document_roles: tuple[tuple[str, str], ...]

    @model_validator(mode="after")
    def _patterns_compile(self) -> ScoringRules:
        for pattern in (
            self.copy_footnote_pattern,
            self.footnote_start_pattern,
            self.footnote_body_pattern,
            self.clause_number_pattern,
            self.chapter_heading_pattern,
        ):
            re.compile(pattern)
        return self


def load_scoring_rules(path: Path | None = None) -> ScoringRules:
    """The packaged rules, or the file at path; any problem is a ScoringRulesError."""
    if path is None:
        return _packaged()
    return _parse(path)


@lru_cache(maxsize=1)
def _packaged() -> ScoringRules:
    return _parse(files(__package__).joinpath("segment_scoring_rules.json"))


def _parse(path: Path | Traversable) -> ScoringRules:
    try:
        return ScoringRules.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError, re.error) as error:
        raise ScoringRulesError(f"scoring rules unreadable: {type(error).__name__}") from None


class RuledSource:
    """One segmented source under one set of rules; folded texts and copies are cached."""

    def __init__(self, source: SegmentedSource, rules: ScoringRules) -> None:
        self.source, self.rules = source, rules
        self._by_id: dict[str, Segment] = {s.id: s for s in source.segments}
        self._folded: dict[str, str] = {}
        self._copies: dict[str, frozenset[str]] = {}
        self._headings: set[str] | None = None
        self._notes: set[str] | None = None

    def role(self, document: str) -> str | None:
        return next((role for word, role in self.rules.document_roles if word in document), None)

    def folded(self, segment_id: str) -> str:
        text = self._folded.get(segment_id)
        if text is None:
            text = self.source.content(segment_id)
            for old, new in self.rules.copy_replacements:
                text = text.replace(old, new)
            text = self._folded[segment_id] = re.sub(self.rules.copy_footnote_pattern, "", text)
        return text

    def copies(self, segment_id: str) -> frozenset[str]:
        """Segments of other documents whose folded text contains, or is contained in, this one."""
        found = self._copies.get(segment_id)
        if found is None:
            mine, document = self.folded(segment_id), self._segment(segment_id).document
            matches = set()
            for other in self.source.segments:
                if other.document == document:
                    continue
                short, long = sorted((mine, self.folded(other.id)), key=len)
                if len(short) >= self.rules.copy_min_chars and short in long:
                    matches.add(other.id)
            found = self._copies[segment_id] = frozenset(matches)
        return found

    def headings(self) -> set[str]:
        if self._headings is None:
            self._headings = {
                s.id
                for s in self.source.segments
                if self.role(s.document) in self.rules.heading_roles and self._is_heading(s.id)
            }
        return self._headings

    def notes(self) -> set[str]:
        """Footnote blocks and the definitions section, neutral unless a card asks for them."""
        if self._notes is None:
            self._notes = self._footnote_blocks() | self._definition_sections()
        return self._notes

    def _segment(self, segment_id: str) -> Segment:
        return self._by_id[segment_id]

    def _is_heading(self, segment_id: str) -> bool:
        text = self.source.content(segment_id)
        if any(marker in text for marker in self.rules.guide_markers):
            return True
        return len(text) <= self.rules.heading_max_chars and not any(
            mark in text for mark in self.rules.sentence_terminators
        )

    def _footnote_blocks(self) -> set[str]:
        pages: dict[tuple[str, int], list[str]] = {}
        for s in self.source.segments:
            pages.setdefault((s.document, s.page), []).append(s.id)
        block: set[str] = set()
        for ids in pages.values():
            start = next((i for i, sid in enumerate(ids) if self._starts_footnote(sid)), None)
            if start is None:
                continue
            tail = ids[start:]
            if any(re.match(self.rules.clause_number_pattern, self._text(sid)) for sid in tail):
                continue  # the body resumes: not a page-final block of notes
            block.update(tail)
        return block

    def _starts_footnote(self, segment_id: str) -> bool:
        text = self._text(segment_id).lstrip()
        if not re.match(self.rules.footnote_start_pattern, text):
            return False
        body = re.sub(r"^\d{1,2}\s+", "", text)[: self.rules.footnote_body_chars]
        return re.search(self.rules.footnote_body_pattern, body) is not None

    def _definition_sections(self) -> set[str]:
        section: set[str] = set()
        inside = None
        for s in self.source.segments:
            if inside is not None and s.document != inside:
                inside = None
            word = self.rules.definition_heading_word
            if self._is_heading(s.id) and word in self.source.content(s.id):
                inside = s.document
            elif inside is not None and self._is_chapter(s.id):
                inside = None
            if inside is not None:
                section.add(s.id)
        return section

    def _is_chapter(self, segment_id: str) -> bool:
        """A chapter heading of any length (review R3): chapter pattern, no sentence terminator."""
        if re.match(self.rules.chapter_heading_pattern, self._squeezed(segment_id)) is None:
            return False
        return not any(mark in self._text(segment_id) for mark in self.rules.sentence_terminators)

    def _text(self, segment_id: str) -> str:
        return self._segment(segment_id).text

    def _squeezed(self, segment_id: str) -> str:
        return "".join(self._text(segment_id).split())


@lru_cache(maxsize=1)
def _definition_fields(markers: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        key
        for key, card in all_cards().items()
        if any(marker in str(card.get("includes", "")) for marker in markers)
    )


def neutral_segments(
    source: SegmentedSource | RuledSource,
    field_key: str,
    gold: Collection[str],
    rules: ScoringRules,
) -> set[str]:
    """Segments that count neither for nor against field_key under rules (S12a Spec §2)."""
    ruled = source if isinstance(source, RuledSource) else RuledSource(source, rules)
    neutral = set(ruled.headings())
    if field_key not in _definition_fields(rules.definition_card_markers):
        neutral |= ruled.notes()
    documents = {s.id: s.document for s in ruled.source.segments}
    if any(ruled.role(documents[sid]) == "terms" for sid in gold if sid in documents):
        neutral |= {sid for sid, doc in documents.items() if ruled.role(doc) == "brochure"}
    return neutral
