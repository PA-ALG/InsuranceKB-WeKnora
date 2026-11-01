"""Shared SK-2 test data (written by Claude): invented sales-method materials and a fake model.

Every material text below is invented for these tests; product names are public filed names. No
private sample text is used anywhere. Block IDs are never written by hand: they are found the way
SK-1 found them, by segmenting the material's pages, so the tests follow the real segmentation.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.compilers.methods.admission import CandidateFile
from insurance_harness.compilers.methods.compile import MethodRun, compile_methods
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.identity.method_signals import BLOCK_SCHEME, detect
from insurance_harness.ingest.method_use_model import MethodUse
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import ProductRegistry
from tests.ingest.method_helpers import DeckPages, deck_pages, source, v2

SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64

# A family-needs deck: two insurance categories; every block but the speaker line shows a method
# signal (SK-1 records only those blocks, and a method only ever cites recorded blocks).
DECK_A = (
    ("家庭保障需求销售方法", "主讲人：培训部"),
    ("讲解步骤一：了解客户家庭结构", "讲解步骤二：分析家庭责任与缺口"),
    ("讲解关键句：保障先于理财，先把风险管住", "话术注意事项：不要向客户承诺收益"),
    ("话术适用于重疾险与医疗险的家庭客户", "促成：约定下次见面时间"),
)
# A transfer deck: one category, a different method.
DECK_C = (
    ("医疗险转保沟通销售技巧", "转保前先核对客户现有保单"),
    ("讲解步骤：对比新旧保障差异", "讲解关键句：保障不中断才是关键"),
)
# A PDF method handbook: one plain page, one sentence per line.
PDF_A = (
    "家庭保障需求销售方法。\n话术适用于重疾险客户。\n"
    "讲解步骤一：了解客户家庭结构。\n讲解关键句：保障先于理财。\n",
)
METHOD_A = "家庭保障需求销售方法"
METHOD_C = "医疗险转保沟通销售技巧"


def pdf_pages(document: str, sha256: str, texts: Sequence[str]) -> list[PageText]:
    return [PageText(document, sha256, n, text) for n, text in enumerate(texts, 1)]


def block_of(pages: Sequence[PageText], needle: str) -> str:
    """The SK-1 block ID (`P<page>S<n>`) of the one segment holding `needle`."""
    segmented = SegmentedSource(pages)
    prefix = next(iter(segmented.document_ids.values()))
    found = [s.id.removeprefix(prefix) for s in segmented.segments if needle in s.text]
    assert len(found) == 1, (needle, found)
    return found[0]


def method_use(raw: RawSource, pages: Sequence[PageText], **override: Any) -> MethodUse:
    """The record SK-1 writes for a material, with the machine's labels (state active)."""
    hits = detect(pages)
    assert hits is not None
    fields: dict[str, Any] = {
        "knowledge_id": raw.knowledge_id,
        "parse_attempt": raw.parse_attempt,
        "sha256": raw.sha256,
        "file_name": raw.file_name,
        "block_scheme": BLOCK_SCHEME,
        "block_ids": hits.block_ids,
        "signals": hits.signals,
        "label_hits": hits.label_hits,
        "taxonomy_version": hits.taxonomy_version,
        "evidence_digest": hits.evidence_digest,
        "state": "active" if hits.labels else "awaiting_scope",
        "categories": hits.labels,
        "decided_by": "machine" if hits.labels else None,
    }
    fields.update(override)
    return MethodUse.model_validate(fields)


