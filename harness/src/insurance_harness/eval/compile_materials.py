"""Input identities of a compile: the materials an output was written from (S8a).

A material is ``<knowledge_id>:<parse_attempt>:<sha256>`` for platform revisions, or
``file:<sha256>`` for local files; an output may stand in for a compile only on the same list.
"""

import re
from collections.abc import Mapping, Sequence

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.source_map import SourceEntry

_MATERIAL = re.compile(r"(?:file|[A-Za-z0-9][A-Za-z0-9_-]{0,127}:[1-9][0-9]*):[0-9a-f]{64}")


def validate_materials(materials: list[str] | None) -> None:
    if materials is None:
        return
    revisions = [tuple(m.split(":")[:2]) for m in materials if m.count(":") == 2]
    if (
        materials != sorted(materials) or any(not _MATERIAL.fullmatch(m) for m in materials)
        or (revisions and (len(revisions) != len(materials)
                           or len(set(revisions)) != len(revisions)))
    ):
        raise ValueError("invalid stored material identities")


def material_identities(
    pages: Sequence[PageText], headers: Mapping[str, Sequence[PageText]] | None,
    revisions: Mapping[str, SourceRevision] | None,
) -> list[str]:
    # Validate before reuse too: duplicate pages, fingerprints or evidence roles are ambiguous.
    source = SegmentedSource(pages, table_headers=headers)
    documents = {page.document: page.document_sha256.lower() for page in source.pages}
    if not documents or (revisions is not None and set(revisions) != set(documents)):
        raise ValueError("missing or ambiguous source identities")
    materials = []
    identities = set()
    for document, digest in documents.items():
        if revisions is None:
            materials.append(f"file:{digest}")
            continue
        revision = revisions[document]
        entry = SourceEntry(
            knowledge_id=revision.knowledge_id, parse_attempt=revision.parse_attempt,
        )
        identity = (entry.knowledge_id, entry.parse_attempt)
        if identity in identities:
            raise ValueError("ambiguous source identities")
        identities.add(identity)
        materials.append(f"{entry.knowledge_id}:{entry.parse_attempt}:{digest}")
    return sorted(materials)
