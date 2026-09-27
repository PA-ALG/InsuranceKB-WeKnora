package types

// Knowledge quality has one policy owner. These bands do not confer publication
// authority and do not alter the model's original six-dimensional scores.
const provenanceQualityPolicy830 = "provenance-applicable-score.830.v1"

type knowledgeQualification830 struct {
	RawTotal      int
	ApplicableMax int
	Band          string
}
type knowledgeQualityContent830 struct {
	content    string
	evidence   []ConceptEvidence830G2
	provenance *KnowledgeContentProvenance
}

func knowledgeQualityMembers830(output ConceptCompileOutput830G2) (map[string]knowledgeQualityContent830, error) {
	members := map[string]knowledgeQualityContent830{}
	for _, row := range output.Definitions {
		id, err := conceptDefinitionID830G2(row)
		if err != nil {
			return nil, err
		}
		members[id] = knowledgeQualityContent830{row.Body, row.Evidence, row.ContentProvenance}
	}
	for _, row := range output.Pages {
		id, err := conceptFreePageID830G2(row)
		if err != nil {
			return nil, err
		}
		if _, exists := members[id]; exists {
			return nil, ErrConceptCandidateBundle830G3
		}
		members[id] = knowledgeQualityContent830{conceptFreePageContent830G3(row), row.Evidence, row.ContentProvenance}
	}
	return members, nil
}
func qualifyKnowledge830(policy string, member knowledgeQualityContent830, score ConceptValueScore830G2) (knowledgeQualification830, error) {
	result := knowledgeQualification830{RawTotal: conceptScoreTotal830G2(score), ApplicableMax: 100, Band: "ACCEPTED"}
	if !validConceptScore830G2(score) || (policy != "" && policy != provenanceQualityPolicy830) {
		return result, ErrConceptCandidateBundle830G3
	}
	if policy != "" {
		if validateKnowledgeContentProvenance(member.content, member.evidence, member.provenance) != nil {
			return result, ErrConceptCandidateBundle830G3
		}
		if member.provenance != nil && len(member.evidence) == 0 {
			if score.EvidenceQuality != 0 {
				return result, ErrConceptCandidateBundle830G3
			}
			result.ApplicableMax = 80
		}
	}
	if result.RawTotal*100 < result.ApplicableMax*60 {
		result.Band = "REJECTED"
	} else if result.RawTotal*100 < result.ApplicableMax*80 {
		result.Band = "PENDING"
	}
	return result, nil
}
