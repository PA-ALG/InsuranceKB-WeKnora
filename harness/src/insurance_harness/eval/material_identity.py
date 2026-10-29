"""The input identity of a compile output (S8a, S5b-6): each material's fixed revision and
file fingerprint, and the role it was read under. An output stands in for a compile only while
both match, so a new revision, file or recorded role always recompiles."""

import re
from collections.abc import Mapping, Sequence

from insurance_harness.catalog.trust_policy import TrustedPages
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.identity.material_roles import document_roles
from insurance_harness.ingest.source_map import SourceEntry

_MATERIAL = re.compile(r"(?:file|[A-Za-z0-9][A-Za-z0-9_-]{0,127}:[1-9][0-9]*):[0-9a-f]{64}")


def validate_materials(materials: list[str] | None) -> None:
    if materials is None:
        return
    revisions = [tuple(m.split(":")[:2]) for m in materials if m.count(":") == 2]
    if (
        materials != sorted(materials)
        or any(not _MATERIAL.fullmatch(m) for m in materials)
        or (
            revisions
            and (len(revisions) != len(materials) or len(set(revisions)) != len(revisions))
        )
    ):
        raise ValueError("invalid stored material identities")


def material_identities(
    pages: Sequence[PageText],
    headers: Mapping[str, Sequence[PageText]] | None,
    revisions: Mapping[str, SourceRevision] | None,
) -> list[tuple[str, str]]:
    """Each input document's material identity and name, identities sorted."""
    # Validate before reuse too: duplicate pages, fingerprints or evidence roles are ambiguous.
    source = SegmentedSource(pages, table_headers=headers)
    documents = {page.document: page.document_sha256.lower() for page in source.pages}
    if not documents or (revisions is not None and set(revisions) != set(documents)):
        raise ValueError("missing or ambiguous source identities")
    materials = []
    identities = set()
    for document, digest in documents.items():
        if revisions is None:
            materials.append((f"file:{digest}", document))
            continue
        revision = revisions[document]
        entry = SourceEntry(
            knowledge_id=revision.knowledge_id,
            parse_attempt=revision.parse_attempt,
        )
        identity = (entry.knowledge_id, entry.parse_attempt)
        if identity in identities:
            raise ValueError("ambiguous source identities")
        identities.add(identity)
        materials.append((f"{entry.knowledge_id}:{entry.parse_attempt}:{digest}", document))
    return sorted(materials)


def document_role_map(read: list[PageText] | TrustedPages[PageText]) -> Mapping[str, str | None]:
    """Each read document's role: as the read decided it (recorded or inferred), else inferred."""
    return read.roles if isinstance(read, TrustedPages) else document_roles(read)


def effective_roles(
    materials: Sequence[tuple[str, str]],
    read: list[PageText] | TrustedPages[PageText],
) -> dict[str, str]:
    """Each material identity's effective role (S5b-6): as the read decided it, or as inferred for
    plain evidence pages. Pages a caller supplies without any role decision record none; local
    files with identical bytes share one identity, so their distinct roles are joined."""
    known = document_role_map(read)
    roles: dict[str, set[str]] = {}
    for identity, document in materials:
        role = known.get(document)
        if role is not None:
            roles.setdefault(identity, set()).add(role)
    return {identity: "+".join(sorted(found)) for identity, found in roles.items()}
