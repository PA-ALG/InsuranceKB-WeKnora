package service

import (
	"context"
	"crypto/sha256"
	"fmt"
	"io"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type revisionSourceRepositoryStub struct {
	interfaces.KnowledgeRepository
	knowledge   *types.Knowledge
	current     *types.KnowledgeRevision
	last        *types.KnowledgeRevision
	source      *types.KnowledgeRevisionSource
	resource    *types.StoredResource
	stateErr    error
	stateCalls  int
	sourceErr   error
	sealErr     error
	sealCalls   int
	captured    types.KnowledgeRevisionSource
	pinned      bool
	pinnedCalls int
}

func (s *revisionSourceRepositoryStub) GetRevisionState(
	context.Context, string,
) (*types.Knowledge, *types.KnowledgeRevision, *types.KnowledgeRevision, error) {
	s.stateCalls++
	return s.knowledge, s.current, s.last, s.stateErr
}

func (s *revisionSourceRepositoryStub) GetRevisionSource(
	context.Context, uint64, string, int64,
) (*types.KnowledgeRevisionSource, *types.StoredResource, error) {
	return s.source, s.resource, s.sourceErr
}

func (s *revisionSourceRepositoryStub) SealRevisionSourceBinding(
	_ context.Context, source types.KnowledgeRevisionSource,
) (*types.KnowledgeRevisionSource, error) {
	s.sealCalls++
	s.captured = source
	if s.sealErr != nil {
		return nil, s.sealErr
	}
	copy := source
	return &copy, nil
}

func (s *revisionSourceRepositoryStub) HasPinnedRevisionSource(
	context.Context, uint64, string,
) (bool, error) {
	s.pinnedCalls++
	return s.pinned, nil
}

type revisionSourceResourceCatalogStub struct {
	interfaces.ResourceCatalog
	resource *types.StoredResource
	err      error
	calls    int
}

func (s *revisionSourceResourceCatalogStub) Resolve(
	context.Context, string,
) (*types.StoredResource, error) {
	s.calls++
	return s.resource, s.err
}

type revisionSourceFileServiceStub struct {
	interfaces.FileService
	data  []byte
	err   error
	calls int
	paths []string
}

func (s *revisionSourceFileServiceStub) GetFile(_ context.Context, path string) (io.ReadCloser, error) {
	s.calls++
	s.paths = append(s.paths, path)
	if s.err != nil {
		return nil, s.err
	}
	return io.NopCloser(strings.NewReader(string(s.data))), nil
}

func revisionSourcePDF(pageCount int) []byte {
	var body strings.Builder
	body.WriteString("%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
	body.WriteString(fmt.Sprintf("2 0 obj << /Type /Pages /Count %d /Kids [", pageCount))
	for page := 0; page < pageCount; page++ {
		body.WriteString(fmt.Sprintf(" %d 0 R", page+3))
	}
	body.WriteString(" ] >> endobj\n")
	for page := 0; page < pageCount; page++ {
		body.WriteString(fmt.Sprintf("%d 0 obj << /Type /Page /Parent 2 0 R >> endobj\n", page+3))
	}
	body.WriteString("trailer << /Root 1 0 R >>\n%%EOF\n")
	return []byte(body.String())
}

func revisionSourceFixture(t *testing.T) (*KnowledgeRevisionSourceService, *revisionSourceRepositoryStub, *revisionSourceFileServiceStub) {
	t.Helper()
	pdf := revisionSourcePDF(2)
	digest := fmt.Sprintf("%x", sha256.Sum256(pdf))
	handle := strings.Repeat("h", types.ResourceHandleLength)
	resource := &types.StoredResource{
		ID: "resource-1", Handle: handle, TenantID: 10003,
		Provider: "local", PhysicalPath: "provider-object-key",
		MimeType: "application/pdf", Size: int64(len(pdf)), ContentHash: digest,
		Lifecycle: types.ResourceLifecyclePersistent, State: types.ResourceStateActive,
	}
	knowledge := &types.Knowledge{
		ID: "knowledge-1", TenantID: 10003, KnowledgeBaseID: "raw-kb-1",
		ParseStatus: types.ParseStatusCompleted, CurrentParseAttempt: 2,
		FilePath: types.BuildResourcePath(handle), FileSHA256: digest, FileType: "pdf",
	}
	revision := &types.KnowledgeRevision{
		KnowledgeID: knowledge.ID, ParseAttempt: 2, FileSHA256: digest,
		ManifestAlgorithm: types.RevisionManifestAlgorithm,
		ManifestDigest:    strings.Repeat("a", 64), ChunkCount: 3,
	}
	repo := &revisionSourceRepositoryStub{
		knowledge: knowledge, current: revision, last: revision,
		resource: resource, sourceErr: repository.ErrKnowledgeNotFound,
	}
	files := &revisionSourceFileServiceStub{data: pdf}
	cfg := &config.Config{KnowledgeRevisionSource: &config.KnowledgeRevisionSourceConfig{
		BackfillEnabled: true, MaxObjectBytes: 1 << 20,
	}}
	service := NewKnowledgeRevisionSourceService(
		cfg, repo, files, &revisionSourceResourceCatalogStub{resource: resource},
	)
	return service, repo, files
}

func revisionSourceContext() context.Context {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))
	return context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleAdmin)
}