class World:
    """Materials, their pages, and a v2 registry holding their active method uses."""

    def __init__(self) -> None:
        self.raw_a = source("k-deck-a", "需求销售方法.pptx", SHA_A)
        self.raw_c = source("k-deck-c", "转保沟通.pptx", SHA_C)
        self.raw_p = source("k-pdf-a", "销售方法手册.pdf", SHA_B)
        self.decks: dict[str, list[PageText]] = {
            "k-deck-a": list(deck_pages(self.raw_a.file_name, SHA_A, DECK_A)),
            "k-deck-c": list(deck_pages(self.raw_c.file_name, SHA_C, DECK_C)),
            "k-pdf-a": pdf_pages(self.raw_p.file_name, SHA_B, PDF_A),
        }
        self.raws = {raw.knowledge_id: raw for raw in (self.raw_a, self.raw_c, self.raw_p)}
        self.reader = DeckPages(self.decks)
        self.registry: ProductRegistry = v2()
        self.registry.method_uses = [
            method_use(self.raw_a, self.decks["k-deck-a"]),
            method_use(self.raw_c, self.decks["k-deck-c"]),
            method_use(self.raw_p, self.decks["k-pdf-a"]),
        ]

    def block(self, knowledge_id: str, needle: str) -> str:
        return block_of(self.decks[knowledge_id], needle)

    def use(self, knowledge_id: str) -> MethodUse:
        return next(u for u in self.registry.method_uses if u.knowledge_id == knowledge_id)

    def add(
        self, knowledge_id: str, file_name: str, sha256: str, slides: Sequence[Sequence[str]]
    ) -> RawSource:
        """Another Office material with its active record."""
        raw = source(knowledge_id, file_name, sha256)
        self.decks[knowledge_id] = list(deck_pages(file_name, sha256, slides))
        self.reader.decks[knowledge_id] = self.decks[knowledge_id]
        self.raws[knowledge_id] = raw
        self.registry.method_uses.append(method_use(raw, self.decks[knowledge_id]))
        return raw

    def hits(self, knowledge_id: str) -> list[str]:
        """Every block SK-1 recorded for the material."""
        return list(self.use(knowledge_id).block_ids)

    def set_use(self, knowledge_id: str, **override: Any) -> None:
        """Replace a material's record, as SK-1 does when it is invalidated or relabelled."""
        raw = self.raws[knowledge_id]
        self.registry.method_uses = [
            method_use(raw, self.decks[knowledge_id], **override)
            if use.knowledge_id == knowledge_id
            else use
            for use in self.registry.method_uses
        ]


def copy_entry(
    raw: RawSource, copy_id: str | None = None, copy_sha: str | None = None
) -> dict[str, Any]:
    return {
        "copy_knowledge_id": copy_id or f"copy-{raw.knowledge_id}",
        "copy_sha256": copy_sha or raw.sha256,
        "knowledge_id": raw.knowledge_id,
        "parse_attempt": raw.parse_attempt,
        "sha256": raw.sha256,
    }


def candidate(
    name: str,
    raw: RawSource,
    blocks: Sequence[str],
    aliases: Sequence[str] = (),
    copy_id: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "aliases": list(aliases),
        "copy_knowledge_id": copy_id or f"copy-{raw.knowledge_id}",
        "block_ids": list(blocks),
    }


def candidate_file(
    copies: Sequence[Mapping[str, Any]], candidates: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "contract": "method-candidates.v1",
        "discovery_kb_id": "kb-methods",
        "copies": list(copies),
        "candidates": list(candidates),
    }


def candidates_of(
    world: World,
    items: Sequence[Mapping[str, Any]],
    copies: Sequence[Mapping[str, Any]] | None = None,
) -> CandidateFile:
    """A candidate file mapping every material of the world to its copy (unless `copies`)."""
    listed = [copy_entry(raw) for raw in world.raws.values()] if copies is None else copies
    return CandidateFile.model_validate_json(json.dumps(candidate_file(listed, items)))


Answer = Callable[[dict[str, Any]], dict[str, Any]]


