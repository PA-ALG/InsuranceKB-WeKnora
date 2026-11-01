package revisionsource

// S11g acceptance: the human-admin "record missing source" operation verifies the stored object's
// bytes against the committed revision before asking the repository to record (or plan) the
// commit-time source row. Spec: docs/design/slices/S11g-Office来源修订记录.md §2.2, §4.

import (
	"context"
	"crypto/sha256"
	"fmt"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type revisionSourceRecorderStub struct {
	*revisionSourceRepositoryStub
	recordCalls int
	gotTenant   uint64
	gotID       string
	gotAttempt  int64
	gotDryRun   bool
	outcome     types.RevisionSourceRecordOutcome
	recordErr   error
}

func (s *revisionSourceRecorderStub) RecordMissingRevisionSource(
	_ context.Context, tenantID uint64, knowledgeID string, parseAttempt int64, dryRun bool,
) (*types.KnowledgeRevisionSource, types.RevisionSourceRecordOutcome, error) {
	s.recordCalls++
	s.gotTenant, s.gotID, s.gotAttempt, s.gotDryRun = tenantID, knowledgeID, parseAttempt, dryRun
	if s.recordErr != nil {
		return nil, "", s.recordErr
	}
	return &types.KnowledgeRevisionSource{KnowledgeID: knowledgeID, ParseAttempt: parseAttempt}, s.outcome, nil
}

func recordMissingFixture(t *testing.T, mimeType, name string) (
	*KnowledgeRevisionSourceService, *revisionSourceRecorderStub, *revisionSourceFileServiceStub,
) {
	t.Helper()
	object := []byte("synthetic office package bytes")
	digest := fmt.Sprintf("%x", sha256.Sum256(object))
	handle := strings.Repeat("h", types.ResourceHandleLength)
	resource := &types.StoredResource{
		ID: "resource-1", Handle: handle, TenantID: 10003,
		Provider: "local", PhysicalPath: "provider-object-key",
		MimeType: mimeType, OriginalName: name, Size: int64(len(object)), ContentHash: digest,
		Lifecycle: types.ResourceLifecyclePersistent, State: types.ResourceStateActive,
	}
	knowledge := &types.Knowledge{
		ID: "knowledge-1", TenantID: 10003, KnowledgeBaseID: "raw-kb-1",
		ParseStatus: types.ParseStatusCompleted, CurrentParseAttempt: 1,
		FilePath: types.BuildResourcePath(handle), FileSHA256: digest,
	}
	revision := &types.KnowledgeRevision{
		KnowledgeID: knowledge.ID, ParseAttempt: 1, FileSHA256: digest,
		ManifestAlgorithm: types.RevisionManifestAlgorithm,
		ManifestDigest:    strings.Repeat("a", 64), ChunkCount: 12,
	}
	repo := &revisionSourceRecorderStub{
		revisionSourceRepositoryStub: &revisionSourceRepositoryStub{
			knowledge: knowledge, current: revision, last: revision, resource: resource,
		},
		outcome: types.RevisionSourceRecordWouldRecord,
	}
	files := &revisionSourceFileServiceStub{data: object}
	cfg := &config.Config{KnowledgeRevisionSource: &config.KnowledgeRevisionSourceConfig{
		BackfillEnabled: true, MaxObjectBytes: 1 << 20,
	}}
	service := NewKnowledgeRevisionSourceService(
		cfg, repo, files, &revisionSourceResourceCatalogStub{resource: resource}, nil, nil,
	)
	return service, repo, files
}

func TestRecordMissingSourceRequiresHumanAdminBeforeAnyRead(t *testing.T) {
	for name, mutate := range map[string]func(context.Context) context.Context{
		"viewer": func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
		},
		"api key even with admin role": func(ctx context.Context) context.Context {
			return types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 1, FullAccess: true})
		},
	} {
		t.Run(name, func(t *testing.T) {
			service, repo, files := recordMissingFixture(t, "", "deck.pptx")
			_, _, err := service.RecordMissingSource(mutate(revisionSourceContext()), "knowledge-1", 1, true)
			require.ErrorIs(t, err, ErrRevisionSourceBackfillDisabled)
			require.Zero(t, repo.stateCalls)
			require.Zero(t, repo.recordCalls)
			require.Zero(t, files.calls)
		})
	}
}

func TestRecordMissingSourceVerifiesObjectBytesThenDelegates(t *testing.T) {
	for _, dryRun := range []bool{true, false} {
		service, repo, files := recordMissingFixture(t, "", "deck.pptx")
		source, outcome, err := service.RecordMissingSource(revisionSourceContext(), "knowledge-1", 1, dryRun)
		require.NoError(t, err)
		require.Equal(t, types.RevisionSourceRecordWouldRecord, outcome)
		require.Equal(t, "knowledge-1", source.KnowledgeID)
		require.Equal(t, 1, files.calls, "the stored object is read once and hashed")
		require.Equal(t, 1, repo.recordCalls)
		require.Equal(t, uint64(10003), repo.gotTenant)
		require.Equal(t, int64(1), repo.gotAttempt)
		require.Equal(t, dryRun, repo.gotDryRun)
	}
}

func TestRecordMissingSourceRefusesBeforeWriting(t *testing.T) {
	type (
		recorder = revisionSourceRecorderStub
		files    = revisionSourceFileServiceStub
		service  = KnowledgeRevisionSourceService
	)
	for name, test := range map[string]struct {
		mime, file  string
		mutate      func(*service, *recorder, *files)
		objectReads int
	}{
		"object bytes drift": {"", "deck.pptx", func(_ *service, _ *recorder, files *files) {
			files.data = []byte("synthetic office package bytes, edited")
		}, 1},
		"unsupported format":              {"text/markdown", "notes.md", nil, 0},
		"foreign mime for an office name": {"image/png", "deck.docx", nil, 0},
		"not the current attempt": {"", "deck.pptx", func(_ *service, repo *recorder, _ *files) {
			repo.knowledge.CurrentParseAttempt = 2
		}, 0},
		"not completed": {"", "deck.pptx", func(_ *service, repo *recorder, _ *files) {
			repo.knowledge.ParseStatus = types.ParseStatusProcessing
		}, 0},
	} {
		t.Run(name, func(t *testing.T) {
			service, repo, files := recordMissingFixture(t, test.mime, test.file)
			if test.mutate != nil {
				test.mutate(service, repo, files)
			}
			_, _, err := service.RecordMissingSource(revisionSourceContext(), "knowledge-1", 1, false)
			require.ErrorIs(t, err, ErrRevisionSourceMismatch)
			require.Zero(t, repo.recordCalls)
			require.Equal(t, test.objectReads, files.calls)
		})
	}
}

func TestRecordMissingSourceFailsClosedWithoutTheRepositoryCapability(t *testing.T) {
	service, repo, files := recordMissingFixture(t, "", "deck.pptx")
	plain := NewKnowledgeRevisionSourceService(
		service.config, repo.revisionSourceRepositoryStub, files,
		&revisionSourceResourceCatalogStub{resource: repo.resource}, nil, nil,
	)
	_, _, err := plain.RecordMissingSource(revisionSourceContext(), "knowledge-1", 1, true)
	require.ErrorIs(t, err, ErrRevisionSourceBackfillDisabled)
	require.Zero(t, files.calls)
}
