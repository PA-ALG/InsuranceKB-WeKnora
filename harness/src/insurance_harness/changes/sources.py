"""Keep published segment pointers in the material order used by compilation."""

import re

from insurance_harness.ingest.source_map import SourceEntry

_LOCAL_FILE = re.compile(r"file:[0-9a-fA-F]{64}")


def publication_entries(
    entries: list[SourceEntry],
    materials: list[str] | None,
) -> list[SourceEntry]:
    # Legacy and local-file outputs predate canonical source-map ordering. Their D1/D2
    # pointers still refer to the supplied map order, so only revision-aware outputs sort.
    if materials is None or any(_LOCAL_FILE.fullmatch(identity) for identity in materials):
        return entries
    return sorted(entries, key=lambda entry: (entry.knowledge_id, entry.parse_attempt))
