package service

import (
	"context"
	"encoding/json"

	"github.com/Tencent/WeKnora/internal/types"
)

type publishedSourceOccurrence830G3 struct {
	block   types.ConceptSourceBlock830G2
	receipt *types.RegisteredSourceReceipt830G3
}

// Short-lived verification state, created only from the release owner's signed
// published projection. It does not become a second release/source authority.
type publishedSourceReuse830G3 struct {
	service     *ConceptSourceAuthorityService830G2
	scope       types.WikiReleaseScope
	occurrences map[string]publishedSourceOccurrence830G3
	checked     map[types.ConceptSourceIdentity830G2]int
	hits        int
}

func sourceOccurrenceKey830G3(member string, evidence types.ConceptEvidence830G2) string {
	raw, _ := canonicalJSON830G2(evidence)
	return member + "\x00" + testSHA256Bytes830G2(raw)
}

// Gob's empty slices can reopen as nil. Normalize only the collection fields of
// these already validated member/binding projections; nullable values stay null.
func publishedSemanticProjection830G3(value any) string {
	raw, err := json.Marshal(value)
	if err != nil {
		return ""
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return ""
	}
	for _, key := range []string{"evidence", "aliases", "concept_ids", "conditions", "exceptions", "required_fields", "source_material_ids", "resolution_refs", "resolution_evidence"} {
		if string(fields[key]) == "null" {
			fields[key] = json.RawMessage(`[]`)
		}
	}
	raw, err = json.Marshal(fields)
	if err != nil {
		return ""
	}
	return string(raw)
}

func (s *ConceptSourceAuthorityService830G2) publishedSourceReuse830G3(ctx context.Context, scope types.WikiReleaseScope, child types.BatchConceptCandidateBundle830G3) (*publishedSourceReuse830G3, error) {
	result := &publishedSourceReuse830G3{service: s, scope: scope, occurrences: map[string]publishedSourceOccurrence830G3{}, checked: map[types.ConceptSourceIdentity830G2]int{}}
	base := child.Request.BaseRequest
	if s.publishedLegacyBase == nil || base.BaseReleaseID == "" {
		return result, nil
	}
	parent, found, err := s.publishedLegacyBase(ctx, scope, base.BaseReleaseID, base.BaseActivationEpoch)
	if err != nil || !found {
		return result, err
	}
	// Exact member identity and payload; an equal quotation in another member
	// cannot transfer the parent's verification to that member.
	parentMembers := map[string]string{}
	addMembers := func(bundle types.BatchConceptCandidateBundle830G3, visit func(string, any, []types.ConceptEvidence830G2)) error {
		for _, v := range bundle.CompileResult.Output.Fields {
			id, err := v.FieldAssertionID()
			if err != nil {
				return err
			}
			visit(id, v, v.Evidence)
		}
		for _, v := range bundle.CompileResult.Output.Definitions {
			id, err := v.DefinitionID()
			if err != nil {
				return err
			}
			visit(id, v, v.Evidence)
		}
		for _, v := range bundle.CompileResult.Output.Pages {
			id, err := v.FreeWikiPageID()
			if err != nil {
				return err
			}
			visit(id, v, v.Evidence)
		}
		for _, v := range bundle.Request.EntityBindings {
			evidence := make([]types.ConceptEvidence830G2, 0, len(v.ResolutionEvidence))
			for _, bound := range v.ResolutionEvidence {
				evidence = append(evidence, bound.Evidence)
			}
			visit("binding:"+v.EntityID, v, evidence)
		}
		return nil
	}
	if err := addMembers(parent, func(id string, value any, _ []types.ConceptEvidence830G2) {
		parentMembers[id] = publishedSemanticProjection830G3(value)
	}); err != nil {
		return nil, err
	}
	parentBlocks := map[types.ConceptSourceIdentity830G2]map[string]types.ConceptSourceBlock830G2{}
	receipts := map[string]types.RegisteredSourceReceipt830G3{}
	for _, entry := range parent.Request.ResolutionInputs.Corpus.Entries {
		if entry.Receipt.Registered != nil {
			receipts[entry.Receipt.Registered.RevisionSourceID] = *entry.Receipt.Registered
		}
	}
	for _, block := range parent.Request.BaseRequest.Sources {
		if parentBlocks[block.ConceptSourceIdentity830G2] == nil {
			parentBlocks[block.ConceptSourceIdentity830G2] = map[string]types.ConceptSourceBlock830G2{}
		}
		parentBlocks[block.ConceptSourceIdentity830G2][block.BlockID] = block
	}
	err = addMembers(child, func(id string, value any, evidence []types.ConceptEvidence830G2) {
		projection := publishedSemanticProjection830G3(value)
		if projection == "" || parentMembers[id] != projection {
			return
		}
		for _, e := range evidence {
			block, ok := parentBlocks[e.ConceptSourceIdentity830G2][e.BlockID]
			receipt, hasReceipt := receipts[e.RevisionID]
			if !ok || block.PageNumber != e.PageNumber || block.SourceType != e.SourceType || !conceptEvidenceMatchesSourceText830G2(e, block.Text) {
				continue
			}
			proof := publishedSourceOccurrence830G3{block: block}
			if hasReceipt {
				proof.receipt = &receipt
			}
			result.occurrences[sourceOccurrenceKey830G3(id, e)] = proof
		}
	})
	return result, err
}

func (r *publishedSourceReuse830G3) verify(ctx context.Context, member string, evidence types.ConceptEvidence830G2, block types.ConceptSourceBlock830G2) (bool, error) {
	proof, ok := r.occurrences[sourceOccurrenceKey830G3(member, evidence)]
	if !ok || proof.block != block {
		return false, nil
	}
	if evidence.PageNumber <= 0 || (proof.receipt != nil && int64(evidence.PageNumber) > proof.receipt.PageCount) {
		return false, ErrConceptSourceAuthorityUnavailable830G2
	}
	pageCount, checked := r.checked[evidence.ConceptSourceIdentity830G2]
	if !checked {
		_, source, resource, err := r.service.currentConceptEvidenceSource830G3(ctx, r.scope, evidence)
		if err != nil || (proof.receipt != nil && !registeredReceiptMatchesSource830G3(*proof.receipt, source)) || !conceptSourceResourceCurrent830G3(source, resource) {
			return false, ErrConceptSourceAuthorityUnavailable830G2
		}
		// Older carried members are outside the parent's current-batch corpus.
		// Its signed member/source identity still binds file, parser and manifest;
		// recompute the source ID to additionally bind resource ID, size and MIME.
		id, err := types.ComputeKnowledgeRevisionSourceID(*source)
		if err != nil || id != evidence.RevisionID {
			return false, ErrConceptSourceAuthorityUnavailable830G2
		}
		pageCount = *source.PageCount
		r.checked[evidence.ConceptSourceIdentity830G2] = pageCount
	}
	if evidence.PageNumber > pageCount {
		return false, ErrConceptSourceAuthorityUnavailable830G2
	}
	r.hits++
	return true, nil
}

func conceptSourceResourceCurrent830G3(source *types.KnowledgeRevisionSource, resource *types.StoredResource) bool {
	return source != nil && resource != nil && source.RetentionState == types.KnowledgeRevisionSourcePinned && resource.Handle == source.ResourceHandle && resource.ContentHash == source.ObjectSHA256 && resource.State == types.ResourceStateActive && resource.Lifecycle == types.ResourceLifecyclePersistent
}
