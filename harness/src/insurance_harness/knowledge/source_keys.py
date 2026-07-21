"""Neutral deterministic source-key derivation shared by lifecycle entry points."""

import hashlib


def derive_retract_event_key(knowledge_id: str, event_revision: str) -> str:
    """Return the reserved 64-character revision for one deletion event."""

    digest = hashlib.sha256(
        f"{knowledge_id}\0{event_revision}".encode()
    ).hexdigest()
    return f"retract:{digest[:56]}"
