package service

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

func TestStampRevisionAttemptUsesDatabaseBindingNotTraceAttempt(t *testing.T) {
	t.Parallel()

	chunks := []*types.Chunk{
		{ID: "parent", ChunkType: types.ChunkTypeParentText},
		{ID: "text", ChunkType: types.ChunkTypeText},
	}
	stampRevisionAttempt(chunks, &types.RevisionCommitBinding{ParseAttempt: 7})
	require.Equal(t, int64(7), chunks[0].ParseAttempt)
	require.Equal(t, int64(7), chunks[1].ParseAttempt)

	legacy := []*types.Chunk{{ID: "legacy"}}
	stampRevisionAttempt(legacy, nil)
	require.Zero(t, legacy[0].ParseAttempt)

	manual := []*types.Chunk{{ID: "manual"}}
	stampParseAttempt(manual, 9)
	require.Equal(t, int64(9), manual[0].ParseAttempt)
}

type revisionFinalizeRepoStub struct {
	interfaces.KnowledgeRepository

	legacyCalls   int
	revisionCalls int
	binding       types.RevisionCommitBinding
}

func (s *revisionFinalizeRepoStub) FinalizeSubtask(
	context.Context, string,
) (int, bool, error) {
	s.legacyCalls++
	return 0, true, nil
}

func (s *revisionFinalizeRepoStub) AllocateParseAttempt(
	context.Context, string, string, string,
) (int64, error) {
	return 0, nil
}

func (s *revisionFinalizeRepoStub) CommitDirectRevision(
	context.Context, string, types.RevisionCommitBinding,
) (*types.KnowledgeRevision, error) {
	return nil, nil
}

func (s *revisionFinalizeRepoStub) FinalizeSubtaskRevision(
	_ context.Context,
	_ string,
	binding types.RevisionCommitBinding,
) (int, bool, error) {
	s.revisionCalls++
	s.binding = binding
	return 0, true, nil
}

func TestFinalizeSubtaskDetachedUsesRevisionFencedPath(t *testing.T) {
	t.Parallel()

	repo := &revisionFinalizeRepoStub{}
	binding := &types.RevisionCommitBinding{
		ParseAttempt: 4,
		FileSHA256:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	}

	finalizeSubtaskDetached(
		context.Background(), repo, "knowledge-1", "summary",
		nil, false, true, binding,
	)

	require.Equal(t, 1, repo.revisionCalls)
	require.Zero(t, repo.legacyCalls)
	require.Equal(t, int64(4), repo.binding.ParseAttempt)
}

func TestRefreshRevisionBindingUsesWorkerEffectiveConfig(t *testing.T) {
	t.Parallel()
	original := &types.RevisionCommitBinding{
		ParseAttempt: 8,
		FileSHA256:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ParserIdentity: types.RevisionParserIdentity{
			ChunkSize: 100,
		},
	}
	kb := &types.KnowledgeBase{EmbeddingModelID: "embed-actual"}
	effective := types.EffectiveProcessConfig{
		ChunkingConfig: types.ChunkingConfig{ChunkSize: 768, ChunkOverlap: 64},
	}

	got := refreshRevisionBinding(original, kb, effective, "pdf")
	require.Equal(t, original.ParseAttempt, got.ParseAttempt)
	require.Equal(t, original.FileSHA256, got.FileSHA256)
	require.Equal(t, 768, got.ParserIdentity.ChunkSize)
	require.Equal(t, 64, got.ParserIdentity.ChunkOverlap)
	require.Equal(t, "embed-actual", got.ParserIdentity.EmbeddingModelID)
}

func TestRevisionBuildIdentityPrefersExistingBuildInjection(t *testing.T) {
	oldVersion, oldCommit := RevisionBuildVersion, RevisionBuildCommit
	t.Cleanup(func() {
		RevisionBuildVersion, RevisionBuildCommit = oldVersion, oldCommit
	})
	RevisionBuildVersion = "v1.2.3"
	RevisionBuildCommit = "abc1234"

	version, commit := revisionBuildIdentity()
	require.Equal(t, "v1.2.3", version)
	require.Equal(t, "abc1234", commit)
}

func TestDocumentRevisionPayloadFenceAcceptsMatchingFilelessAndRejectsStale(t *testing.T) {
	t.Parallel()

	for _, sourceType := range []string{"url", "file_url"} {
		t.Run(sourceType, func(t *testing.T) {
			t.Parallel()
			knowledge := &types.Knowledge{
				ID:                  "knowledge-" + sourceType,
				Type:                sourceType,
				CurrentParseAttempt: 7,
			}

			require.True(t, revisionPayloadMatchesKnowledge(knowledge, nil, 7))
			require.False(t, revisionPayloadMatchesKnowledge(knowledge, nil, 6))
			require.False(t, revisionPayloadMatchesKnowledge(knowledge, nil, 0))
		})
	}
}

func TestDocumentRevisionPayloadFencePreservesLegacyAndRejectsConflictingBinding(t *testing.T) {
	t.Parallel()

	legacy := &types.Knowledge{ID: "legacy", CurrentParseAttempt: 0}
	require.True(t, revisionPayloadMatchesKnowledge(legacy, nil, 0))

	knowledge := &types.Knowledge{
		ID:                  "file-backed",
		CurrentParseAttempt: 3,
		FileSHA256:          "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	}
	binding := &types.RevisionCommitBinding{
		ParseAttempt: 3,
		FileSHA256:   knowledge.FileSHA256,
	}
	require.True(t, revisionPayloadMatchesKnowledge(knowledge, binding, 3))
	require.False(t, revisionPayloadMatchesKnowledge(knowledge, binding, 2))

	payload := types.DocumentProcessPayload{ParseAttempt: 7}
	encoded, err := json.Marshal(payload)
	require.NoError(t, err)
	require.Contains(t, string(encoded), `"parse_attempt":7`)
}
