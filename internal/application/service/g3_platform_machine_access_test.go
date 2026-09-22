package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type g3PlatformMachineKnowledgeStub struct {
	byID             *types.Knowledge
	upload           *types.Knowledge
	err              error
	metadata         string
	findCalls        int
	getIDCalls       int
	fingerprintCalls int
}

type g3MachineUploadProcessingReceiptStub struct {
	receipt G3PlatformSourceProcessingReceiptV1
	err     error
}

func (s g3MachineUploadProcessingReceiptStub) ProcessingReceipt(context.Context, types.WikiReleaseScope, string, int64) (G3PlatformSourceProcessingReceiptV1, error) {
	return s.receipt, s.err
}

func TestG3PlatformUploadSnapshotIncludesCurrentFailedProcessingReceiptWhenAvailable(t *testing.T) {
	scope, binding, repository, _, machine := g3PlatformMachineFixture()
	repository.upload.ParseStatus = "failed"
	receipt := G3PlatformSourceProcessingReceiptV1{Contract: G3PlatformProcessingReceiptContractV1, Availability: G3PlatformProcessingUnavailable, KnowledgeID: repository.upload.ID, ParseAttempt: repository.upload.CurrentParseAttempt, UnavailabilityReason: "LEGACY_NO_JOURNAL", Phases: modelDispatchPhases(nil)}
	var err error
	receipt.ReceiptSHA256, err = modelDispatchDigest(receipt.Contract, receipt)
	require.NoError(t, err)
	machine.processing = g3MachineUploadProcessingReceiptStub{receipt: receipt}
	got, err := machine.LookupUpload(g3PlatformMachineContext(scope, binding), scope, "run-1", 0)
	require.NoError(t, err)
	require.NotNil(t, got.ProcessingReceipt)
	require.Equal(t, int64(3), got.ProcessingReceiptParseAttempt)
	require.Equal(t, "LEGACY_NO_JOURNAL", got.ProcessingReceipt.UnavailabilityReason)
}

func (s *g3PlatformMachineKnowledgeStub) FindFileBySHA256(_ context.Context, tenantID uint64, kbID, sha string) (*types.Knowledge, error) {
	s.fingerprintCalls++
	if s.err != nil {
		return nil, s.err
	}
	if s.upload == nil || s.upload.TenantID != tenantID || s.upload.KnowledgeBaseID != kbID || s.upload.FileSHA256 != sha {
		return nil, nil
	}
	return s.upload, nil
}

func TestG3PlatformMachineFingerprintLookupRejectsForeignOrInvalidFile(t *testing.T) {
	scope, binding, repository, _, machine := g3PlatformMachineFixture()
	ctx := g3PlatformMachineContext(scope, binding)
	repository.upload.Type = "file"
	repository.upload.FileSHA256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	repository.upload.FileSize = 123
	record, err := machine.LookupFileBySHA256(ctx, scope, repository.upload.FileSHA256, "")
	require.NoError(t, err)
	require.Equal(t, repository.upload.ID, record.KnowledgeID)
	require.Equal(t, int64(123), record.FileSize)
	require.Equal(t, 1, repository.fingerprintCalls)
	repository.upload.Type = "url"
	_, err = machine.LookupFileBySHA256(ctx, scope, repository.upload.FileSHA256, "")
	require.Error(t, err)
	repository.upload.Type = "file"
	repository.upload.KnowledgeBaseID = "foreign"
	_, err = machine.LookupFileBySHA256(ctx, scope, repository.upload.FileSHA256, "")
	require.Error(t, err)
}

func TestG3PlatformMachineFingerprintKnownIDKeepsFailedOriginalBinding(t *testing.T) {
	scope, binding, repository, _, machine := g3PlatformMachineFixture()
	ctx := g3PlatformMachineContext(scope, binding)
	repository.byID.Type = "file"
	repository.byID.FileSHA256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	repository.byID.FileSize = 123
	repository.byID.ParseStatus = "failed"
	record, err := machine.LookupFileBySHA256(ctx, scope, repository.byID.FileSHA256, repository.byID.ID)
	require.NoError(t, err)
	require.Equal(t, "failed", record.ParseStatus)
	require.Equal(t, "run-1", *record.OriginalUploadRunID)
	require.Equal(t, 0, *record.OriginalUploadOrdinal)
	_, err = machine.LookupFileBySHA256(ctx, scope, repository.byID.FileSHA256, "different")
	require.Error(t, err)
}

