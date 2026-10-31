// Package revisionsource owns the operational backfill of fixed knowledge revision sources
// (single source and exact3 batch) and the exact fixed-revision byte read.
package revisionsource

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const defaultRevisionSourceMaxObjectBytes int64 = 128 << 20

// Typed failures of the revision-source operations; the handler maps each to one HTTP status.
var (
	ErrRevisionSourceMismatch         = errors.New("REVISION_SOURCE_MISMATCH")
	ErrRevisionSourcePageUnavailable  = errors.New("PAGE_UNAVAILABLE")
	ErrRevisionSourceBackfillDisabled = errors.New("REVISION_SOURCE_BACKFILL_DISABLED")
	ErrRevisionSourceExact3Conflict   = errors.New("REVISION_SOURCE_EXACT3_CONFLICT_STOP")
)

type knowledgeRevisionSourceRepository interface {
	GetRevisionState(context.Context, string) (
		*types.Knowledge, *types.KnowledgeRevision, *types.KnowledgeRevision, error,
	)
	GetRevisionSource(context.Context, uint64, string, int64) (
		*types.KnowledgeRevisionSource, *types.StoredResource, error,
	)
	SealRevisionSourceBinding(
		context.Context, types.KnowledgeRevisionSource,
	) (*types.KnowledgeRevisionSource, error)
}

type knowledgeRevisionSourceExact3Repository interface {
	WithExact3ReadSnapshot(
		context.Context,
		func(interfaces.KnowledgeRevisionSourceExact3SnapshotReader) error,
	) error
}

// KnowledgeRevisionSourceService owns the sole operational backfill and exact
// fixed-revision byte path. It never resolves a current/latest/presigned file.
type KnowledgeRevisionSourceService struct {
	config          *config.Config
	repo            knowledgeRevisionSourceRepository
	exact3Repo      knowledgeRevisionSourceExact3Repository
	files           interfaces.FileService
	resources       interfaces.ResourceCatalog
	storageResolver interfaces.StorageBackendResolver
	tenants         interfaces.TenantRepository
}

// NewKnowledgeRevisionSourceService wires the service; repository capabilities it needs are optional
// interfaces of the knowledge repository and fail closed when absent.
func NewKnowledgeRevisionSourceService(
	cfg *config.Config,
	repo interfaces.KnowledgeRepository,
	files interfaces.FileService,
	resources interfaces.ResourceCatalog,
	storageResolver interfaces.StorageBackendResolver,
	tenants interfaces.TenantRepository,
) *KnowledgeRevisionSourceService {
	revisionRepo, _ := repo.(knowledgeRevisionSourceRepository)
	exact3Repo, _ := repo.(knowledgeRevisionSourceExact3Repository)
	return &KnowledgeRevisionSourceService{
		config: cfg, repo: revisionRepo, exact3Repo: exact3Repo,
		files: files, resources: resources, storageResolver: storageResolver, tenants: tenants,
	}
}

func (s *KnowledgeRevisionSourceService) maxObjectBytes() int64 {
	if s != nil && s.config != nil && s.config.KnowledgeRevisionSource != nil &&
		s.config.KnowledgeRevisionSource.MaxObjectBytes > 0 {
		return s.config.KnowledgeRevisionSource.MaxObjectBytes
	}
	return defaultRevisionSourceMaxObjectBytes
}

// BackfillCurrentCompleted seals the revision source of the knowledge's current completed parse
// attempt; only a human tenant admin may call it.
func (s *KnowledgeRevisionSourceService) BackfillCurrentCompleted(
	ctx context.Context,
	knowledgeID string,
	parseAttempt int64,
) (*types.KnowledgeRevisionSource, error) {
	tenantID, err := s.authorizeBackfill(ctx)
	if err != nil {
		return nil, err
	}
	source, err := s.prepareCurrentCompleted(ctx, tenantID, "", knowledgeID, parseAttempt)
	if err != nil {
		return nil, err
	}
	return s.sealPreparedRevisionSource(ctx, source)
}

