package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"
	"github.com/stretchr/testify/require"
)

type revisionSourceRepositoryStub struct {
	interfaces.KnowledgeRepository
	knowledge      *types.Knowledge
	current        *types.KnowledgeRevision
	last           *types.KnowledgeRevision
	source         *types.KnowledgeRevisionSource
	resource       *types.StoredResource
	stateErr       error
	stateCalls     int
	sourceErr      error
	sealErr        error
	sealCalls      int
	captured       types.KnowledgeRevisionSource
	pinned         bool
	pinnedCalls    int
	knowledgeCalls int
	states         map[string]revisionSourceState
	sealErrAt      int
	sealed         []types.KnowledgeRevisionSource
}

type revisionSourceState struct {
	knowledge *types.Knowledge
	current   *types.KnowledgeRevision
	last      *types.KnowledgeRevision
}

func (s *revisionSourceRepositoryStub) GetKnowledgeByID(
	context.Context, uint64, string,
) (*types.Knowledge, error) {
	s.knowledgeCalls++
	return s.knowledge, s.stateErr
}

func (s *revisionSourceRepositoryStub) GetRevisionState(
	_ context.Context, knowledgeID string,
) (*types.Knowledge, *types.KnowledgeRevision, *types.KnowledgeRevision, error) {
	s.stateCalls++
	if state, ok := s.states[knowledgeID]; ok {
		return state.knowledge, state.current, state.last, s.stateErr
	}
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
	s.sealed = append(s.sealed, source)
	if s.sealErr != nil || (s.sealErrAt > 0 && s.sealCalls == s.sealErrAt) {
		if s.sealErr == nil {
			s.sealErr = fmt.Errorf("seal failed")
		}
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
	resource  *types.StoredResource
	resources map[string]*types.StoredResource
	err       error
	calls     int
}

func (s *revisionSourceResourceCatalogStub) Resolve(
	_ context.Context, path string,
) (*types.StoredResource, error) {
	s.calls++
	if resource, ok := s.resources[path]; ok {
		return resource, s.err
	}
	return s.resource, s.err
}

type revisionSourceFileServiceStub struct {
	interfaces.FileService
	data       []byte
	dataByPath map[string][]byte
	err        error
	calls      int
	paths      []string
}

func (s *revisionSourceFileServiceStub) GetFile(_ context.Context, path string) (io.ReadCloser, error) {
	s.calls++
	s.paths = append(s.paths, path)
	if s.err != nil {
		return nil, s.err
	}
	if data, ok := s.dataByPath[path]; ok {
		return io.NopCloser(strings.NewReader(string(data))), nil
	}
	return io.NopCloser(strings.NewReader(string(s.data))), nil
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
	require.Equal(t, 1, repo.knowledgeCalls)
	require.Equal(t, 1, repo.pinnedCalls)
}

func revisionSourceExact3Fixture(t *testing.T) (
	*KnowledgeRevisionSourceService,
	*revisionSourceRepositoryStub,
	*revisionSourceFileServiceStub,
	KnowledgeRevisionSourceExact3RequestV1,
) {
	t.Helper()
	pdf, err := os.ReadFile(filepath.Join(
		"..", "..", "..", "dataset", "shouxian_product",
		"平安e生保（尊享版）医疗保险", "费率表.pdf",
	))
	require.NoError(t, err)
	fileSHA := fmt.Sprintf("%x", sha256.Sum256(pdf))
	repo := &revisionSourceRepositoryStub{states: map[string]revisionSourceState{}}
	resources := &revisionSourceResourceCatalogStub{resources: map[string]*types.StoredResource{}}
	files := &revisionSourceFileServiceStub{dataByPath: map[string][]byte{}}
	request := KnowledgeRevisionSourceExact3RequestV1{
		Contract: KnowledgeRevisionSourceExact3ContractV1,
		Sources:  make([]KnowledgeRevisionSourceExact3ItemV1, 0, 3),
	}
	for index, role := range []string{
		KnowledgeRevisionSourceRoleTerms,
		KnowledgeRevisionSourceRoleBrochure,
		KnowledgeRevisionSourceRoleRateTable,
	} {
		knowledgeID := fmt.Sprintf("knowledge-%d", index+1)
		handle := strings.Repeat(string(rune('a'+index)), types.ResourceHandleLength)
		path := types.BuildResourcePath(handle)
		manifest := strings.Repeat(fmt.Sprintf("%x", index+1), 64)
		knowledge := &types.Knowledge{
			ID: knowledgeID, TenantID: 10003, KnowledgeBaseID: "raw-kb-1",
			ParseStatus: types.ParseStatusCompleted, CurrentParseAttempt: 2,
			FilePath: path, FileSHA256: fileSHA, FileType: "pdf",
		}
		revision := &types.KnowledgeRevision{
			KnowledgeID: knowledgeID, ParseAttempt: 2, FileSHA256: fileSHA,
			ManifestAlgorithm: types.RevisionManifestAlgorithm,
			ManifestDigest:    manifest, ChunkCount: index + 1,
		}
		repo.states[knowledgeID] = revisionSourceState{
			knowledge: knowledge, current: revision, last: revision,
		}
		resources.resources[path] = &types.StoredResource{
			ID: fmt.Sprintf("resource-%d", index+1), Handle: handle, TenantID: 10003,
			Provider: "local", PhysicalPath: fmt.Sprintf("object-%d", index+1),
			MimeType: "application/pdf", Size: int64(len(pdf)), ContentHash: fileSHA,
			Lifecycle: types.ResourceLifecyclePersistent, State: types.ResourceStateActive,
		}
		files.dataByPath[path] = pdf
		request.Sources = append(request.Sources, KnowledgeRevisionSourceExact3ItemV1{
			Role: role, KnowledgeID: knowledgeID, ParseAttempt: 2,
			ExpectedFileSHA256: fileSHA, ExpectedManifestDigest: manifest,
		})
	}
	service := NewKnowledgeRevisionSourceService(
		&config.Config{KnowledgeRevisionSource: &config.KnowledgeRevisionSourceConfig{
			BackfillEnabled: true, MaxObjectBytes: 2 << 20,
		}},
		repo,
		files,
		resources,
	)
	return service, repo, files, request
}

func TestExact3BackfillPreflightsAllSourcesBeforeStrictSerialSeal(t *testing.T) {
	service, repo, _, request := revisionSourceExact3Fixture(t)
	request.DryRun = true

	result, err := service.BackfillExact3(
		revisionSourceContext(), "raw-kb-1", request,
	)
	require.NoError(t, err)
	require.True(t, result.DryRun)
	require.Equal(t, []string{
		KnowledgeRevisionSourceRoleTerms,
		KnowledgeRevisionSourceRoleBrochure,
		KnowledgeRevisionSourceRoleRateTable,
	}, result.ValidatedRoles)
	require.Equal(t, 3, repo.stateCalls)
	require.Zero(t, repo.sealCalls)

	service, repo, _, request = revisionSourceExact3Fixture(t)
	repo.sealErrAt = 2
	result, err = service.BackfillExact3(
		revisionSourceContext(), "raw-kb-1", request,
	)
	require.Nil(t, result)
	var roleErr *KnowledgeRevisionSourceExact3Error
	require.ErrorAs(t, err, &roleErr)
	require.Equal(t, KnowledgeRevisionSourceRoleBrochure, roleErr.FailedRole)
	require.Equal(t, 5, repo.stateCalls, "all sources must preflight before serial fresh seal checks")
	require.Equal(t, 2, repo.sealCalls, "rate_table must not seal after brochure failure")
	require.Equal(t, []string{
		"knowledge-1", "knowledge-2",
	}, []string{repo.sealed[0].KnowledgeID, repo.sealed[1].KnowledgeID})

	service, repo, _, request = revisionSourceExact3Fixture(t)
	request.Sources[1].ExpectedManifestDigest = strings.Repeat("f", 64)
	result, err = service.BackfillExact3(
		revisionSourceContext(), "raw-kb-1", request,
	)
	require.Nil(t, result)
	require.Error(t, err)
	require.Zero(t, repo.sealCalls, "preflight failure must keep all source rows unwritten")
}