func (s *g3PlatformMachineKnowledgeStub) GetKnowledgeByID(
	_ context.Context, tenantID uint64, knowledgeID string,
) (*types.Knowledge, error) {
	s.getIDCalls++
	if s.err != nil {
		return nil, s.err
	}
	if s.byID == nil || s.byID.TenantID != tenantID || s.byID.ID != knowledgeID {
		return nil, nil
	}
	return s.byID, nil
}

func (s *g3PlatformMachineKnowledgeStub) FindByMetadataKey(
	_ context.Context, tenantID uint64, kbID, key, value string,
) (*types.Knowledge, error) {
	s.findCalls++
	s.metadata = key + "=" + value
	if s.err != nil {
		return nil, s.err
	}
	if s.upload == nil || s.upload.TenantID != tenantID || s.upload.KnowledgeBaseID != kbID {
		return nil, nil
	}
	return s.upload, nil
}

type g3PlatformMachineAccessVerifier struct {
	err      error
	delegate WikiReleaseAccessVerifier
	requests []WikiReleaseAccessRequest
}

func (s *g3PlatformMachineAccessVerifier) VerifyWikiReleaseAccess(
	ctx context.Context, request WikiReleaseAccessRequest,
) error {
	if s.delegate != nil {
		if err := s.delegate.VerifyWikiReleaseAccess(ctx, request); err != nil {
			return err
		}
	}
	s.requests = append(s.requests, request)
	return s.err
}

func g3PlatformMachineFixture() (
	types.WikiReleaseScope,
	G3PlatformMachineAccessBinding,
	*g3PlatformMachineKnowledgeStub,
	*g3PlatformMachineAccessVerifier,
	*G3PlatformMachineAccessService,
) {
	scope := types.WikiReleaseScope{
		TenantID: 42, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1",
	}
	binding := G3PlatformMachineAccessBinding{
		PrincipalStorageID: "api_tenant:42", APIKeyID: 91, Scope: scope,
	}
	now := time.Date(2026, 9, 13, 12, 0, 0, 0, time.UTC)
	knowledge := &types.Knowledge{
		ID: "knowledge-1", TenantID: scope.TenantID, KnowledgeBaseID: scope.RawKBID,
		FileName: "terms.pdf", ParseStatus: types.ParseStatusCompleted,
		CurrentParseAttempt: 3, CreatedAt: now, UpdatedAt: now.Add(time.Minute),
		ProcessedAt: func() *time.Time { value := now.Add(2 * time.Minute); return &value }(),
		Metadata:    types.JSON(`{"product_ingestion_upload":"run-1:0"}`),
	}
	repository := &g3PlatformMachineKnowledgeStub{byID: knowledge, upload: knowledge}
	verifier := &g3PlatformMachineAccessVerifier{
		delegate: NewContextWikiReleaseAccessVerifier(),
	}
	releases := NewWikiReleaseService(nil, verifier, nil, WikiReleaseServiceOptions{})
	machine := NewG3PlatformMachineAccessService(repository, releases, binding)
	return scope, binding, repository, verifier, machine
}

func g3PlatformMachineContext(
	scope types.WikiReleaseScope,
	binding G3PlatformMachineAccessBinding,
) context.Context {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, scope.TenantID)
	ctx = types.WithPrincipal(ctx, types.Principal{Type: types.PrincipalAPITenant, ID: "42"})
	ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{
		KeyID:            binding.APIKeyID,
		KnowledgeBaseIDs: types.StringArray{scope.RawKBID, scope.WikiKBID},
		Capabilities: types.StringArray{
			string(types.APIKeyCapabilityRetrieve), string(types.APIKeyCapabilityIngest),
		},
	})
	principal := types.WikiReleasePrincipal{
		ID: binding.PrincipalStorageID, TenantID: scope.TenantID, SpaceID: scope.SpaceID,
		APIKeyKnowledgeBaseIDs: []string{scope.RawKBID, scope.WikiKBID},
	}
	return SealWikiReleaseAccess(ctx, principal, scope)
}

