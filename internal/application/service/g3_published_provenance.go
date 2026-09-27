package service

import (
	"encoding/json"
	"reflect"

	"github.com/Tencent/WeKnora/internal/types"
)

// gob loses nonnil empty slices. Only the verified cold projection may use its
// signed member JSON as a witness to recover generated-content collections.
// This does not repair model output, recompile a candidate or rewrite the seal.
func restorePublishedGeneratedCollections830G3(bundle *types.BatchConceptCandidateBundle830G3) error {
	witnesses := make(map[string]json.RawMessage, len(bundle.PageManifest.Members))
	for _, member := range bundle.PageManifest.Members {
		if member.Kind == "concept" || member.Kind == "free_wiki_item" {
			witnesses[member.MemberID] = member.Payload
		}
	}
	for i := range bundle.CompileResult.Output.Definitions {
		d := &bundle.CompileResult.Output.Definitions[i]
		if d.ContentProvenance == nil {
			continue
		}
		id, err := d.DefinitionID()
		if err != nil || restorePublishedContentCollections830G3(d.ContentProvenance, &d.Evidence, witnesses[id], d.Origin == "MODEL_COMPILE") != nil {
			return ErrSchemaWikiPreparationInvalid
		}
	}
	for i := range bundle.CompileResult.Output.Pages {
		p := &bundle.CompileResult.Output.Pages[i]
		if p.ContentProvenance == nil {
			continue
		}
		id, err := p.FreeWikiPageID()
		if err != nil || restorePublishedContentCollections830G3(p.ContentProvenance, &p.Evidence, witnesses[id], true) != nil {
			return ErrSchemaWikiPreparationInvalid
		}
	}
	return nil
}

func restorePublishedContentCollections830G3(
	provenance *types.KnowledgeContentProvenance,
	evidence *[]types.ConceptEvidence830G2,
	raw json.RawMessage,
	allowGenerated bool,
) error {
	var witness struct {
		ContentProvenance *types.KnowledgeContentProvenance `json:"content_provenance"`
		Evidence          []types.ConceptEvidence830G2      `json:"evidence"`
	}
	if json.Unmarshal(raw, &witness) != nil || provenance == nil ||
		witness.ContentProvenance == nil || witness.Evidence == nil ||
		len(provenance.Segments) == 0 || len(provenance.Segments) != len(witness.ContentProvenance.Segments) {
		return ErrSchemaWikiPreparationInvalid
	}
	allGenerated := true
	for i := range provenance.Segments {
		segment := &provenance.Segments[i]
		original := witness.ContentProvenance.Segments[i]
		if segment.Origin == "MODEL_GENERATED" {
			if !allowGenerated || original.EvidenceIndexes == nil || len(original.EvidenceIndexes) != 0 || len(segment.EvidenceIndexes) != 0 {
				return ErrSchemaWikiPreparationInvalid
			}
			if segment.EvidenceIndexes == nil {
				segment.EvidenceIndexes = []int{}
			}
		} else {
			allGenerated = false
			if segment.Origin != "SOURCE_SUPPORTED" || len(segment.EvidenceIndexes) == 0 {
				return ErrSchemaWikiPreparationInvalid
			}
		}
	}
	if *evidence == nil {
		if !allGenerated || len(witness.Evidence) != 0 {
			return ErrSchemaWikiPreparationInvalid
		}
		*evidence = []types.ConceptEvidence830G2{}
	}
	if !reflect.DeepEqual(provenance, witness.ContentProvenance) || !reflect.DeepEqual(*evidence, witness.Evidence) {
		return ErrSchemaWikiPreparationInvalid
	}
	return nil
}