class FakeModel:
    """A completion port answering each method's request with a canned response.

    `answers` maps a method name to a function of the request payload (so a response can name the
    paragraphs the request actually listed); a method without an answer gets an invalid response.
    Every request is recorded, so a test can check what was sent.
    """

    model = "fake-model"

    def __init__(self, answers: Mapping[str, Answer]) -> None:
        self.answers = dict(answers)
        self.requests: list[dict[str, Any]] = []
        self.sent: list[tuple[str, str, str]] = []  # (request digest, user payload, response)

    def complete(self, *, system: str, user: str) -> str:
        payload = json.loads(user)
        self.requests.append(payload)
        answer = self.answers.get(payload["method"]["name"])
        raw = json.dumps(answer(payload), ensure_ascii=False) if answer else "not json"
        digest = json.dumps([system, user], ensure_ascii=False, separators=(",", ":"))
        self.sent.append((hashlib.sha256(digest.encode("utf-8")).hexdigest(), user, raw))
        return raw


def paragraph_ref(payload: Mapping[str, Any], needle: str, material: str = "M1") -> str:
    """The paragraph ID (`M<n>P<page>S<n>`) of the one paragraph of `material` holding `needle`."""
    found = [
        ref
        for ref, text in (line.split(" ", 1) for line in payload["paragraphs"].splitlines())
        if ref.startswith(material + "P") and needle in text
    ]
    assert len(found) == 1, (needle, found)
    return found[0]


def full_answer(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A well-formed answer for DECK_A's method: every card filled from the listed paragraphs."""
    def ref(needle: str) -> str:
        return paragraph_ref(payload, needle, "M1")

    return {
        "predicates": [
            {
                "predicate": "method_summary",
                "state": "present",
                "items": [{"text": "按家庭结构分析保障需求", "refs": [ref("讲解步骤一")]}],
            },
            {
                "predicate": "method_steps",
                "state": "present",
                "items": [
                    {"text": "了解客户家庭结构", "refs": [ref("讲解步骤一")]},
                    {"text": "分析家庭责任与缺口", "refs": [ref("讲解步骤二")]},
                ],
            },
            {
                "predicate": "key_phrases",
                "state": "present",
                "items": [{"text": "保障先于理财，先把风险管住", "refs": [ref("讲解关键句")]}],
            },
            {
                "predicate": "applicable_scenario",
                "state": "present",
                "items": [{"text": "重疾险与医疗险的家庭客户", "refs": [ref("适用于")]}],
            },
            {
                "predicate": "cautions",
                "state": "present",
                "items": [{"text": "不要向客户承诺收益", "refs": [ref("注意事项")]}],
            },
        ],
        "labels": [{"label": "sales_stage:needs_analysis", "refs": [ref("讲解步骤一")]}],
    }


def unknown_answer(payload: Mapping[str, Any]) -> dict[str, Any]:
    cards = ("method_summary", "method_steps", "key_phrases", "applicable_scenario", "cautions")
    return {"predicates": [{"predicate": p, "state": "unknown"} for p in cards], "labels": []}


def compiled(
    world: World,
    items: Sequence[Mapping[str, Any]],
    model: "FakeModel",
    active: Release | None = None,
) -> MethodRun:
    """One offline run on the world's registry; the world takes the registry it writes back."""
    result = compile_methods(
        world.registry, candidates_of(world, items), pages=world.reader, port=model, active=active
    )
    world.registry = result.registry
    return result


def claims_of(bundle: CandidateBundle | None) -> dict[str, Claim]:
    """The bundle's claims by logical key."""
    members = bundle.members if bundle else []
    return {
        m.logical_slug: Claim.model_validate(m.payload) for m in members if m.kind == "claim"
    }


def release_from(
    bundle: CandidateBundle, base: Release | None = None, epoch: int = 1
) -> Release:
    """The Active release activating `bundle` on `base`: members by slug, removals dropped."""
    members = {m.logical_slug: m for m in (base.members if base else [])}
    for slug in bundle.removals:
        members.pop(slug, None)
    for member in bundle.members:
        members[member.logical_slug] = ReleaseMember(
            kind=member.kind,
            logical_slug=member.logical_slug,
            member_digest=member.member_digest,
            payload=member.payload,
            evidence_refs=member.evidence_refs,
            access_scope=member.access_scope,
        )
    return Release(id=f"rel-{epoch}", epoch=epoch, members=list(members.values()))
