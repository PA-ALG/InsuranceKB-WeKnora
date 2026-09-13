package service

import (
	"context"
	"errors"
	"path"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

const (
	G3PlatformUploadSnapshotContractV1 = "g3-platform-upload-snapshot.830.v1"
	g3PlatformUploadMetadataKey        = "product_ingestion_upload"
)

var ErrG3PlatformUploadNotFound = errors.New("G3_PLATFORM_UPLOAD_NOT_FOUND")

type G3PlatformMachineAccessBinding struct {
	PrincipalStorageID string
	APIKeyID           uint64
	Scope              types.WikiReleaseScope
}

type G3PlatformMachineKnowledgeRepository interface {
	GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error)
	FindByMetadataKey(context.Context, uint64, string, string, string) (*types.Knowledge, error)
}

type G3PlatformUploadSnapshotV1 struct {
	Contract     string     `json:"contract"`
	RunID        string     `json:"run_id"`
	Ordinal      int        `json:"ordinal"`
	KnowledgeID  string     `json:"knowledge_id"`
	FileName     string     `json:"file_name"`
	ParseStatus  string     `json:"parse_status"`
	ParseAttempt int64      `json:"parse_attempt"`
	CreatedAt    time.Time  `json:"created_at"`
	UpdatedAt    time.Time  `json:"updated_at"`
	ProcessedAt  *time.Time `json:"processed_at,omitempty"`
}

// G3PlatformMachineAccessService binds machine snapshot reads to one configured
// workspace API key and to the exact active release scope proved by the route.
type G3PlatformMachineAccessService struct {
	knowledge G3PlatformMachineKnowledgeRepository
	releases  *WikiReleaseService
	binding   G3PlatformMachineAccessBinding
}

func NewG3PlatformMachineAccessService(
	knowledge G3PlatformMachineKnowledgeRepository,
	releases *WikiReleaseService,
	binding G3PlatformMachineAccessBinding,
) *G3PlatformMachineAccessService {
	return &G3PlatformMachineAccessService{
		knowledge: knowledge, releases: releases, binding: binding,
	}
}

