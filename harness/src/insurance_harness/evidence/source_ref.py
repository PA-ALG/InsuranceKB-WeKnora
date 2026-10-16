"""The fixed source revision evidence cites (S4c-2a Spec §3.2, S4g).

A reference names one parse attempt of one WeKnora knowledge item and the file fingerprint it
was parsed from: ``source:v1:<knowledge_id>:<parse_attempt>:<file_sha256>``. The platform
resolves it only within the request's Space and only to that exact attempt and fingerprint.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRevision:
    """The platform's fixed source revision a document's pages were read from."""

    knowledge_id: str
    parse_attempt: int

    def ref(self, file_sha256: str) -> str:
        return f"source:v1:{self.knowledge_id}:{self.parse_attempt}:{file_sha256}"
