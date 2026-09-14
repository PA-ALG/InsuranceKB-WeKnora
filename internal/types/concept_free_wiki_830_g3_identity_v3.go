package types

import (
	"reflect"
	"sort"
)

const evidenceIdentityCompilerV3_830G3 = "batch-entity-resolution-compiler.830.g3.v3"

type jointIdentityRowV3_830G3 struct {
	parent   int
	child    int
	proposal MaterialProposal830G3
	entity   EntityProposal830G3
}

// Only a derived decision receives the joint anchors. Original proposals and
// evidence keep their own material, revision and locator throughout replay.
func associateEvidenceV3_830G3(decisions []MaterialDecision830G3, proposals ProposalBatch830G3, existing ExistingEntitySnapshot830G3, policy BatchResolutionPolicy830G3) ([]MaterialDecision830G3, error) {
	byMaterial := map[string]MaterialProposal830G3{}
	for _, proposal := range proposals.Proposals {
		byMaterial[proposal.MaterialID] = proposal
	}
	groups := map[string][]jointIdentityRowV3_830G3{}
	for i, parent := range decisions {
		proposal := byMaterial[parent.MaterialID]
		for j, child := range parent.Children {
			for _, entity := range proposal.Entities {
				if entity.ProposalRef == child.ProposalRef && entity.Name != nil {
					name := normalizedIdentity830G3(*entity.Name)
					groups[name] = append(groups[name], jointIdentityRowV3_830G3{i, j, proposal, entity})
				}
			}
		}
	}
	result := append([]MaterialDecision830G3(nil), decisions...)
	for _, group := range groups {
		sort.Slice(group, func(i, j int) bool {
			if group[i].proposal.MaterialID == group[j].proposal.MaterialID {
				return group[i].entity.ProposalRef < group[j].entity.ProposalRef
			}
			return group[i].proposal.MaterialID < group[j].proposal.MaterialID
		})
		eligible := true
		for _, row := range group {
			child := decisions[row.parent].Children[row.child]
			if len(row.proposal.Entities) != 1 || len(decisions[row.parent].Children) != 1 ||
				(row.proposal.MaterialRole != "terms" && row.proposal.MaterialRole != "brochure" && row.proposal.MaterialRole != "rate-table" && row.proposal.MaterialRole != "rate_table") ||
				!ownIdentitySupportedV2_830G3(row.proposal, row.entity) {
				eligible = false
			}
			for _, reason := range child.ReasonCodes {
				if reason != "IDENTITY_EVIDENCE_MISSING" && reason != "VERSION_UNRESOLVED" && reason != "AMBIGUOUS_IDENTITY" && reason != "EXACT_EXISTING_MATCH" && reason != "NEW_ENTITY_CANDIDATE" {
					eligible = false
				}
			}
		}
		if !eligible {
			continue
		}
		merged := group[0].entity
		merged.Issuer, merged.ProductCode, merged.VersionLabel, merged.FilingOrRegistration = nil, nil, nil, nil
		merged.ValidFrom, merged.ValidThrough = nil, nil
		conflict := false
		firstClass := decisions[group[0].parent].Children[group[0].child].Classification
		ids := []string{}
		for _, row := range group {
			for _, values := range []struct {
				dst **string
				src *string
			}{{&merged.Issuer, row.entity.Issuer}, {&merged.ProductCode, row.entity.ProductCode}, {&merged.VersionLabel, row.entity.VersionLabel}, {&merged.ValidFrom, row.entity.ValidFrom}, {&merged.ValidThrough, row.entity.ValidThrough}} {
				if values.src == nil {
					continue
				}
				if *values.dst == nil {
					*values.dst = values.src
				} else if normalizedIdentity830G3(**values.dst) != normalizedIdentity830G3(*values.src) {
					conflict = true
				}
			}
			if anchor := row.entity.FilingOrRegistration; anchor != nil {
				if merged.FilingOrRegistration == nil {
					merged.FilingOrRegistration = anchor
				} else if anchor.Kind != merged.FilingOrRegistration.Kind || normalizedIdentity830G3(anchor.Value) != normalizedIdentity830G3(merged.FilingOrRegistration.Value) {
					conflict = true
				}
			}
			if !sameClassificationV2_830G3(firstClass, decisions[row.parent].Children[row.child].Classification) {
				conflict = true
			}
			ids = append(ids, row.entity.IdentityEvidenceIDs...)
		}
		if conflict {
			for _, row := range group {
				child := decisions[row.parent].Children[row.child]
				reasons := map[string]bool{"AMBIGUOUS_IDENTITY": true}
				for _, reason := range child.ReasonCodes {
					if reason != "EXACT_EXISTING_MATCH" && reason != "NEW_ENTITY_CANDIDATE" {
						reasons[reason] = true
					}
				}
				child.Disposition = "NEEDS_CONFIRM"
				child.MatchedEntityID, child.MatchedEntityVersion, child.EntityCandidate = nil, nil, nil
				child.ReasonCodes = sortedReasonCodes830G3(reasons)
				queue, owner := policy.QueueID, policy.QueueOwner
				child.QueueID, child.QueueOwner = &queue, &owner
				child.DecisionSHA256, _ = batchConceptHashWithout830G3("entity-decision.830.g3.v1", child, "decision_sha256")
				result[row.parent] = jointParentV3_830G3(decisions[row.parent], child, policy)
			}
			continue
		}
		if merged.Issuer == nil || merged.ProductCode == nil || merged.VersionLabel == nil || merged.FilingOrRegistration == nil {
			continue
		}
		termsSupport := false
		for _, row := range group {
			entity := row.entity
			if row.proposal.MaterialRole == "terms" && entity.ProductCode != nil && entity.FilingOrRegistration != nil &&
				normalizedIdentity830G3(*entity.ProductCode) == normalizedIdentity830G3(*merged.ProductCode) && entity.FilingOrRegistration.Kind == merged.FilingOrRegistration.Kind && normalizedIdentity830G3(entity.FilingOrRegistration.Value) == normalizedIdentity830G3(merged.FilingOrRegistration.Value) {
				termsSupport = true
			}
		}
		if !termsSupport {
			continue
		}
		sort.Strings(ids)
		ids = uniqueStrings830G3(ids)
		anchors := expectedAnchors830G3(merged)
		key, err := entityKey830G3(existing.SpaceID, *merged.ProductCode)
		if err != nil {
			return nil, err
		}
		version, err := entityVersionKey830G3(key, merged)
		if err != nil {
			return nil, err
		}
		candidate := EntityCandidate830G3{Contract: "entity-candidate.830.g3.v1", CandidateID: "entity_candidate_" + version, EntityKeySHA256: key, VersionCandidateKeySHA256: version, Issuer: *anchors.Issuer, Name: *anchors.Name, ProductCode: *anchors.ProductCode, VersionLabel: *anchors.VersionLabel, VersionAnchor: *anchors.VersionAnchor, EvidenceIDs: ids, Status: "NOT_ACTIVE"}
		candidate.CandidateSHA256, _ = batchConceptHashWithout830G3(candidate.Contract, candidate, "candidate_sha256")
		for _, row := range group {
			original := decisions[row.parent].Children[row.child]
			view := merged
			view.ProposalRef, view.IdentityConfidence, view.IdentityEvidenceIDs, view.Labels = row.entity.ProposalRef, row.entity.IdentityConfidence, row.entity.IdentityEvidenceIDs, row.entity.Labels
			reasons := map[string]bool{}
			if identityCompetition830G3(existing, view) {
				reasons["AMBIGUOUS_IDENTITY"] = true
			}
			child, err := expectedEntityDecision830G3(resolutionRow830G3{Entity: view, Reasons: reasons, Classification: original.Classification, MultiName: original.MultiIdentityNameEvidenceIDs, MultiCode: original.MultiIdentityCodeEvidenceIDs, Candidate: &candidate}, existing, policy)
			if err != nil {
				return nil, err
			}
			result[row.parent] = jointParentV3_830G3(decisions[row.parent], child, policy)
		}
	}
	return result, nil
}

