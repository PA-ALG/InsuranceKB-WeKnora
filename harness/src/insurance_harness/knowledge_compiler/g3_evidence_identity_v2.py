"""Small deterministic supplements to captured G3 classifications.

No model result is rewritten. The v2 resolver derives a view from the original
source blocks; the compiler consumes that same view and keeps both documents'
evidence when a brochure is associated with its qualified terms.
"""
from __future__ import annotations

import re

from . import batch_entity_resolution_830_g3 as g
from .concept_free_wiki_830_g2 import evidence_for, verify_evidence
from .g3_title_routing import _LINE_LABELS
from insurance_harness.product.classify import detect_product_line

_ROWS = re.compile(r"(?m)^[ \t]*([A-Z0-9]+(?:/[A-Z0-9]+)*)[ \t]+([^\r\n]*保险[^\r\n]*)")
_ISSUER = re.compile(r"[\u4e00-\u9fff]{2,40}保险(?:集团)?股份有限公司")


def expand_directory(proposal, entry):
    if proposal.material_role != "product-list" or not any("险种代码" in b.text and "险种名称" in b.text for b in entry.blocks):
        return proposal
    blocks = sorted(entry.blocks,key=lambda b:(b.page_number,b.block_id))
    issuers = {}
    for block in blocks:
        for match in _ISSUER.finditer(block.text):
            issuers.setdefault(match.group(),evidence_for(block,match.start(),match.end()))
    if not issuers:
        for entity in proposal.entities:
            for row in proposal.evidence:
                if entity.issuer and row.purpose=="issuer" and row.entity_proposal_ref==entity.proposal_ref and g._normalized(entity.issuer) in g._normalized(row.evidence.quote):
                    verify_evidence(row.evidence,entry.blocks)
                    issuers.setdefault(entity.issuer,row.evidence)
    issuer = next(iter(issuers)) if len(issuers)==1 else None
    rows = [row for row in proposal.evidence if row.purpose=="material_role"]
    entities=[]; seen=set()
    for block in blocks:
        for match in _ROWS.finditer(block.text):
            code,name=match.group(1),match.group(2).strip()
            if (code,name) in seen: continue
            seen.add((code,name))
            evidence=evidence_for(block,match.start(),match.end())
            ref=g._batch_sha256("directory-row.830.g3.v2",{"material_id":entry.material_id,"revision_id":block.revision_id,"block_id":block.block_id,"start":evidence.start,"end":evidence.end})
            label=_LINE_LABELS.get(detect_product_line(name),"classification_unresolved")
            ids={}
            for purpose in ("name","product_code","classification"):
                eid=ref+"-"+purpose;ids[purpose]=eid
                rows.append(g.ProposalEvidenceV1(evidence_id=eid,entity_proposal_ref=ref,purpose=purpose,field_key=None,evidence=evidence))
            identity=[ids["name"],ids["product_code"]]
            if issuer is not None:
                eid=ref+"-issuer";identity.append(eid)
                rows.append(g.ProposalEvidenceV1(evidence_id=eid,entity_proposal_ref=ref,purpose="issuer",field_key=None,evidence=issuers[issuer]))
            entities.append(g.EntityProposalV1(proposal_ref=ref,issuer=issuer,name=name,product_code=code,version_label=None,filing_or_registration=None,identity_confidence="1.000000",identity_evidence_ids=tuple(sorted(identity)),labels=(g.LabelProposalV1(taxonomy_label=label,confidence="1.000000",evidence_ids=(ids["classification"],)),),primary_label=label,valid_from=None,valid_through=None))
    if not entities: return proposal
    return proposal.model_copy(update={"entities":tuple(sorted(entities,key=lambda row:row.proposal_ref)),"evidence":tuple(sorted(rows,key=lambda row:row.evidence_id))})


def same_classification(a,b):
    return (a.primary_label,a.schema_pack_id,a.schema_version,a.schema_pack_sha256)==(b.primary_label,b.schema_pack_id,b.schema_version,b.schema_pack_sha256)


def own_identity_supported(proposal, entity):
    # Full source and trust checks already ran in the resolver. Only missing
    # scalars may be filled from terms; every asserted scalar needs own evidence.
    values=[("issuer",entity.issuer),("name",entity.name),("product_code",entity.product_code),("version",entity.version_label)]
    if entity.filing_or_registration is not None:
        values.append(("version",entity.filing_or_registration.value))
    selected=set(entity.identity_evidence_ids)
    return all(value is None or any(row.evidence_id in selected and row.purpose==purpose and row.entity_proposal_ref==entity.proposal_ref and g._normalized(value) in g._normalized(row.evidence.quote) for row in proposal.evidence) for purpose,value in values)


def associate_brochures(decisions, proposals):
    by_material={row.material_id:row for row in proposals.proposals}
    terms=[]
    for parent in decisions:
        proposal=by_material[parent.material_id]
        if proposal.material_role!="terms": continue
        for child in parent.children:
            if child.disposition in ("MATCH","CREATE"):
                terms.append(child)
    result=[]
    allowed={"IDENTITY_EVIDENCE_MISSING","VERSION_UNRESOLVED","AMBIGUOUS_IDENTITY"}
    for parent in decisions:
        proposal=by_material[parent.material_id]
        if proposal.material_role!="brochure" or len(parent.children)!=1:
            result.append(parent);continue
        child=parent.children[0];entity=proposal.entities[0]
        if child.disposition!="NEEDS_CONFIRM" or not set(child.reason_codes)<=allowed or entity.issuer is None or entity.name is None or not own_identity_supported(proposal,entity):
            result.append(parent);continue
        targets={}
        for target in terms:
            a=target.anchors
            if a.issuer is None or a.name is None or a.product_code is None or a.version_anchor is None or a.version_label is None: continue
            if g._normalized(entity.issuer)!=a.issuer.normalized_value or g._normalized(entity.name)!=a.name.normalized_value or not same_classification(child.classification,target.classification):continue
            if entity.product_code is not None and g._normalized(entity.product_code)!=a.product_code.normalized_value:continue
            if entity.version_label is not None and g._normalized(entity.version_label)!=a.version_label.normalized_value:continue
            if entity.filing_or_registration is not None and (entity.filing_or_registration.kind,g._normalized(entity.filing_or_registration.value))!=(a.version_anchor.kind,a.version_anchor.normalized_value):continue
            key=(target.disposition,target.matched_entity_id,target.matched_entity_version,None if target.entity_candidate is None else target.entity_candidate.candidate_sha256)
            targets[key]=target
        if len(targets)!=1:
            result.append(parent);continue
        target=next(iter(targets.values()))
        values=child.model_dump(exclude={"decision_sha256"})
        values.update(disposition=target.disposition,matched_entity_id=target.matched_entity_id,matched_entity_version=target.matched_entity_version,entity_candidate=target.entity_candidate,anchors=target.anchors,reason_codes=target.reason_codes,queue_id=None,queue_owner=None)
        linked=g._hashed(g.EntityDecisionV1,object_type="entity-decision.830.g3.v1",hash_field="decision_sha256",payload=values)
        values=parent.model_dump(exclude={"decision_sha256"})
        values.update(disposition=target.disposition,children=(linked,),reason_codes=target.reason_codes,queue_id=None,queue_owner=None)
        result.append(g._hashed(g.MaterialDecisionV1,object_type="material-decision.830.g3.v1",hash_field="decision_sha256",payload=values))
    return tuple(result)
