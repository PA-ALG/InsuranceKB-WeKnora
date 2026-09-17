package service

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func publishedSourceFixture830G3(t *testing.T) (*ConceptSourceAuthorityService830G2, types.WikiReleaseScope, types.BatchConceptCandidateBundle830G3, types.ConceptEvidence830G2, types.ConceptSourceBlock830G2, string) {
	t.Helper()
	s, _, scope, e, block := nativeIndexFixture830G2(t)
	readySourceReuseResource830G3(s)
	source := s.revisions.(*conceptKnowledgeStub830G2).source
	value := "A😀"
	field := types.ConceptFieldAssertion830G2{SpaceID: scope.SpaceID, EntityID: "entity", FieldKey: "field", State: "present", Value: &value, Attempted: true, Evidence: []types.ConceptEvidence830G2{e}, EntityVersion: "v1"}
	id, err := field.FieldAssertionID()
	require.NoError(t, err)
	parent := types.BatchConceptCandidateBundle830G3{}
	parent.Request.BaseRequest.Sources = []types.ConceptSourceBlock830G2{block}
	parent.CompileResult.Output.Fields = []types.ConceptFieldAssertion830G2{field}
	parent.Request.ResolutionInputs.Corpus.Entries = []types.CorpusEntry830G3{{Blocks: []types.ConceptSourceBlock830G2{block}, Receipt: types.SourceReceipt830G3{Registered: &types.RegisteredSourceReceipt830G3{
		Contract: "knowledge-revision-source.v1", KnowledgeID: source.KnowledgeID, ParseAttempt: source.ParseAttempt, RevisionSourceID: source.RevisionSourceID, FileSHA256: source.FileSHA256, ObjectSHA256: source.ObjectSHA256, Size: source.Size, MIMEType: source.MimeType, PageCount: int64(*source.PageCount), ManifestAlgorithm: source.ManifestAlgorithm, ManifestDigest: source.ManifestDigest, ChunkCount: int64(source.ChunkCount), BindingDigest: source.BindingDigest, RetentionState: source.RetentionState,
	}}}}
	// Scope is checked by the release owner's signed projection loader in production.
	s.publishedLegacyBase = func(_ context.Context, got types.WikiReleaseScope, release string, epoch uint64) (types.BatchConceptCandidateBundle830G3, bool, error) {
		require.Equal(t, scope, got)
		require.Equal(t, "published-parent", release)
		require.EqualValues(t, 7, epoch)
		return parent, true, nil
	}
	child := parent
	child.Request.BaseRequest.BaseReleaseID = "published-parent"
	child.Request.BaseRequest.BaseActivationEpoch = 7
	return s, scope, child, e, block, id
}

func TestG3PublishedSourceReuseChecksLiveBindingsWithoutReopeningHistory(t *testing.T) {
	s, scope, child, e, block, member := publishedSourceFixture830G3(t)
	reuse, err := s.publishedSourceReuse830G3(context.Background(), scope, child)
	require.NoError(t, err)
	// A cold/missing local index does not erase a valid immutable published proof.
	s.fixed = nil
	s.chunks = nil
	s.docreader = nil
	ok, err := reuse.verify(context.Background(), member, e, block)
	require.NoError(t, err)
	require.True(t, ok)
	repo := s.revisions.(*conceptKnowledgeStub830G2)
	for _, change := range []string{"deleted", "foreign", "revoked", "binding", "resource"} {
		t.Run(change, func(t *testing.T) {
			fresh, err := s.publishedSourceReuse830G3(context.Background(), scope, child)
			require.NoError(t, err)
			knowledge, source, resource := *repo.knowledge, *repo.source, *repo.resource
			defer func() { *repo.knowledge = knowledge; *repo.source = source; *repo.resource = resource }()
			switch change {
			case "deleted":
				repo.knowledge.DeletedAt.Valid = true
			case "foreign":
				repo.knowledge.KnowledgeBaseID = "foreign"
			case "revoked":
				repo.source.RetentionState = "released"
			case "binding":
				repo.source.BindingDigest = testSHA830G2("changed")
			case "resource":
				repo.resource.State = "deleted"
			}
			_, err = fresh.verify(context.Background(), member, e, block)
			require.Error(t, err)
		})
	}
}