func jointParentV3_830G3(parent MaterialDecision830G3, child EntityDecision830G3, policy BatchResolutionPolicy830G3) MaterialDecision830G3 {
	parent.Children = []EntityDecision830G3{child}
	parent.Disposition = child.Disposition
	reasons := map[string]bool{}
	for _, reason := range parent.ReasonCodes {
		if reason != "NEW_ENTITY_CANDIDATE" && reason != "EXACT_EXISTING_MATCH" {
			reasons[reason] = true
		}
	}
	parent.QueueID, parent.QueueOwner = nil, nil
	if child.Disposition == "CREATE" {
		reasons["NEW_ENTITY_CANDIDATE"] = true
	} else if child.Disposition == "MATCH" {
		reasons["EXACT_EXISTING_MATCH"] = true
	} else {
		queue, owner := policy.QueueID, policy.QueueOwner
		parent.QueueID, parent.QueueOwner = &queue, &owner
	}
	parent.ReasonCodes = sortedReasonCodes830G3(reasons)
	parent.DecisionSHA256, _ = batchConceptHashWithout830G3("material-decision.830.g3.v1", parent, "decision_sha256")
	return parent
}

// The binding must retain every contributing material, including issuer-only
// support and matches to existing entities (which have no candidate object).
func validateJointBindingSupportV3_830G3(binding EntityCompileBinding830G3, resolution BatchEntityResolution830G3, proposals map[string]MaterialProposal830G3) error {
	refs := map[string]bool{}
	for _, ref := range binding.ResolutionRefs {
		refs[ref.MaterialID+"\x00"+ref.ProposalRef] = true
	}
	var target *EntityDecision830G3
	for _, parent := range resolution.Decisions {
		for _, child := range parent.Children {
			if refs[parent.MaterialID+"\x00"+child.ProposalRef] {
				copy := child
				target = &copy
				break
			}
		}
	}
	if target == nil {
		return ErrConceptCandidateBundle830G3
	}
	termsSupport := false
	for _, parent := range resolution.Decisions {
		for _, child := range parent.Children {
			if child.Disposition != target.Disposition || !reflect.DeepEqual(child.Anchors, target.Anchors) || !sameClassificationV2_830G3(child.Classification, target.Classification) || !optionalStringEqualV2_830G3(child.MatchedEntityID, target.MatchedEntityID) || !optionalStringEqualV2_830G3(child.MatchedEntityVersion, target.MatchedEntityVersion) || !reflect.DeepEqual(child.EntityCandidate, target.EntityCandidate) {
				continue
			}
			if !refs[parent.MaterialID+"\x00"+child.ProposalRef] {
				return ErrConceptCandidateBundle830G3
			}
			p := proposals[parent.MaterialID]
			if p.MaterialRole != "terms" {
				continue
			}
			for _, entity := range p.Entities {
				if entity.ProposalRef == child.ProposalRef && entity.ProductCode != nil && entity.FilingOrRegistration != nil && normalizedIdentity830G3(*entity.ProductCode) == normalizedIdentity830G3(binding.ProductCode) && entity.FilingOrRegistration.Kind == binding.VersionAnchor.Kind && normalizedIdentity830G3(entity.FilingOrRegistration.Value) == binding.VersionAnchor.NormalizedValue {
					termsSupport = true
				}
			}
		}
	}
	if !termsSupport {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}
