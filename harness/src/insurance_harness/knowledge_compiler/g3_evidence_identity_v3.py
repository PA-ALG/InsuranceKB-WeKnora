"""Joint product identity decisions from independently verified source rows.

Original proposals and evidence ownership are immutable. Only decision anchors
and their shared candidate are derived from complementary material claims.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from . import batch_entity_resolution_830_g3 as g
from .g3_evidence_identity_v2 import own_identity_supported, same_classification

IdentityRow = tuple[g.MaterialProposalV1, g.EntityDecisionV1, g.EntityProposalV1]

_ALLOWED = {
    "IDENTITY_EVIDENCE_MISSING",
    "VERSION_UNRESOLVED",
    "AMBIGUOUS_IDENTITY",
    "EXACT_EXISTING_MATCH",
    "NEW_ENTITY_CANDIDATE",
}
_SUCCESS = {"EXACT_EXISTING_MATCH", "NEW_ENTITY_CANDIDATE"}


def _child(
    child: g.EntityDecisionV1,
    policy: g.BatchResolutionPolicyV1,
    **updates: object,
) -> g.EntityDecisionV1:
    payload = child.model_dump(exclude={"decision_sha256"})
    payload.update(updates)
    human = payload["disposition"] in ("NEEDS_CONFIRM", "QUARANTINE")
    payload.update(
        queue_id=policy.queue_id if human else None,
        queue_owner=policy.queue_owner if human else None,
    )
    return g._hashed(
        g.EntityDecisionV1,
        object_type="entity-decision.830.g3.v1",
        hash_field="decision_sha256",
        payload=payload,
    )


def _target(
    entity: g.EntityProposalV1,
    existing: g.ExistingEntitySnapshotV1,
    policy: g.BatchResolutionPolicyV1,
) -> tuple[set[str], g.ExistingEntityV1 | None]:
    issuer = entity.issuer
    name = entity.name
    version_label = entity.version_label
    filing = entity.filing_or_registration
    if issuer is None or name is None or version_label is None or filing is None:
        raise ValueError("joint identity target is incomplete")
    reasons: set[str] = set()
    if g._has_existing_identity_competition(existing, entity):
        reasons.add("AMBIGUOUS_IDENTITY")
    matches = list(g._existing_matches(existing, entity))
    exact = None
    if matches:
        issuers = [
            m
            for m in matches
            if g._normalized(policy.canonical_issuer(issuer, existing.space_id))
            == g._normalized(policy.canonical_issuer(m.issuer, existing.space_id))
        ]
        if not issuers:
            reasons.add("IDENTITY_ANCHOR_CONFLICT")
        else:
            matches = [
                m
                for m in issuers
                if g._normalized(name)
                in {g._normalized(m.name), *(g._normalized(a.value) for a in m.approved_aliases)}
                and g._normalized(version_label) == g._normalized(m.version_label)
                and filing.kind == m.filing_or_registration.kind
                and g._normalized(filing.value) == g._normalized(m.filing_or_registration.value)
            ]
            if len(matches) != 1:
                reasons.add("AMBIGUOUS_IDENTITY")
            else:
                exact = matches[0]
    return reasons, exact


def associate_material_groups(
    decisions: tuple[g.MaterialDecisionV1, ...],
    proposals: g.ProposalBatchV1,
    corpus: g.BatchCorpusV1,
    existing: g.ExistingEntitySnapshotV1,
    policy: g.BatchResolutionPolicyV1,
) -> tuple[g.MaterialDecisionV1, ...]:
    parents = {p.material_id: p for p in decisions}
    entries = {e.material_id: e for e in corpus.entries}
    buckets: defaultdict[str, list[IdentityRow]] = defaultdict(list)
    for proposal in proposals.proposals:
        parent = parents[proposal.material_id]
        for entity, child in zip(proposal.entities, parent.children, strict=True):
            if entity.name is not None:
                buckets[g._normalized(entity.name)].append((proposal, child, entity))
    for rows in buckets.values():
        rows.sort(key=lambda row: (row[0].material_id, row[2].proposal_ref))
        if any(
            len(p.entities) != 1
            or p.material_role not in {"terms", "brochure", "rate-table", "rate_table"}
            or not set(c.reason_codes) <= _ALLOWED
            or not own_identity_supported(p, e)
            for p, c, e in rows
        ):
            continue
        string_values: dict[str, list[str]] = {
            "issuer": [e.issuer for _, _, e in rows if e.issuer is not None],
            "name": [e.name for _, _, e in rows if e.name is not None],
            "product_code": [e.product_code for _, _, e in rows if e.product_code is not None],
            "version_label": [e.version_label for _, _, e in rows if e.version_label is not None],
            "valid_from": [e.valid_from for _, _, e in rows if e.valid_from is not None],
            "valid_through": [e.valid_through for _, _, e in rows if e.valid_through is not None],
        }
        anchor_values = [
            entity.filing_or_registration
            for _, _, entity in rows
            if entity.filing_or_registration is not None
        ]
        issuer_values = [
            policy.canonical_issuer(value, corpus.space_id) for value in string_values["issuer"]
        ]
        string_values["issuer"] = issuer_values
        conflicts = any(
            len({g._normalized(value) for value in values}) > 1 for values in string_values.values()
        )
        conflicts |= len({(v.kind, g._normalized(v.value)) for v in anchor_values}) > 1
        conflicts |= any(
            not same_classification(rows[0][1].classification, c.classification) for _, c, _ in rows
        )
        if conflicts:
            for proposal, child, _ in rows:
                changed = _child(
                    child,
                    policy,
                    disposition="NEEDS_CONFIRM",
                    matched_entity_id=None,
                    matched_entity_version=None,
                    entity_candidate=None,
                    reason_codes=tuple(
                        sorted((set(child.reason_codes) - _SUCCESS) | {"AMBIGUOUS_IDENTITY"})
                    ),
                )
                parents[proposal.material_id] = g._material_decision(
                    entry=entries[proposal.material_id],
                    proposal=proposal,
                    children=(changed,),
                    policy=policy,
                    reasons=set(),
                )
            continue
        required_strings = ("issuer", "product_code", "version_label")
        if any(not string_values[key] for key in required_strings) or not anchor_values:
            continue
        if not any(
            p.material_role == "terms"
            and e.product_code is not None
            and e.filing_or_registration is not None
            for p, _, e in rows
        ):
            continue
        # This transient scalar carrier is never emitted as a MaterialProposal.
        entity = rows[0][2].model_copy(
            update={
                **{key: values[0] if values else None for key, values in string_values.items()},
                "filing_or_registration": anchor_values[0] if anchor_values else None,
            }
        )
        reasons, target = _target(entity, existing, policy)
        candidate = None
        if not reasons and target is None:
            candidate = g._candidate(
                space_id=corpus.space_id,
                entity=entity,
                evidence_ids=tuple(
                    sorted({eid for _, _, e in rows for eid in e.identity_evidence_ids})
                ),
            )
        disposition = (
            "QUARANTINE"
            if "IDENTITY_ANCHOR_CONFLICT" in reasons
            else "NEEDS_CONFIRM"
            if reasons
            else "MATCH"
            if target is not None
            else "CREATE"
        )
        if not reasons:
            reasons.add("EXACT_EXISTING_MATCH" if target is not None else "NEW_ENTITY_CANDIDATE")
        for proposal, child, _ in rows:
            changed = _child(
                child,
                policy,
                disposition=disposition,
                matched_entity_id=target.entity_id
                if target is not None and disposition == "MATCH"
                else None,
                matched_entity_version=target.entity_version
                if target is not None and disposition == "MATCH"
                else None,
                entity_candidate=candidate if disposition == "CREATE" else None,
                anchors=g._anchors(entity),
                reason_codes=tuple(sorted(reasons)),
                **(
                    {"multi_identity_name_evidence_ids": (), "multi_identity_code_evidence_ids": ()}
                    if disposition == "QUARANTINE"
                    else {}
                ),
            )
            parents[proposal.material_id] = g._material_decision(
                entry=entries[proposal.material_id],
                proposal=proposal,
                children=(changed,),
                policy=policy,
                reasons=set(),
            )
    return tuple(parents[p.material_id] for p in decisions)


def require_complete_support(
    resolution: g.BatchEntityResolutionV1,
    selected_refs: Iterable[tuple[str, str]],
    proposals: g.ProposalBatchV1,
) -> None:
    """A linked decision cannot publish after omitting its supporting material."""
    selected = set(selected_refs)
    rows = [
        (p.material_id, c)
        for p in resolution.decisions
        for c in p.children
        if c.disposition in {"MATCH", "CREATE"}
    ]
    for material_id, child in rows:
        if (material_id, child.proposal_ref) not in selected:
            continue
        product_code = child.anchors.product_code
        version_anchor = child.anchors.version_anchor
        if product_code is None or version_anchor is None:
            raise ValueError("RESOLUTION_IDENTITY_SOURCE_REQUIRED")
        required = {
            (mid, other.proposal_ref)
            for mid, other in rows
            if other.anchors == child.anchors
            and same_classification(other.classification, child.classification)
            and other.disposition == child.disposition
            and other.matched_entity_id == child.matched_entity_id
            and other.matched_entity_version == child.matched_entity_version
            and other.entity_candidate == child.entity_candidate
        }
        if not required <= selected:
            raise ValueError("RESOLUTION_IDENTITY_SOURCE_REQUIRED")

        by_material = {p.material_id: p for p in proposals.proposals}
        if not any(
            by_material[mid].material_role == "terms"
            and any(
                e.proposal_ref == ref
                and e.product_code is not None
                and g._normalized(e.product_code) == product_code.normalized_value
                and e.filing_or_registration is not None
                and e.filing_or_registration.kind == version_anchor.kind
                and g._normalized(e.filing_or_registration.value) == version_anchor.normalized_value
                for e in by_material[mid].entities
            )
            for mid, ref in required
        ):
            raise ValueError("RESOLUTION_IDENTITY_SOURCE_REQUIRED")
