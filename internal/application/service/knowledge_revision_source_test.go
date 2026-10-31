package service

import (
	"context"
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/revisionsource"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func revisionSourceFixture(t *testing.T) (
	*revisionsource.KnowledgeRevisionSourceService, *revisionSourceRepositoryStub, *revisionSourceFileServiceStub,
) {
	t.Helper()
	pdf, err := os.ReadFile(filepath.Join(
		"..", "..", "..", "dataset", "shouxian_product",
		"平安e生保（尊享版）医疗保险", "费率表.pdf",
	))
	require.NoError(t, err)
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
	service := revisionsource.NewKnowledgeRevisionSourceService(
		cfg, repo, files, &revisionSourceResourceCatalogStub{resource: resource},
		nil, nil,
	)
	return service, repo, files
}

func revisionSourceContext() context.Context {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))
	return context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleAdmin)
}

func TestPinnedRevisionSourceBlocksKnowledgeDeleteBeforeMutation(t *testing.T) {
	repo := &revisionSourceRepositoryStub{pinned: true}
	err := requireKnowledgeRevisionSourceDeleteAllowed(
		revisionSourceContext(), repo, 10003, "knowledge-1",
	)
	require.ErrorIs(t, err, ErrKnowledgeRevisionSourcePinned)
	require.Equal(t, 1, repo.pinnedCalls)
}

func TestPinnedRevisionSourceBlocksDirectReparseBeforeAnyMutation(t *testing.T) {
	_, repo, _ := revisionSourceFixture(t)
	repo.pinned = true
	svc := &knowledgeService{repo: repo}

	result, err := svc.ReparseKnowledge(
		revisionSourceContext(), repo.knowledge.ID, nil,
	)

	require.ErrorIs(t, err, ErrKnowledgeRevisionSourcePinned)
	require.Nil(t, result)
	require.Zero(t, repo.knowledgeCalls, "pinned source is rejected before loading mutable write state")
	require.Equal(t, 1, repo.pinnedCalls)
}
