package service

import (
	"bytes"
	"compress/gzip"
	"encoding/gob"
	"encoding/json"
	"io"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestPublishedGeneratedContentSurvivesColdRead(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	compressed, err := os.ReadFile("../../../harness/tests/fixtures/batch_concept_compile_830_g3/content-provenance-candidate.json.gz")
	require.NoError(t, err)
	reader, err := gzip.NewReader(bytes.NewReader(compressed))
	require.NoError(t, err)
	raw, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	bundle, canonical, err := types.CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	members, err := bundle.SnapshotMembers()
	require.NoError(t, err)
	base := bundle.Request.BaseRequest
	p := &types.WikiReleasePreparation{ID: "generated-cold-read", WikiReleaseScope: batchConceptScope830G3(bundle), Status: types.WikiReleasePreparationReady, Manifest: canonical, Members: members, CandidateDigest: bundle.CandidateHash, ManifestDigest: digestWikiReleaseBytes(canonical), ReadyReceiptDigest: bundle.ReviewResult.Execution.RawOutputHash, ReviewDecisionDigest: "reviewed", ReviewPolicyID: conceptReviewPolicyHash830G2(base.PolicyIdentity), ExpectedReleaseID: base.BaseReleaseID, ExpectedActivationEpoch: base.BaseActivationEpoch}
	p.PreparationDigest = digestWikiReleasePreparation(p)
	store := newPublishedBatchReadReuse830G3(sourceReuseTestCodec830G3(t))
	require.NoError(t, store.rememberValidated(p, p.WikiReleaseScope))
	path, err := store.artifactPath(p, p.WikiReleaseScope)
	require.NoError(t, err)
	frozen, err := os.ReadFile(path)
	require.NoError(t, err)
	metadata := *p
	metadata.Manifest = nil
	metadata.Members = nil
	hot, _, err := store.read(&metadata, p.WikiReleaseScope)
	require.NoError(t, err)
	validations := batchPreparationValidations830G3.Load()
	cold, gotMembers, err := newPublishedBatchReadReuse830G3(store.codec).read(&metadata, p.WikiReleaseScope)
	require.NoError(t, err)
	require.Equal(t, validations, batchPreparationValidations830G3.Load())
	require.True(t, publishedBatchMemberIdentitiesEqual830G3(members, gotMembers))
	require.Equal(t, hot.CandidateHash, cold.CandidateHash)
	for i, page := range hot.CompileResult.Output.Pages {
		require.Equal(t, page.ContentProvenance, cold.CompileResult.Output.Pages[i].ContentProvenance)
		require.Equal(t, page.Evidence, cold.CompileResult.Output.Pages[i].Evidence)
	}
	for i, definition := range hot.CompileResult.Output.Definitions {
		require.Equal(t, definition.ContentProvenance, cold.CompileResult.Output.Definitions[i].ContentProvenance)
	}
	projection, err := g3PlatformPublishedProjectionFromBundle(p.WikiReleaseScope, cold)
	require.NoError(t, err)
	wire, err := json.Marshal(projection)
	require.NoError(t, err)
	require.NotContains(t, string(wire), `"evidence_indexes":null`)
	after, err := os.ReadFile(path)
	require.NoError(t, err)
	require.Equal(t, frozen, after, "read repair must not rewrite signed artifacts")
	var seal publishedBatchReadProjectionSeal830G3
	require.NoError(t, json.Unmarshal(frozen, &seal))
	seal.Signature[0] ^= 1
	broken, err := json.Marshal(seal)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(path, broken, 0600))
	_, _, err = newPublishedBatchReadReuse830G3(store.codec).read(&metadata, p.WikiReleaseScope)
	require.Error(t, err)
}

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

func TestGeneratedPublishedBaseSnapshotAfterRestart(t *testing.T) {
	fixture, schema, _ := batchConceptReleaseFixture830G3(t)
	compressed, err := os.ReadFile("testdata/generated-restart-candidate.json.gz")
	require.NoError(t, err)
	reader, err := gzip.NewReader(bytes.NewReader(compressed))
	require.NoError(t, err)
	raw, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	_, _, err = types.CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	draft, err := schema.CreateBatchConceptDraft830G3(fixture.ctx, fixture.principal1, fixture.scope, "generated-restart-base", raw)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "generated-restart-base")
	ready, err := schema.ReviewSchemaDraft(fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision)
	require.NoError(t, err)
	published, err := fixture.service.ActivateReviewed(fixture.ctx, fixture.principal1, rawDecision, conceptAuthorization830G2(t, fixture, ready, decision))
	require.NoError(t, err)
	store := fixture.service.publishedBatchReuse830G3()
	fixture.service.publishedReadReuse = newPublishedBatchReadReuse830G3(store.codec)
	service := NewG3PlatformBaseSnapshotService(fixture.service, &g3PlatformBaseAuthorizerStub{}, &g3PlatformSnapshotSignerStub{keyID: "base-key", signature: []byte("signed-base")})
	snapshot, err := service.Read(fixture.ctx, fixture.scope, published.ReleaseID, published.ActivationEpoch)
	require.NoError(t, err)
	generated := 0
	for _, definition := range snapshot.Snapshot.PublishedProjection.Definitions {
		if definition.ContentProvenance != nil && definition.ContentProvenance.Segments[0].Origin == "MODEL_GENERATED" {
			generated++
			require.NotNil(t, definition.Evidence)
			require.Empty(t, definition.Evidence)
			require.NotNil(t, definition.ContentProvenance.Segments[0].EvidenceIndexes)
		}
	}
	require.Positive(t, generated, "real base API must retain a pure generated definition")
	for _, page := range snapshot.Snapshot.PublishedProjection.Pages {
		if page.ContentProvenance != nil && page.ContentProvenance.Segments[0].Origin == "MODEL_GENERATED" {
			require.NotNil(t, page.Evidence)
			require.NotNil(t, page.ContentProvenance.Segments[0].EvidenceIndexes)
		}
	}
	second, err := service.Read(fixture.ctx, fixture.scope, published.ReleaseID, published.ActivationEpoch)
	require.NoError(t, err)
	require.Equal(t, snapshot.Snapshot.SnapshotSHA256, second.Snapshot.SnapshotSHA256)
}
