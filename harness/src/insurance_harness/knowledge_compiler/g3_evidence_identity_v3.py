"""Joint product identity decisions from independently verified source rows.

Original proposals and evidence ownership are immutable. Only decision anchors
and their shared candidate are derived from complementary material claims.
"""

from __future__ import annotations

from collections import defaultdict

from . import batch_entity_resolution_830_g3 as g
from .g3_evidence_identity_v2 import own_identity_supported, same_classification

_ALLOWED = {
    "IDENTITY_EVIDENCE_MISSING",
    "VERSION_UNRESOLVED",
    "AMBIGUOUS_IDENTITY",
    "EXACT_EXISTING_MATCH",
    "NEW_ENTITY_CANDIDATE",
}
_SUCCESS = {"EXACT_EXISTING_MATCH", "NEW_ENTITY_CANDIDATE"}


def _child(child, policy, **updates):
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


def _nonempty(rows, key):
    return [getattr(row[2], key) for row in rows if getattr(row[2], key) is not None]


def _target(entity, existing):
    reasons = set()
    if g._has_existing_identity_competition(existing, entity):
        reasons.add("AMBIGUOUS_IDENTITY")
    matches = g._existing_matches(existing, entity)
    exact = None
    if matches:
        issuers = [m for m in matches if g._normalized(entity.issuer) == g._normalized(m.issuer)]
        if not issuers:
            reasons.add("IDENTITY_ANCHOR_CONFLICT")
        else:
            matches = [
                m
                for m in issuers
                if g._normalized(entity.name)
                in {g._normalized(m.name), *(g._normalized(a.value) for a in m.approved_aliases)}
                and g._normalized(entity.version_label) == g._normalized(m.version_label)
                and entity.filing_or_registration.kind == m.filing_or_registration.kind
                and g._normalized(entity.filing_or_registration.value)
                == g._normalized(m.filing_or_registration.value)
            ]
            if len(matches) != 1:
                reasons.add("AMBIGUOUS_IDENTITY")
            else:
                exact = matches[0]
    return reasons, exact


def associate_material_groups(decisions, proposals, corpus, existing, policy):
    parents = {p.material_id: p for p in decisions}
    entries = {e.material_id: e for e in corpus.entries}
    buckets = defaultdict(list)
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
        values = {
            key: _nonempty(rows, key)
            for key in (
                "issuer",
                "name",
                "product_code",
                "version_label",
                "filing_or_registration",
                "valid_from",
                "valid_through",
            )
        }
        conflicts = any(
            len(
                {
                    (v.kind, g._normalized(v.value))
                    if key == "filing_or_registration"
                    else g._normalized(v)
                    for v in vs
                }
            )
            > 1
            for key, vs in values.items()
        )
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
        if any(
            not values[key]
            for key in ("issuer", "product_code", "version_label", "filing_or_registration")
        ):
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
            update={key: vs[0] if vs else None for key, vs in values.items()}
        )
        reasons, target = _target(entity, existing)
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


def require_complete_support(resolution, selected_refs, proposals):
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
                and g._normalized(e.product_code) == child.anchors.product_code.normalized_value
                and e.filing_or_registration is not None
                and e.filing_or_registration.kind == child.anchors.version_anchor.kind
                and g._normalized(e.filing_or_registration.value)
                == child.anchors.version_anchor.normalized_value
                for e in by_material[mid].entities
            )
            for mid, ref in required
        ):
            raise ValueError("RESOLUTION_IDENTITY_SOURCE_REQUIRED")