func (s *KnowledgeRevisionSourceService) authorizeBackfill(ctx context.Context) (uint64, error) {
	if _, apiKey := types.TenantAPIKeyScopeFromContext(ctx); apiKey ||
		!types.TenantRoleFromContext(ctx).HasPermission(types.TenantRoleAdmin) {
		return 0, ErrRevisionSourceBackfillDisabled
	}
	if s == nil || s.repo == nil || s.files == nil || s.resources == nil ||
		s.config == nil || s.config.KnowledgeRevisionSource == nil ||
		!s.config.KnowledgeRevisionSource.BackfillEnabled {
		return 0, ErrRevisionSourceBackfillDisabled
	}
	tenantID, ok := ctx.Value(types.TenantIDContextKey).(uint64)
	if !ok || tenantID == 0 {
		return 0, ErrRevisionSourceMismatch
	}
	return tenantID, nil
}

func (s *KnowledgeRevisionSourceService) prepareCurrentCompleted(
	ctx context.Context,
	tenantID uint64,
	expectedKnowledgeBaseID string,
	knowledgeID string,
	parseAttempt int64,
) (types.KnowledgeRevisionSource, error) {
	if tenantID == 0 || knowledgeID == "" || parseAttempt <= 0 {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	knowledge, current, last, err := s.repo.GetRevisionState(ctx, knowledgeID)
	if err != nil || knowledge == nil || current == nil || last == nil || knowledge.DeletedAt.Valid ||
		knowledge.TenantID != tenantID || knowledge.ID != knowledgeID ||
		(expectedKnowledgeBaseID != "" && knowledge.KnowledgeBaseID != expectedKnowledgeBaseID) ||
		knowledge.ParseStatus != types.ParseStatusCompleted ||
		knowledge.CurrentParseAttempt != parseAttempt || current.ParseAttempt != parseAttempt ||
		current.KnowledgeID != knowledgeID || current.FileSHA256 != knowledge.FileSHA256 ||
		last.KnowledgeID != current.KnowledgeID || last.ParseAttempt != current.ParseAttempt ||
		last.FileSHA256 != current.FileSHA256 || last.ManifestDigest != current.ManifestDigest ||
		current.ManifestAlgorithm != types.RevisionManifestAlgorithm || current.ChunkCount <= 0 {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	resource, err := s.resources.Resolve(ctx, knowledge.FilePath)
	if err != nil || resource == nil || resource.TenantID != tenantID ||
		resource.State != types.ResourceStateActive ||
		resource.Lifecycle != types.ResourceLifecyclePersistent ||
		!strings.EqualFold(strings.TrimSpace(resource.MimeType), "application/pdf") ||
		resource.Size <= 0 || resource.Handle == "" {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	data, err := s.readResourceObject(ctx, resource)
	if err != nil || int64(len(data)) != resource.Size {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	objectDigest := sha256.Sum256(data)
	objectSHA256 := hex.EncodeToString(objectDigest[:])
	if objectSHA256 != current.FileSHA256 ||
		(resource.ContentHash != "" && resource.ContentHash != objectSHA256) {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	pageCount, err := countImmutablePDFPages(data)
	if err != nil || pageCount <= 0 {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourcePageUnavailable
	}
	source := types.KnowledgeRevisionSource{
		TenantID: tenantID, KnowledgeID: knowledgeID, ParseAttempt: parseAttempt,
		ResourceID: resource.ID, ResourceHandle: resource.Handle,
		FileSHA256: current.FileSHA256, ObjectSHA256: objectSHA256,
		Size: resource.Size, MimeType: strings.ToLower(strings.TrimSpace(resource.MimeType)),
		PageCount: &pageCount, ManifestAlgorithm: current.ManifestAlgorithm,
		ManifestDigest: current.ManifestDigest, ChunkCount: current.ChunkCount,
		ImmutableLocator: types.BuildResourcePath(resource.Handle),
		RetentionState:   types.KnowledgeRevisionSourcePinned,
	}
	sourceID, err := types.ComputeKnowledgeRevisionSourceID(source)
	if err != nil {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	source.RevisionSourceID = sourceID
	bindingDigest, err := types.ComputeKnowledgeRevisionSourceBindingDigest(source)
	if err != nil {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	source.BindingDigest = bindingDigest
	if types.ValidateKnowledgeRevisionSourceBinding(source) != nil {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	return source, nil
}

func (s *KnowledgeRevisionSourceService) sealPreparedRevisionSource(
	ctx context.Context,
	source types.KnowledgeRevisionSource,
) (*types.KnowledgeRevisionSource, error) {
	sealed, err := s.repo.SealRevisionSourceBinding(ctx, source)
	if err != nil || sealed == nil || types.ValidateKnowledgeRevisionSourceBinding(*sealed) != nil {
		return nil, ErrRevisionSourceMismatch
	}
	return sealed, nil
}
