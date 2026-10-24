package service

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type sourcePagesRepository struct {
	interfaces.KnowledgeRepository
	knowledge                     *types.Knowledge
	revision                      *types.KnowledgeRevision
	knowledgeErr, revisionErr     error
	knowledgeCalls, revisionCalls int
	tenant                        uint64
	attempt                       int64
}

func (r *sourcePagesRepository) GetKnowledgeByID(_ context.Context, tenant uint64, _ string) (*types.Knowledge, error) {
	r.knowledgeCalls++
	r.tenant = tenant
	return r.knowledge, r.knowledgeErr
}

func (r *sourcePagesRepository) GetRevision(
	_ context.Context, _ string, attempt int64,
) (*types.KnowledgeRevision, error) {
	r.revisionCalls++
	r.attempt = attempt
	return r.revision, r.revisionErr
}

func sourcePagesFixture(
	t *testing.T,
) (*G3FirstParseStore, *sourcePagesRepository, types.WikiReleaseScope, capture.Identity) {
	t.Helper()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	store := NewG3FirstParseStore(captureTestKeys(t))
	result := firstParseNative(t, "First\r\n𠮷", "Second\n")
	scope := types.WikiReleaseScope{TenantID: 7, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}
	id := capture.Identity{
		TenantID: 7, RawKBID: "raw", KnowledgeID: "source", ParseAttempt: 2,
		SourceSHA256: result.NativeStructure.SourceSHA256,
	}
	require.NoError(t, store.save(id, result, []types.ParsedChunk{
		{Content: result.MarkdownContent, Start: 0, End: len([]rune(result.MarkdownContent))},
	}))
	repo := &sourcePagesRepository{
		knowledge: &types.Knowledge{
			ID: "source", TenantID: 7, KnowledgeBaseID: "raw", FileName: "source.pdf",
			CurrentParseAttempt: 9, FileSHA256: captureTestSHA256("new revision"),
		},
		revision: &types.KnowledgeRevision{KnowledgeID: "source", ParseAttempt: 2, FileSHA256: id.SourceSHA256},
	}
	return store, repo, scope, id
}

func TestReadSourceArtifactUsesExactHistoricalAttemptAfterRestart(t *testing.T) {
	store, repo, scope, _ := sourcePagesFixture(t)
	restarted := NewG3FirstParseStore(store.keys)
	a, err := restarted.ReadSourceArtifact(context.Background(), repo, scope, "source", 2)
	require.NoError(t, err)
	require.Equal(t, uint64(7), repo.tenant)
	require.Equal(t, int64(2), repo.attempt)
	require.Equal(t, repo.revision.FileSHA256, a.FileSHA256)
	require.NotEqual(t, repo.knowledge.FileSHA256, a.FileSHA256)
	require.Equal(t, "source.pdf", a.FileName)
	require.Equal(t, "First\r\n𠮷\n\nSecond\n", a.Markdown)
	set, err := source.NewService(sourcePagesStoreFunc(
		func(context.Context, source.Scope, string, int64) (*source.Artifact, error) { return a, nil },
	)).Pages(context.Background(), source.Scope{TenantID: 7, SpaceID: "space"}, "source", 2)
	require.NoError(t, err)
	require.Equal(t, "First\r\n𠮷", set.Pages[0].Text)
}

type sourcePagesStoreFunc func(context.Context, source.Scope, string, int64) (*source.Artifact, error)

func (f sourcePagesStoreFunc) Load(
	ctx context.Context, scope source.Scope, id string, attempt int64,
) (*source.Artifact, error) {
	return f(ctx, scope, id, attempt)
}

func TestReadSourceArtifactRejectsWrongTenantKBAndRevision(t *testing.T) {
	for _, mutate := range []func(*sourcePagesRepository){
		func(r *sourcePagesRepository) { r.knowledge.TenantID++ },
		func(r *sourcePagesRepository) { r.knowledge.KnowledgeBaseID = "other" },
		func(r *sourcePagesRepository) { r.knowledge.ID = "other" },
		func(r *sourcePagesRepository) { r.knowledge.DeletedAt.Valid = true },
		func(r *sourcePagesRepository) { r.revision.ParseAttempt++ },
		func(r *sourcePagesRepository) { r.revision.KnowledgeID = "other" },
		func(r *sourcePagesRepository) { r.knowledgeErr = wikirepository.ErrKnowledgeNotFound },
		func(r *sourcePagesRepository) { r.revisionErr = wikirepository.ErrKnowledgeNotFound },
	} {
		store, repo, scope, _ := sourcePagesFixture(t)
		mutate(repo)
		_, err := store.ReadSourceArtifact(context.Background(), repo, scope, "source", 2)
		require.ErrorIs(t, err, source.ErrNotFound)
	}
}

func TestReadSourceArtifactNeverCreatesMissingCaptureAndRejectsTampering(t *testing.T) {
	store, repo, scope, id := sourcePagesFixture(t)
	key, err := capture.Key(id)
	require.NoError(t, err)
	path := filepath.Join(store.root, key+".json")
	require.NoError(t, os.Remove(path))
	_, err = store.ReadSourceArtifact(context.Background(), repo, scope, "source", 2)
	require.ErrorIs(t, err, source.ErrNotCaptured)
	_, err = os.Stat(path)
	require.ErrorIs(t, err, os.ErrNotExist)
	require.NoError(t, os.WriteFile(path, []byte(`{"payload":"tampered"}`), 0o600))
	_, err = store.ReadSourceArtifact(context.Background(), repo, scope, "source", 2)
	var failure *source.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, source.ErrorIntegrity, failure.Code)
}

func TestReadSourceArtifactPreservesBackendFailureAndChecksCancellation(t *testing.T) {
	store, repo, scope, _ := sourcePagesFixture(t)
	want := errors.New("backend failure")
	repo.knowledgeErr = want
	_, err := store.ReadSourceArtifact(context.Background(), repo, scope, "source", 2)
	require.ErrorIs(t, err, want)
	repo.knowledgeCalls = 0
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = store.ReadSourceArtifact(ctx, repo, scope, "source", 2)
	require.ErrorIs(t, err, context.Canceled)
	require.Zero(t, repo.knowledgeCalls)
}
