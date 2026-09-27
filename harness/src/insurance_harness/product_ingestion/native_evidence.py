"""Apply the existing PDF locator to admitted knowledge without changing its text."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput, free_page_id
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    Evidence,
    FreeWikiPage,
)
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.source_geometry import (
    prepare_evidence_locations,
    project_evidence_locations,
)

Member = TypeVar("Member", ConceptDefinition, FreeWikiPage)


@dataclass(frozen=True, slots=True)
class LocatedNativeEvidence:
    output: CompileOutput
    locations: tuple[dict[str, Any], ...]


def locate_native_evidence(
    output: CompileOutput,
    sources: Mapping[str, DecodedSourceSnapshot],
) -> LocatedNativeEvidence:
    """Require exact native geometry and preserve each segment's evidence relation.

    Inputs are already verified source snapshots. Audit records retain original
    quote identity and page-gap whitespace; nothing here calls a model or stores
    a candidate. The independent review must bind the returned final output.
    """
    if output.fields:
        raise ValueError("native evidence adapter cannot modify fields")
    evidence_by_source: dict[str, list[Evidence]] = {}
    members: tuple[ConceptDefinition | FreeWikiPage, ...] = (*output.definitions, *output.pages)
    for member in members:
        if member.content_provenance is None:
            raise ValueError("native knowledge must declare content provenance")
        for evidence in member.evidence:
            evidence_by_source.setdefault(evidence.knowledge_id, []).append(evidence)
    if not evidence_by_source.keys() <= sources.keys():
        raise ValueError("native evidence source snapshot missing")
    indexes = {
        key: prepare_evidence_locations(sources[key], evidence)
        for key, evidence in evidence_by_source.items()
    }
    locations: list[dict[str, Any]] = []

    def locate(member: Member) -> Member:
        assert member.content_provenance is not None
        evidence: list[Evidence] = []
        remap: dict[int, tuple[int, ...]] = {}
        for index, original in enumerate(member.evidence):
            parts, audit = project_evidence_locations(
                original,
                sources[original.knowledge_id],
                page_index=indexes[original.knowledge_id],
            )
            mapped = []
            for part in parts:
                if part not in evidence:
                    evidence.append(part)
                mapped.append(evidence.index(part))
            remap[index] = tuple(mapped)
            locations.append(
                {
                    "member_id": member.concept_id
                    if isinstance(member, ConceptDefinition)
                    else free_page_id(member),
                    "original_evidence_index": index,
                    "evidence_indexes": list(remap[index]),
                    **audit,
                }
            )
        provenance = member.content_provenance.model_dump(mode="json")
        for segment in provenance["segments"]:
            segment["evidence_indexes"] = sorted(
                {
                    replacement
                    for index in segment["evidence_indexes"]
                    for replacement in remap[index]
                }
            )
        return type(member).model_validate(
            {
                **member.model_dump(mode="json"),
                "evidence": evidence,
                "content_provenance": provenance,
            }
        )

    result = CompileOutput.model_validate(
        {
            **output.model_dump(mode="json"),
            "definitions": tuple(locate(member) for member in output.definitions),
            "pages": tuple(locate(member) for member in output.pages),
        }
    )
    return LocatedNativeEvidence(result, tuple(locations))
