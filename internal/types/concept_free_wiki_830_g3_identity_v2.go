package types

import (
	"crypto/sha256"
	"encoding/hex"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

const evidenceIdentityCompilerV2_830G3 = "batch-entity-resolution-compiler.830.g3.v2"

// Retain the original proposal/receipt objects. This is the deterministic view
// used only by explicitly versioned v2 resolution; v1 remains byte-compatible.
func effectiveEvidenceProposalsV2_830G3(proposals ProposalBatch830G3, corpus ...BatchCorpus830G3) ProposalBatch830G3 {
	result := proposals
	result.Proposals = append([]MaterialProposal830G3(nil), proposals.Proposals...)
	for i, proposal := range result.Proposals {
		if len(corpus) > 0 {
			for _, entry := range corpus[0].Entries {
				if entry.MaterialID == proposal.MaterialID {
					proposal = expandDirectoryV2_830G3(proposal, entry)
					result.Proposals[i] = proposal
					break
				}
			}
		}
		result.Proposals[i].Entities = append([]EntityProposal830G3(nil), proposal.Entities...)
		for j, entity := range result.Proposals[i].Entities {
			if entity.VersionLabel == nil && entity.FilingOrRegistration != nil {
				label := entity.FilingOrRegistration.Value
				result.Proposals[i].Entities[j].VersionLabel = &label
			}
		}
	}
	return result
}
func distinctFilingVersionsV2_830G3(rows []resolutionRow830G3, indexes []int, versions map[int]string) bool {
	identities, anchors, distinct := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, index := range indexes {
		row := rows[index]
		entity := row.Entity
		if entity.Issuer == nil || entity.Name == nil || entity.ProductCode == nil || entity.FilingOrRegistration == nil {
			return false
		}
		identity, _ := batchConceptHash830G3("resolution-version-family.830.g3.v2", map[string]any{
			"issuer": *entity.Issuer, "name": *entity.Name, "code": *entity.ProductCode,
			"pack": row.Classification.SchemaPackID, "version": row.Classification.SchemaVersion, "sha": row.Classification.SchemaPackSHA256,
		})
		identities[identity] = true
		anchors[entity.FilingOrRegistration.Kind+"\x00"+normalizedIdentity830G3(entity.FilingOrRegistration.Value)] = true
		distinct[versions[index]] = true
	}
	return len(distinct) > 1 && len(identities) == 1 && len(anchors) == len(distinct)
}

var directoryRowsV2_830G3 = regexp.MustCompile(`(?m)^[ \t]*([A-Z0-9]+(?:/[A-Z0-9]+)*)[ \t]+([^\r\n]*保险[^\r\n]*)`)
var directoryIssuerV2_830G3 = regexp.MustCompile(`[\x{4e00}-\x{9fff}]{2,40}保险(?:集团)?股份有限公司`)

func sourceSpanV2_830G3(block ConceptSourceBlock830G2, start, end int) ConceptEvidence830G2 {
	quote := block.Text[start:end]
	sum := sha256.Sum256([]byte(quote))
	return ConceptEvidence830G2{ConceptSourceIdentity830G2: block.ConceptSourceIdentity830G2, SourceType: block.SourceType, BlockID: block.BlockID, PageNumber: block.PageNumber, OffsetUnit: "UNICODE_CODE_POINT", Start: utf8.RuneCountInString(block.Text[:start]), End: utf8.RuneCountInString(block.Text[:end]), Quote: quote, QuoteHash: hex.EncodeToString(sum[:])}
}
func directoryLabelV2_830G3(name string) string {
	// Mirrors the established product.classify keyword order, not a new taxonomy.
	rules := [][2]string{{"意外医疗", "accident_medical_insurance"}, {"医疗意外", "accident_medical_insurance"}, {"失能收入", "disability_income_insurance"}, {"补充养老", "supplementary_pension_insurance"}, {"护理保险", "nursing_care_insurance"}, {"重大疾病", "critical_illness_insurance"}, {"重疾", "critical_illness_insurance"}, {"终身寿险", "whole_life_insurance"}, {"定期寿险", "term_life_insurance"}, {"两全保险", "endowment_insurance"}, {"年金保险", "annuity_insurance"}, {"医疗保险", "medical_insurance"}, {"意外伤害", "accident_insurance"}}
	for _, rule := range rules {
		if strings.Contains(name, rule[0]) {
			return rule[1]
		}
	}
	return "classification_unresolved"
}
func expandDirectoryV2_830G3(proposal MaterialProposal830G3, entry CorpusEntry830G3) MaterialProposal830G3 {
	header := false
	for _, block := range entry.Blocks {
		if strings.Contains(block.Text, "险种代码") && strings.Contains(block.Text, "险种名称") {
			header = true
		}
	}
	if proposal.MaterialRole != "product-list" || !header {
		return proposal
	}
	blocks := append([]ConceptSourceBlock830G2(nil), entry.Blocks...)
	sort.Slice(blocks, func(i, j int) bool {
		if blocks[i].PageNumber == blocks[j].PageNumber {
			return blocks[i].BlockID < blocks[j].BlockID
		}
		return blocks[i].PageNumber < blocks[j].PageNumber
	})
	issuers := map[string]ConceptEvidence830G2{}
	for _, block := range blocks {
		for _, at := range directoryIssuerV2_830G3.FindAllStringIndex(block.Text, -1) {
			name := block.Text[at[0]:at[1]]
			if _, exists := issuers[name]; !exists {
				issuers[name] = sourceSpanV2_830G3(block, at[0], at[1])
			}
		}
	}
	if len(issuers) == 0 {
		for _, entity := range proposal.Entities {
			for _, row := range proposal.Evidence {
				if entity.Issuer != nil && row.Purpose == "issuer" && row.EntityProposalRef != nil && *row.EntityProposalRef == entity.ProposalRef && strings.Contains(normalizedIdentity830G3(row.Evidence.Quote), normalizedIdentity830G3(*entity.Issuer)) && verifyConceptEvidence830G2(row.Evidence, entry.Blocks) == nil {
					if _, exists := issuers[*entity.Issuer]; !exists {
						issuers[*entity.Issuer] = row.Evidence
					}
				}
			}
		}
	}
	var issuer *string
	if len(issuers) == 1 {
		for name := range issuers {
			value := name
			issuer = &value
		}
	}
	evidence := []ProposalEvidence830G3{}
	for _, row := range proposal.Evidence {
		if row.Purpose == "material_role" {
			evidence = append(evidence, row)
		}
	}
	entities := []EntityProposal830G3{}
	seen := map[string]bool{}
	for _, block := range blocks {
		for _, at := range directoryRowsV2_830G3.FindAllStringSubmatchIndex(block.Text, -1) {
			code, name := block.Text[at[2]:at[3]], strings.TrimSpace(block.Text[at[4]:at[5]])
			key := code + "\x00" + name
			if seen[key] {
				continue
			}
			seen[key] = true
			span := sourceSpanV2_830G3(block, at[0], at[1])
			ref, _ := batchConceptHash830G3("directory-row.830.g3.v2", map[string]any{"material_id": entry.MaterialID, "revision_id": block.RevisionID, "block_id": block.BlockID, "start": span.Start, "end": span.End})
			label := directoryLabelV2_830G3(name)
			ids := []string{ref + "-name", ref + "-product_code"}
			for _, purpose := range []string{"name", "product_code", "classification"} {
				evidence = append(evidence, ProposalEvidence830G3{EvidenceID: ref + "-" + purpose, EntityProposalRef: &ref, Purpose: purpose, Evidence: span})
			}
			if issuer != nil {
				eid := ref + "-issuer"
				ids = append(ids, eid)
				evidence = append(evidence, ProposalEvidence830G3{EvidenceID: eid, EntityProposalRef: &ref, Purpose: "issuer", Evidence: issuers[*issuer]})
			}
			sort.Strings(ids)
			entities = append(entities, EntityProposal830G3{ProposalRef: ref, Issuer: issuer, Name: &name, ProductCode: &code, IdentityConfidence: "1.000000", IdentityEvidenceIDs: ids, Labels: []LabelProposal830G3{{TaxonomyLabel: label, Confidence: "1.000000", EvidenceIDs: []string{ref + "-classification"}}}, PrimaryLabel: label})
		}
	}
	if len(entities) == 0 {
		return proposal
	}
	sort.Slice(entities, func(i, j int) bool { return entities[i].ProposalRef < entities[j].ProposalRef })
	sort.Slice(evidence, func(i, j int) bool { return evidence[i].EvidenceID < evidence[j].EvidenceID })
	proposal.Entities, proposal.Evidence = entities, evidence
	return proposal
}
func sameClassificationV2_830G3(a, b ClassificationAssignment830G3) bool {
	return a.PrimaryLabel == b.PrimaryLabel && optionalStringEqualV2_830G3(a.SchemaPackID, b.SchemaPackID) && optionalStringEqualV2_830G3(a.SchemaVersion, b.SchemaVersion) && optionalStringEqualV2_830G3(a.SchemaPackSHA256, b.SchemaPackSHA256)
}
func optionalStringEqualV2_830G3(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}
func ownIdentitySupportedV2_830G3(proposal MaterialProposal830G3, entity EntityProposal830G3) bool {
	values := map[string][]string{}
	for purpose, value := range map[string]*string{"issuer": entity.Issuer, "name": entity.Name, "product_code": entity.ProductCode, "version": entity.VersionLabel} {
		if value != nil {
			values[purpose] = append(values[purpose], *value)
		}
	}
	if entity.FilingOrRegistration != nil {
		values["version"] = append(values["version"], entity.FilingOrRegistration.Value)
	}
	selected := map[string]bool{}
	for _, id := range entity.IdentityEvidenceIDs {
		selected[id] = true
	}
	for purpose, asserted := range values {
		for _, value := range asserted {
			found := false
			for _, row := range proposal.Evidence {
				if selected[row.EvidenceID] && row.Purpose == purpose && row.EntityProposalRef != nil && *row.EntityProposalRef == entity.ProposalRef && strings.Contains(normalizedIdentity830G3(row.Evidence.Quote), normalizedIdentity830G3(value)) {
					found = true
					break
				}
			}
			if !found {
				return false
			}
		}
	}
	return true
}

func associateBrochuresV2_830G3(decisions []MaterialDecision830G3, proposals ProposalBatch830G3) []MaterialDecision830G3 {
	byMaterial := map[string]MaterialProposal830G3{}
	for _, p := range proposals.Proposals {
		byMaterial[p.MaterialID] = p
	}
	terms := []EntityDecision830G3{}
	for _, parent := range decisions {
		if byMaterial[parent.MaterialID].MaterialRole == "terms" {
			for _, child := range parent.Children {
				if child.Disposition == "MATCH" || child.Disposition == "CREATE" {
					terms = append(terms, child)
				}
			}
		}
	}
	result := append([]MaterialDecision830G3(nil), decisions...)
	for i, parent := range result {
		p := byMaterial[parent.MaterialID]
		if p.MaterialRole != "brochure" || len(parent.Children) != 1 || len(p.Entities) != 1 {
			continue
		}
		child, entity := parent.Children[0], p.Entities[0]
		allowed := true
		for _, reason := range child.ReasonCodes {
			if reason != "IDENTITY_EVIDENCE_MISSING" && reason != "VERSION_UNRESOLVED" && reason != "AMBIGUOUS_IDENTITY" {
				allowed = false
			}
		}
		if child.Disposition != "NEEDS_CONFIRM" || !allowed || entity.Issuer == nil || entity.Name == nil || !ownIdentitySupportedV2_830G3(p, entity) {
			continue
		}
		targets := map[string]EntityDecision830G3{}
		for _, target := range terms {
			a := target.Anchors
			if a.Issuer == nil || a.Name == nil || a.ProductCode == nil || a.VersionAnchor == nil || a.VersionLabel == nil {
				continue
			}
			if normalizedIdentity830G3(*entity.Issuer) != a.Issuer.NormalizedValue || normalizedIdentity830G3(*entity.Name) != a.Name.NormalizedValue || !sameClassificationV2_830G3(child.Classification, target.Classification) {
				continue
			}
			if entity.ProductCode != nil && normalizedIdentity830G3(*entity.ProductCode) != a.ProductCode.NormalizedValue {
				continue
			}
			if entity.VersionLabel != nil && normalizedIdentity830G3(*entity.VersionLabel) != a.VersionLabel.NormalizedValue {
				continue
			}
			if entity.FilingOrRegistration != nil && (entity.FilingOrRegistration.Kind != a.VersionAnchor.Kind || normalizedIdentity830G3(entity.FilingOrRegistration.Value) != a.VersionAnchor.NormalizedValue) {
				continue
			}
			key := target.Disposition
			if target.EntityCandidate != nil {
				key += "\x00" + target.EntityCandidate.CandidateSHA256
			} else if target.MatchedEntityID != nil && target.MatchedEntityVersion != nil {
				key += "\x00" + *target.MatchedEntityID + "\x00" + *target.MatchedEntityVersion
			}
			targets[key] = target
		}
		if len(targets) != 1 {
			continue
		}
		for _, target := range targets {
			child.Disposition, child.MatchedEntityID, child.MatchedEntityVersion, child.EntityCandidate, child.Anchors = target.Disposition, target.MatchedEntityID, target.MatchedEntityVersion, target.EntityCandidate, target.Anchors
			child.ReasonCodes = target.ReasonCodes
			child.QueueID, child.QueueOwner = nil, nil
			child.DecisionSHA256, _ = batchConceptHashWithout830G3("entity-decision.830.g3.v1", child, "decision_sha256")
			parent.Disposition, parent.Children, parent.ReasonCodes = target.Disposition, []EntityDecision830G3{child}, target.ReasonCodes
			parent.QueueID, parent.QueueOwner = nil, nil
			parent.DecisionSHA256, _ = batchConceptHashWithout830G3("material-decision.830.g3.v1", parent, "decision_sha256")
			result[i] = parent
		}
	}
	return result
}