func (s *G3PlatformMachineAccessService) LookupUpload(
	ctx context.Context,
	scope types.WikiReleaseScope,
	runID string,
	ordinal int,
) (*G3PlatformUploadSnapshotV1, error) {
	if s == nil || s.knowledge == nil || !validG3PlatformMachineID(runID) || ordinal < 0 {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	if _, err := s.authorize(ctx, scope, "g3-platform-upload-lookup"); err != nil {
		return nil, err
	}
	metadataValue := runID + ":" + strconv.Itoa(ordinal)
	knowledge, err := s.knowledge.FindByMetadataKey(
		ctx, scope.TenantID, scope.RawKBID, g3PlatformUploadMetadataKey, metadataValue,
	)
	if err != nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	if knowledge == nil {
		return nil, ErrG3PlatformUploadNotFound
	}
	metadata := knowledge.GetMetadata()
	if knowledge.ID == "" || knowledge.TenantID != scope.TenantID ||
		knowledge.KnowledgeBaseID != scope.RawKBID || metadata == nil ||
		metadata[g3PlatformUploadMetadataKey] != metadataValue ||
		knowledge.CurrentParseAttempt <= 0 {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	fileName := path.Base(strings.ReplaceAll(strings.TrimSpace(knowledge.FileName), "\\", "/"))
	if fileName == "" || fileName == "." || fileName == "/" {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	return &G3PlatformUploadSnapshotV1{
		Contract: G3PlatformUploadSnapshotContractV1,
		RunID:    runID, Ordinal: ordinal, KnowledgeID: knowledge.ID,
		FileName: fileName, ParseStatus: knowledge.ParseStatus,
		ParseAttempt: knowledge.CurrentParseAttempt,
		CreatedAt:    knowledge.CreatedAt, UpdatedAt: knowledge.UpdatedAt,
		ProcessedAt: knowledge.ProcessedAt,
	}, nil
}

func (s *G3PlatformMachineAccessService) AuthorizeG3PlatformSourceSnapshot(
	ctx context.Context,
	scope types.WikiReleaseScope,
	knowledgeID string,
	parseAttempt int64,
) error {
	if s == nil || s.knowledge == nil || !validG3PlatformMachineID(knowledgeID) ||
		parseAttempt <= 0 {
		return ErrG3PlatformSnapshotUnauthorized
	}
	if _, err := s.authorize(ctx, scope, "g3-platform-source-snapshot"); err != nil {
		return err
	}
	knowledge, err := s.knowledge.GetKnowledgeByID(ctx, scope.TenantID, knowledgeID)
	if err != nil {
		return ErrG3PlatformSnapshotUnavailable
	}
	if knowledge == nil || knowledge.ID != knowledgeID || knowledge.TenantID != scope.TenantID ||
		knowledge.KnowledgeBaseID != scope.RawKBID {
		return ErrG3PlatformSnapshotUnauthorized
	}
	return nil
}

func (s *G3PlatformMachineAccessService) AuthorizeG3PlatformBaseSnapshot(
	ctx context.Context,
	scope types.WikiReleaseScope,
	releaseID string,
	activationEpoch uint64,
) error {
	if s == nil || !validG3PlatformMachineID(releaseID) || activationEpoch == 0 {
		return ErrG3PlatformSnapshotUnauthorized
	}
	_, err := s.authorize(ctx, scope, "g3-platform-base-snapshot")
	return err
}

func (s *G3PlatformMachineAccessService) authorize(
	ctx context.Context,
	scope types.WikiReleaseScope,
	operation string,
) (types.WikiReleasePrincipal, error) {
	var empty types.WikiReleasePrincipal
	if s == nil || s.releases == nil || ctx == nil || !validG3PlatformScope(scope) ||
		scope.RawKBID == scope.WikiKBID || scope != s.binding.Scope ||
		s.binding.APIKeyID == 0 || s.binding.PrincipalStorageID == "" {
		return empty, ErrG3PlatformSnapshotUnauthorized
	}
	terminal, principalOK := types.PrincipalFromContext(ctx)
	tenantID, tenantOK := types.TenantIDFromContext(ctx)
	apiKey, keyOK := types.TenantAPIKeyScopeFromContext(ctx)
	expectedPrincipal := types.Principal{
		Type: types.PrincipalAPITenant, ID: strconv.FormatUint(scope.TenantID, 10),
	}
	if !principalOK || terminal != expectedPrincipal ||
		terminal.StorageID() != s.binding.PrincipalStorageID ||
		!tenantOK || tenantID != scope.TenantID || !keyOK ||
		apiKey.KeyID != s.binding.APIKeyID || apiKey.FullAccess || apiKey.IsPlatform() ||
		!exactG3PlatformKBAllowlist(apiKey.KnowledgeBaseIDs, scope) {
		return empty, ErrG3PlatformSnapshotUnauthorized
	}
	principal := types.WikiReleasePrincipal{
		ID: terminal.StorageID(), TenantID: scope.TenantID, SpaceID: scope.SpaceID,
		APIKeyKnowledgeBaseIDs: append([]string(nil), apiKey.KnowledgeBaseIDs...),
	}
	if err := s.releases.verifyAccess(ctx, principal, scope, operation); err != nil {
		return empty, ErrG3PlatformSnapshotUnauthorized
	}
	return principal, nil
}

func exactG3PlatformKBAllowlist(ids []string, scope types.WikiReleaseScope) bool {
	actual := append([]string(nil), ids...)
	expected := []string{scope.RawKBID, scope.WikiKBID}
	slices.Sort(actual)
	slices.Sort(expected)
	return slices.Equal(actual, expected)
}

func validG3PlatformMachineID(value string) bool {
	if value == "" || len(value) > 160 || strings.TrimSpace(value) != value {
		return false
	}
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || char == '-' || char == '_' {
			continue
		}
		return false
	}
	return true
}