func TestBackfillKnowledgeRevisionSourceRequiresHumanAdminBeforeAuthorityReads(t *testing.T) {
	for name, mutate := range map[string]func(context.Context) context.Context{
		"missing trusted role": func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
		},
		"contributor": func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleContributor)
		},
		"api key even with admin role": func(ctx context.Context) context.Context {
			return types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 1, FullAccess: true})
		},
	} {
		t.Run(name, func(t *testing.T) {
			service, repo, files := revisionSourceFixture(t)
			_, err := service.BackfillCurrentCompleted(
				mutate(revisionSourceContext()), "knowledge-1", 2,
			)
			require.ErrorIs(t, err, ErrRevisionSourceBackfillDisabled)
			require.Zero(t, repo.stateCalls)
			require.Zero(t, repo.sealCalls)
			require.Zero(t, files.calls)
		})
	}
}

func TestBackfillKnowledgeRevisionSourceUsesOnlyCurrentCompletedAttemptAndRecomputesObject(t *testing.T) {
	service, repo, files := revisionSourceFixture(t)
	sealed, err := service.BackfillCurrentCompleted(revisionSourceContext(), "knowledge-1", 2)
	require.NoError(t, err)
	require.Equal(t, 1, files.calls)
	require.Equal(t, 1, repo.sealCalls)
	require.Equal(t, 2, *sealed.PageCount)
	require.Equal(t, sealed.FileSHA256, sealed.ObjectSHA256)
	require.Equal(t, sealed.ManifestDigest, repo.current.ManifestDigest)
	require.Equal(t, repo.resource.Handle, sealed.ResourceHandle)
	require.Equal(t, types.BuildResourcePath(repo.resource.Handle), sealed.ImmutableLocator)
	require.NoError(t, types.ValidateKnowledgeRevisionSourceBinding(*sealed))
}

func TestBackfillKnowledgeRevisionSourceRejectsZeroStaleAndMissingRevisionBeforeObjectRead(t *testing.T) {
	for name, attempt := range map[string]int64{"zero": 0, "stale": 1} {
		t.Run(name, func(t *testing.T) {
			service, repo, files := revisionSourceFixture(t)
			_, err := service.BackfillCurrentCompleted(revisionSourceContext(), "knowledge-1", attempt)
			require.ErrorIs(t, err, ErrRevisionSourceMismatch)
			require.Zero(t, files.calls)
			require.Zero(t, repo.sealCalls)
		})
	}

	service, repo, files := revisionSourceFixture(t)
	repo.current = nil
	repo.last = nil
	_, err := service.BackfillCurrentCompleted(revisionSourceContext(), "knowledge-1", 2)
	require.ErrorIs(t, err, ErrRevisionSourceMismatch)
	require.Zero(t, files.calls)
	require.Zero(t, repo.sealCalls)

	service, repo, files = revisionSourceFixture(t)
	driftedLast := *repo.last
	driftedLast.ManifestDigest = strings.Repeat("f", 64)
	repo.last = &driftedLast
	_, err = service.BackfillCurrentCompleted(revisionSourceContext(), "knowledge-1", 2)
	require.ErrorIs(t, err, ErrRevisionSourceMismatch)
	require.Zero(t, files.calls)
	require.Zero(t, repo.sealCalls)
}

func TestReadFixedRevisionSourceRejectsBindingAndPageDriftBeforeBytes(t *testing.T) {
	service, repo, files := revisionSourceFixture(t)
	sealed, err := service.BackfillCurrentCompleted(revisionSourceContext(), "knowledge-1", 2)
	require.NoError(t, err)
	repo.source = sealed
	repo.sourceErr = nil
	files.calls = 0

	_, err = service.ReadFixedRevision(
		revisionSourceContext(), "knowledge-1", 2,
		sealed.FileSHA256, strings.Repeat("f", 64), 1,
	)
	require.ErrorIs(t, err, ErrRevisionSourceMismatch)
	require.Zero(t, files.calls)

	_, err = service.ReadFixedRevision(
		revisionSourceContext(), "knowledge-1", 2,
		sealed.FileSHA256, sealed.BindingDigest, 12,
	)
	require.ErrorIs(t, err, ErrRevisionSourcePageUnavailable)
	require.Zero(t, files.calls)
}

func TestReadFixedRevisionSourceReturnsOnlyExactPinnedObject(t *testing.T) {
	service, repo, files := revisionSourceFixture(t)
	sealed, err := service.BackfillCurrentCompleted(revisionSourceContext(), "knowledge-1", 2)
	require.NoError(t, err)
	repo.source = sealed
	repo.sourceErr = nil
	files.calls = 0

	opened, err := service.ReadFixedRevision(
		revisionSourceContext(), "knowledge-1", 2,
		sealed.FileSHA256, sealed.BindingDigest, 2,
	)
	require.NoError(t, err)
	require.Equal(t, revisionSourcePDF(2), opened)
	require.Equal(t, []string{sealed.ImmutableLocator}, files.paths[len(files.paths)-1:])
}

func TestPinnedRevisionSourceBlocksKnowledgeDeleteBeforeMutation(t *testing.T) {
	repo := &revisionSourceRepositoryStub{pinned: true}
	err := requireKnowledgeRevisionSourceDeleteAllowed(
		revisionSourceContext(), repo, 10003, "knowledge-1",
	)
	require.ErrorIs(t, err, ErrKnowledgeRevisionSourcePinned)
	require.Equal(t, 1, repo.pinnedCalls)
}
