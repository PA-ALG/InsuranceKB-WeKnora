package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	filesvc "github.com/Tencent/WeKnora/internal/application/service/file"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"
	"github.com/stretchr/testify/require"
)

func TestRevisionSourceUsesStoredBackendForBackfillAndFixedRead(t *testing.T) {
	s, repo, defaultFiles := revisionSourceFixture(t)
	root := t.TempDir()
	require.NoError(t, os.WriteFile(filepath.Join(root, "terms.pdf"), defaultFiles.data, 0600))
	backendID := "30545abd-ae95-4de0-a796-29b5c4bc32c7"
	repo.resource.StorageBackendID = backendID
	repo.resource.PhysicalPath = types.BuildStorageBackendPath(backendID, "local://terms.pdf")
	catalog := s.resources.(*revisionSourceResourceCatalogStub)
	local := filesvc.NewLocalFileService(root, "")
	// Parsing storage:// alone cannot select its configured backend root.
	// The default reader must not resolve a source stored in a different root.
	legacy := filesvc.NewResourceCatalogFileService(filesvc.NewLocalFileService(t.TempDir(), ""), catalog)
	_, err := legacy.GetFile(revisionSourceContext(), repo.knowledge.FilePath)
	require.Error(t, err)
	s.files = defaultFiles
	backend := &revisionSourceBackendStub{reader: filesvc.NewResourceCatalogFileService(filesvc.NewBackendScopedFileService(backendID, local), catalog), provider: "local"}
	s.storageResolver = backend
	s.tenants = &revisionSourceTenantStub{tenant: &types.Tenant{ID: 10003}}
	source, err := s.BackfillCurrentCompleted(revisionSourceContext(), repo.knowledge.ID, 2)
	require.NoError(t, err)
	require.Equal(t, backendID, backend.backendID)
	require.Equal(t, uint64(10003), backend.tenantID)
	repo.source, repo.sourceErr = source, nil
	actual, err := s.ReadFixedRevision(revisionSourceContext(), repo.knowledge.ID, 2, source.FileSHA256, source.BindingDigest, 1)
	require.NoError(t, err)
	require.Equal(t, defaultFiles.data, actual)
	require.Zero(t, defaultFiles.calls)
}

func TestRevisionSourceStoredBackendFailureNeverReadsDefault(t *testing.T) {
	for _, scenario := range []string{"missing-resolver", "backend-drift", "resolver-error", "provider-drift", "tenant-drift"} {
		t.Run(scenario, func(t *testing.T) {
			s, repo, files := revisionSourceFixture(t)
			backendID := "30545abd-ae95-4de0-a796-29b5c4bc32c7"
			repo.resource.StorageBackendID = backendID
			repo.resource.PhysicalPath = types.BuildStorageBackendPath(backendID, "local://terms.pdf")
			resolver := &revisionSourceBackendStub{reader: files, provider: "local"}
			s.storageResolver = resolver
			s.tenants = &revisionSourceTenantStub{tenant: &types.Tenant{ID: 10003}}
			switch scenario {
			case "missing-resolver":
				s.storageResolver = nil
			case "backend-drift":
				repo.resource.StorageBackendID = "foreign-backend"
			case "resolver-error":
				resolver.err = fmt.Errorf("backend unavailable")
			case "provider-drift":
				resolver.provider = "foreign-provider"
			case "tenant-drift":
				s.tenants = &revisionSourceTenantStub{tenant: &types.Tenant{ID: 10004}}
			}
			_, err := s.BackfillCurrentCompleted(revisionSourceContext(), repo.knowledge.ID, 2)
			require.ErrorIs(t, err, ErrRevisionSourceMismatch)
			require.Zero(t, files.calls)
			require.Zero(t, repo.sealCalls)
		})
	}
}

func revisionSourceFixture(t *testing.T) (*KnowledgeRevisionSourceService, *revisionSourceRepositoryStub, *revisionSourceFileServiceStub) {
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
	service := NewKnowledgeRevisionSourceService(
		cfg, repo, files, &revisionSourceResourceCatalogStub{resource: resource},
		nil, nil,
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

func TestImmutablePDFPageCounterAcceptsExact5961EncryptedMaterials(t *testing.T) {
	t.Parallel()
	root := filepath.Join("..", "..", "..", "dataset")
	for _, test := range []struct {
		name   string
		path   string
		sha256 string
		pages  int
	}{
		{
			name:   "terms AES object streams",
			path:   filepath.Join(root, "version-materials", "esb_zunxiang_596-1_tiaokuan.pdf"),
			sha256: "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
			pages:  39,
		},
		{
			name:   "brochure",
			path:   filepath.Join(root, "shouxian_product", "平安e生保（尊享版）医疗保险", "产品说明书.pdf"),
			sha256: "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
			pages:  27,
		},
		{
			name:   "rate table",
			path:   filepath.Join(root, "shouxian_product", "平安e生保（尊享版）医疗保险", "费率表.pdf"),
			sha256: "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
			pages:  2,
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			data, err := os.ReadFile(test.path)
			require.NoError(t, err)
			require.Equal(t, test.sha256, fmt.Sprintf("%x", sha256.Sum256(data)))
			pages, err := countImmutablePDFPages(data)
			require.NoError(t, err)
			require.Equal(t, test.pages, pages)
		})
	}
}

func TestImmutablePDFPageCounterRejectsCorruptExactObject(t *testing.T) {
	data, err := os.ReadFile(filepath.Join(
		"..", "..", "..", "dataset", "version-materials",
		"esb_zunxiang_596-1_tiaokuan.pdf",
	))
	require.NoError(t, err)
	corrupt := append([]byte(nil), data[:len(data)/2]...)
	pages, err := countImmutablePDFPages(corrupt)
	require.ErrorIs(t, err, ErrRevisionSourcePageUnavailable)
	require.Zero(t, pages)

	rate, err := os.ReadFile(filepath.Join(
		"..", "..", "..", "dataset", "shouxian_product",
		"平安e生保（尊享版）医疗保险", "费率表.pdf",
	))
	require.NoError(t, err)
	var passwordProtected bytes.Buffer
	require.NoError(t, api.Encrypt(
		bytes.NewReader(rate),
		&passwordProtected,
		model.NewAESConfiguration("required-user-password", "required-owner-password", 256),
	))
	pages, err = countImmutablePDFPages(passwordProtected.Bytes())
	require.ErrorIs(t, err, ErrRevisionSourcePageUnavailable)
	require.Zero(t, pages)
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
	require.Equal(t, files.data, opened)
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
