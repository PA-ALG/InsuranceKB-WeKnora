package types

import (
	"fmt"
	"strings"
)

type KnowledgeContentSegment struct {
	Text            string `json:"text"`
	Origin          string `json:"origin"`
	EvidenceIndexes []int  `json:"evidence_indexes"`
}
type KnowledgeContentProvenance struct {
	Contract string                    `json:"contract"`
	Segments []KnowledgeContentSegment `json:"segments"`
}

func validateKnowledgeContentProvenance(content string, evidence []ConceptEvidence830G2, provenance *KnowledgeContentProvenance) error {
	if provenance == nil {
		if len(evidence) == 0 {
			return ErrConceptCandidateBundle830G2
		}
		return nil
	}
	if provenance.Contract != "knowledge-content-provenance.830.v1" || len(provenance.Segments) == 0 || evidence == nil {
		return ErrConceptCandidateBundle830G2
	}
	identities := map[string]bool{}
	for _, e := range evidence {
		// Same occurrence identity used by the serving citation ID.
		key := fmt.Sprintf("%q/%q/%d/%d/%d/%s", e.RevisionID, e.BlockID, e.PageNumber, e.Start, e.End, e.QuoteHash)
		if identities[key] {
			return ErrConceptCandidateBundle830G2
		}
		identities[key] = true
	}
	var rendered strings.Builder
	used := map[int]bool{}
	for _, segment := range provenance.Segments {
		if segment.Text == "" || segment.EvidenceIndexes == nil {
			return ErrConceptCandidateBundle830G2
		}
		if segment.Origin == "MODEL_GENERATED" {
			if len(segment.EvidenceIndexes) != 0 {
				return ErrConceptCandidateBundle830G2
			}
		} else if segment.Origin != "SOURCE_SUPPORTED" || len(segment.EvidenceIndexes) == 0 {
			return ErrConceptCandidateBundle830G2
		}
		previous := -1
		for _, index := range segment.EvidenceIndexes {
			if index <= previous || index >= len(evidence) {
				return ErrConceptCandidateBundle830G2
			}
			previous = index
			used[index] = true
		}
		rendered.WriteString(segment.Text)
	}
	if rendered.String() != content || len(used) != len(evidence) {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func hasGeneratedKnowledgeContent(provenance *KnowledgeContentProvenance) bool {
	if provenance != nil {
		for _, segment := range provenance.Segments {
			if segment.Origin == "MODEL_GENERATED" {
				return true
			}
		}
	}
	return false
}

func validateKnowledgeTransformation(output ConceptCompileOutput830G2) error {
	if output.Transformation == "SYNTHESIZE" {
		return nil
	}
	for _, definition := range output.Definitions {
		if hasGeneratedKnowledgeContent(definition.ContentProvenance) {
			return ErrConceptCandidateBundle830G2
		}
	}
	for _, page := range output.Pages {
		if hasGeneratedKnowledgeContent(page.ContentProvenance) {
			return ErrConceptCandidateBundle830G2
		}
	}
	return nil
}