func TestG3PublishedSourceReuseNeverCarriesChangedOccurrences(t *testing.T) {
	for _, change := range []string{"unchanged", "empty optional slices", "value", "condition", "evidence", "block", "member", "source"} {
		t.Run(change, func(t *testing.T) {
			s, scope, child, e, block, member := publishedSourceFixture830G3(t)
			raw, err := json.Marshal(child.CompileResult.Output.Fields)
			require.NoError(t, err)
			child.CompileResult.Output.Fields = nil // Decode into independent storage, not the parent slice.
			require.NoError(t, json.Unmarshal(raw, &child.CompileResult.Output.Fields))
			switch change {
			case "empty optional slices":
				child.CompileResult.Output.Fields[0].ConceptIDs = []string{}
				child.CompileResult.Output.Fields[0].Conditions = []string{}
			case "value":
				v := "other"
				child.CompileResult.Output.Fields[0].Value = &v
			case "condition":
				child.CompileResult.Output.Fields[0].Conditions = []string{"different"}
			case "evidence":
				child.CompileResult.Output.Fields[0].Evidence[0].PageNumber++
			case "block":
				block.Text += "changed"
			case "member":
				member = "new-member"
			case "source":
				e.ParserIdentity = testSHA830G2("new-parser")
			}
			reuse, err := s.publishedSourceReuse830G3(context.Background(), scope, child)
			require.NoError(t, err)
			ok, err := reuse.verify(context.Background(), member, e, block)
			require.NoError(t, err)
			require.Equal(t, change == "unchanged" || change == "empty optional slices", ok)
		})
	}
}

func TestG3PublishedSourceReuseCarriedSourcesOutsideCurrentCorpus(t *testing.T) {
	s, scope, child, e, block, member := publishedSourceFixture830G3(t)
	parent, _, err := s.publishedLegacyBase(context.Background(), scope, "published-parent", 7)
	require.NoError(t, err)
	parent.Request.ResolutionInputs.Corpus.Entries = nil
	s.publishedLegacyBase = func(context.Context, types.WikiReleaseScope, string, uint64) (types.BatchConceptCandidateBundle830G3, bool, error) {
		return parent, true, nil
	}
	reuse, err := s.publishedSourceReuse830G3(context.Background(), scope, child)
	require.NoError(t, err)
	ok, err := reuse.verify(context.Background(), member, e, block)
	require.NoError(t, err)
	require.True(t, ok)
	// Self-rehashing a different physical resource cannot reuse the published ID.
	repo := s.revisions.(*conceptKnowledgeStub830G2)
	repo.source.ResourceID = "different-resource"
	repo.resource.ID = repo.source.ResourceID
	repo.source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(*repo.source)
	require.NoError(t, err)
	reuse, err = s.publishedSourceReuse830G3(context.Background(), scope, child)
	require.NoError(t, err)
	_, err = reuse.verify(context.Background(), member, e, block)
	require.Error(t, err)
}

func TestG3PublishedSourceReuseMissingProjectionFallsBack(t *testing.T) {
	s, scope, child, e, block, member := publishedSourceFixture830G3(t)
	s.publishedLegacyBase = func(context.Context, types.WikiReleaseScope, string, uint64) (types.BatchConceptCandidateBundle830G3, bool, error) {
		return types.BatchConceptCandidateBundle830G3{}, false, nil
	}
	reuse, err := s.publishedSourceReuse830G3(context.Background(), scope, child)
	require.NoError(t, err)
	ok, err := reuse.verify(context.Background(), member, e, block)
	require.NoError(t, err)
	require.False(t, ok)
}

// Optional offline measurement over retained platform artifacts. No database,
// provider, or authority mutation is involved; the normal unit tests run in CI.
func TestG3PublishedSourceReuseRecordedCandidate(t *testing.T) {
	directory := os.Getenv("G3_SOURCE_REUSE_RECORDINGS_DIR")
	if directory == "" {
		t.Skip("no recorded platform artifacts supplied")
	}
	read := func(name string) types.BatchConceptCandidateBundle830G3 {
		raw, err := os.ReadFile(filepath.Join(directory, name))
		require.NoError(t, err)
		var bundle types.BatchConceptCandidateBundle830G3
		require.NoError(t, json.Unmarshal(raw, &bundle))
		return bundle
	}
	parent, child := read("parent_candidate.json"), read("candidate.json")
	scope := batchConceptScope830G3(child)
	s := &ConceptSourceAuthorityService830G2{publishedLegacyBase: func(context.Context, types.WikiReleaseScope, string, uint64) (types.BatchConceptCandidateBundle830G3, bool, error) {
		return parent, true, nil
	}}
	start := time.Now()
	reuse, err := s.publishedSourceReuse830G3(context.Background(), scope, child)
	require.NoError(t, err)
	require.Greater(t, len(reuse.occurrences), 300, "historical members must be reusable beyond only the parent's current-batch corpus")
	sources := map[types.ConceptSourceIdentity830G2]bool{}
	for _, proof := range reuse.occurrences {
		sources[proof.block.ConceptSourceIdentity830G2] = true
	}
	t.Logf("published immutable occurrences=%d historical sources=%d projection elapsed=%s", len(reuse.occurrences), len(sources), time.Since(start))
}
