"""Fail-closed KnowledgeScope guards for WeKnora read responses."""

from insurance_harness.adapters.weknora.models import WeKnoraChunk, WeKnoraKnowledge
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    is_database_bound_scope,
)

_SCOPE_ERROR = "scope mismatch"


def require_bound_scope(scope: KnowledgeScope) -> None:
    """Reject forged or incomplete scopes before any external request."""
    if not is_database_bound_scope(scope):
        raise ScopeViolation(_SCOPE_ERROR)
    identifiers = (
        getattr(scope, "space_id", None),
        getattr(scope, "tenant_id", None),
        getattr(scope, "raw_kb_id", None),
        getattr(scope, "wiki_kb_id", None),
    )
    if any(not isinstance(value, str) or not value.strip() for value in identifiers):
        raise ScopeViolation(_SCOPE_ERROR)


def require_knowledge_scope(
    scope: KnowledgeScope,
    knowledge: WeKnoraKnowledge,
    knowledge_id: str,
) -> None:
    """Ensure a knowledge metadata response belongs to the requested raw KB."""
    require_bound_scope(scope)
    if not _identity_matches(getattr(knowledge, "id", None), knowledge_id):
        raise ScopeViolation(_SCOPE_ERROR)
    if not _identity_matches(getattr(knowledge, "tenant_id", None), scope.tenant_id):
        raise ScopeViolation(_SCOPE_ERROR)
    if not _identity_matches(
        getattr(knowledge, "knowledge_base_id", None), scope.raw_kb_id
    ):
        raise ScopeViolation(_SCOPE_ERROR)


def require_chunk_scope(
    scope: KnowledgeScope,
    chunk: WeKnoraChunk,
    knowledge_id: str,
) -> None:
    """Ensure a chunk is anchored to the requested knowledge and raw KB."""
    require_bound_scope(scope)
    if not _identity_matches(getattr(chunk, "tenant_id", None), scope.tenant_id):
        raise ScopeViolation(_SCOPE_ERROR)
    if not _identity_matches(getattr(chunk, "knowledge_id", None), knowledge_id):
        raise ScopeViolation(_SCOPE_ERROR)
    if not _identity_matches(
        getattr(chunk, "knowledge_base_id", None), scope.raw_kb_id
    ):
        raise ScopeViolation(_SCOPE_ERROR)


def scope_log_context(scope: KnowledgeScope) -> dict[str, str]:
    """Return the allow-listed scope identifiers safe for logs and manifests."""
    require_bound_scope(scope)
    return {
        "space_id": scope.space_id,
        "tenant_id": scope.tenant_id,
        "raw_kb_id": scope.raw_kb_id,
    }


def _identity_matches(value: object, expected: str) -> bool:
    return type(value) in (str, int) and str(value) == expected