func TestG3PlatformMachineAccessBindsExactMachineScopeAndUpload(t *testing.T) {
	scope, binding, repository, verifier, machine := g3PlatformMachineFixture()
	ctx := g3PlatformMachineContext(scope, binding)

	record, err := machine.LookupUpload(ctx, scope, "run-1", 0)
	require.NoError(t, err)
	require.Equal(t, G3PlatformUploadSnapshotContractV1, record.Contract)
	require.Equal(t, "run-1", record.RunID)
	require.Equal(t, 0, record.Ordinal)
	require.Equal(t, "knowledge-1", record.KnowledgeID)
	require.Equal(t, "terms.pdf", record.FileName)
	require.Equal(t, types.ParseStatusCompleted, record.ParseStatus)
	require.Equal(t, int64(3), record.ParseAttempt)
	require.NotNil(t, record.ProcessedAt)
	require.Equal(t, "product_ingestion_upload=run-1:0", repository.metadata)
	require.Len(t, verifier.requests, 1)
	require.Equal(t, "g3-platform-upload-lookup", verifier.requests[0].Operation)

	require.NoError(t, machine.AuthorizeG3PlatformSourceSnapshot(
		ctx, scope, "knowledge-1", 3,
	))
	require.NoError(t, machine.AuthorizeG3PlatformBaseSnapshot(
		ctx, scope, "release-1", 9,
	))
	require.Equal(t, 1, repository.getIDCalls)
	require.Len(t, verifier.requests, 3)
}

func TestG3PlatformMachineAccessRejectsIdentityKeyScopeAllowlistAndACLDrift(t *testing.T) {
	scope, binding, repository, verifier, machine := g3PlatformMachineFixture()
	valid := g3PlatformMachineContext(scope, binding)

	tests := map[string]context.Context{
		"missing sealed acl": func() context.Context {
			ctx := context.WithValue(context.Background(), types.TenantIDContextKey, scope.TenantID)
			ctx = types.WithPrincipal(ctx, types.Principal{Type: types.PrincipalAPITenant, ID: "42"})
			return types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{
				KeyID:            binding.APIKeyID,
				KnowledgeBaseIDs: types.StringArray{scope.RawKBID, scope.WikiKBID},
			})
		}(),
		"wrong principal": types.WithPrincipal(valid, types.Principal{
			Type: types.PrincipalAPIExternalUser, ID: "42:other",
		}),
		"wrong key": types.WithTenantAPIKeyScope(valid, types.TenantAPIKeyScope{
			KeyID:            binding.APIKeyID + 1,
			KnowledgeBaseIDs: types.StringArray{scope.RawKBID, scope.WikiKBID},
		}),
		"full key": types.WithTenantAPIKeyScope(valid, types.TenantAPIKeyScope{
			KeyID: binding.APIKeyID, FullAccess: true,
			KnowledgeBaseIDs: types.StringArray{scope.RawKBID, scope.WikiKBID},
		}),
		"extra kb": types.WithTenantAPIKeyScope(valid, types.TenantAPIKeyScope{
			KeyID:            binding.APIKeyID,
			KnowledgeBaseIDs: types.StringArray{scope.RawKBID, scope.WikiKBID, "other"},
		}),
	}
	for name, ctx := range tests {
		t.Run(name, func(t *testing.T) {
			_, err := machine.LookupUpload(ctx, scope, "run-1", 0)
			require.ErrorIs(t, err, ErrG3PlatformSnapshotUnauthorized)
		})
	}
	require.Zero(t, repository.findCalls)
	require.Zero(t, verifier.requests)

	foreign := scope
	foreign.SpaceID = "space-other"
	_, err := machine.LookupUpload(valid, foreign, "run-1", 0)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnauthorized)
	require.Zero(t, repository.findCalls)
}

func TestG3PlatformMachineUploadNotFoundAndSourceMustBelongToRawKB(t *testing.T) {
	scope, binding, repository, verifier, machine := g3PlatformMachineFixture()
	ctx := g3PlatformMachineContext(scope, binding)
	repository.upload = nil

	_, err := machine.LookupUpload(ctx, scope, "run-1", 0)
	require.ErrorIs(t, err, ErrG3PlatformUploadNotFound)
	require.Len(t, verifier.requests, 1)

	repository.byID.KnowledgeBaseID = "other-raw"
	err = machine.AuthorizeG3PlatformSourceSnapshot(ctx, scope, "knowledge-1", 3)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnauthorized)

	repository.byID.KnowledgeBaseID = scope.RawKBID
	repository.byID.ParseStatus = types.ParseStatusProcessing
	require.NoError(t, machine.AuthorizeG3PlatformSourceSnapshot(ctx, scope, "knowledge-1", 3),
		"authorization must preserve a pending source for the snapshot service's readiness check")

	repository.err = errors.New("storage unavailable")
	_, err = machine.LookupUpload(ctx, scope, "run-1", 0)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnavailable)
}
