package service

import (
	"bytes"
	"encoding/gob"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestPublishedGeneratedCollectionsRequireSignedEmptyWitness(t *testing.T) {
	generated := types.KnowledgeContentSegment{Text: "model explanation", Origin: "MODEL_GENERATED", EvidenceIndexes: []int{}}
	source := types.KnowledgeContentSegment{Text: "source text", Origin: "SOURCE_SUPPORTED", EvidenceIndexes: []int{0}}
	proof := types.ConceptEvidence830G2{Quote: "source text"}
	for _, tc := range []struct {
		name     string
		segments []types.KnowledgeContentSegment
		evidence []types.ConceptEvidence830G2
		mutate   func(*types.KnowledgeContentProvenance, *[]types.ConceptEvidence830G2, *json.RawMessage)
		wantErr  bool
	}{
		{name: "pure generated definition", segments: []types.KnowledgeContentSegment{generated}, evidence: []types.ConceptEvidence830G2{}},
		{name: "mixed content", segments: []types.KnowledgeContentSegment{source, generated}, evidence: []types.ConceptEvidence830G2{proof}},
		{name: "source supported indexes cannot be invented", segments: []types.KnowledgeContentSegment{source}, evidence: []types.ConceptEvidence830G2{proof}, wantErr: true, mutate: func(p *types.KnowledgeContentProvenance, _ *[]types.ConceptEvidence830G2, _ *json.RawMessage) {
			p.Segments[0].EvidenceIndexes = nil
		}},
		{name: "mixed evidence cannot be invented", segments: []types.KnowledgeContentSegment{source, generated}, evidence: []types.ConceptEvidence830G2{proof}, wantErr: true, mutate: func(_ *types.KnowledgeContentProvenance, e *[]types.ConceptEvidence830G2, _ *json.RawMessage) {
			*e = nil
		}},
		{name: "missing witness", segments: []types.KnowledgeContentSegment{generated}, evidence: []types.ConceptEvidence830G2{}, wantErr: true, mutate: func(_ *types.KnowledgeContentProvenance, _ *[]types.ConceptEvidence830G2, raw *json.RawMessage) {
			*raw = nil
		}},
		{name: "null witness is not empty", segments: []types.KnowledgeContentSegment{generated}, evidence: []types.ConceptEvidence830G2{}, wantErr: true, mutate: func(_ *types.KnowledgeContentProvenance, _ *[]types.ConceptEvidence830G2, raw *json.RawMessage) {
			*raw = bytes.ReplaceAll(*raw, []byte(`"evidence_indexes":[]`), []byte(`"evidence_indexes":null`))
		}},
		{name: "text cannot change", segments: []types.KnowledgeContentSegment{generated}, evidence: []types.ConceptEvidence830G2{}, wantErr: true, mutate: func(p *types.KnowledgeContentProvenance, _ *[]types.ConceptEvidence830G2, _ *json.RawMessage) {
			p.Segments[0].Text = "changed"
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			provenance := &types.KnowledgeContentProvenance{Contract: "knowledge-content-provenance.830.v1", Segments: tc.segments}
			definition := types.ConceptDefinition830G2{SpaceID: "space", CanonicalKey: "concept", SenseKey: "sense", Origin: "MODEL_COMPILE", ContentProvenance: provenance, Evidence: tc.evidence}
			raw, err := json.Marshal(definition)
			require.NoError(t, err)
			var cold types.ConceptDefinition830G2
			var buffer bytes.Buffer
			require.NoError(t, gob.NewEncoder(&buffer).Encode(definition))
			require.NoError(t, gob.NewDecoder(&buffer).Decode(&cold))
			witness := json.RawMessage(raw)
			if tc.mutate != nil {
				tc.mutate(cold.ContentProvenance, &cold.Evidence, &witness)
			}
			id, err := cold.DefinitionID()
			require.NoError(t, err)
			bundle := types.BatchConceptCandidateBundle830G3{CompileResult: types.ConceptCompileResult830G2{Output: types.ConceptCompileOutput830G2{Definitions: []types.ConceptDefinition830G2{cold}}}, PageManifest: types.BatchConceptPageManifest830G3{Members: []types.ConceptPageMember830G2{{Kind: "concept", MemberID: id, Payload: witness}}}}
			err = restorePublishedGeneratedCollections830G3(&bundle)
			if tc.wantErr {
				require.Error(t, err)
				return
			}
			require.NoError(t, err)
			require.Equal(t, definition.ContentProvenance, bundle.CompileResult.Output.Definitions[0].ContentProvenance)
			require.Equal(t, definition.Evidence, bundle.CompileResult.Output.Definitions[0].Evidence)
		})
	}
}
