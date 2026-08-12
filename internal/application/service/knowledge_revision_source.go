package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"strings"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"
)

const defaultRevisionSourceMaxObjectBytes int64 = 128 << 20

var (
	ErrRevisionSourceMismatch         = errors.New("REVISION_SOURCE_MISMATCH")
	ErrRevisionSourcePageUnavailable  = errors.New("PAGE_UNAVAILABLE")
	ErrRevisionSourceBackfillDisabled = errors.New("REVISION_SOURCE_BACKFILL_DISABLED")
	ErrKnowledgeRevisionSourcePinned  = errors.New("KNOWLEDGE_REVISION_SOURCE_PINNED")
	ErrRevisionSourceExact3Conflict   = errors.New("REVISION_SOURCE_EXACT3_CONFLICT_STOP")
)

const (
	KnowledgeRevisionSourceExact3ContractV1 = "knowledge-revision-source-exact3-backfill.v1"
	KnowledgeRevisionSourceRoleTerms        = "terms"
	KnowledgeRevisionSourceRoleBrochure     = "brochure"
	KnowledgeRevisionSourceRoleRateTable    = "rate_table"
	KnowledgeRevisionSourceExact3PlanInsert = "WOULD_INSERT"
	KnowledgeRevisionSourceExact3PlanNoop   = "NOOP"
	KnowledgeRevisionSourceExact3PlanStop   = "CONFLICT_STOP"
)

type KnowledgeRevisionSourceExact3ItemV1 struct {
	Role                   string `json:"role"`
	KnowledgeID            string `json:"knowledge_id"`
	ParseAttempt           int64  `json:"parse_attempt"`
	ExpectedFileSHA256     string `json:"expected_file_sha256"`
	ExpectedManifestDigest string `json:"expected_manifest_digest"`
}

type KnowledgeRevisionSourceExact3RequestV1 struct {
	Contract string                                `json:"contract"`
	DryRun   bool                                  `json:"dry_run"`
	Sources  []KnowledgeRevisionSourceExact3ItemV1 `json:"sources"`
}

type KnowledgeRevisionSourceExact3ReceiptV1 struct {
	Role         string `json:"role"`
	PlanCode     string `json:"plan_code"`
	SourceSHA256 string `json:"source_sha256"`
	ResultSHA256 string `json:"result_sha256"`
}

type KnowledgeRevisionSourceExact3ResultV1 struct {
	Contract          string                                   `json:"contract"`
	DryRun            bool                                     `json:"dry_run"`
	SnapshotIsolation string                                   `json:"snapshot_isolation"`
	SnapshotReadOnly  bool                                     `json:"snapshot_read_only"`
	SnapshotSHA256    string                                   `json:"snapshot_sha256"`
	ValidatedRoles    []string                                 `json:"validated_roles"`
	PlannedRows       int                                      `json:"planned_rows"`
	DuplicateRows     int                                      `json:"duplicate_rows"`
	ConflictRows      int                                      `json:"conflict_rows"`
	Writes            int                                      `json:"writes"`
	Sources           []KnowledgeRevisionSourceExact3ReceiptV1 `json:"sources"`
}

type KnowledgeRevisionSourceExact3Error struct {
	FailedRole string
	Err        error
	Receipt    *KnowledgeRevisionSourceExact3ResultV1
}

func (e *KnowledgeRevisionSourceExact3Error) Error() string {
	return "revision source exact3 backfill failed"
}

func (e *KnowledgeRevisionSourceExact3Error) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Err
}

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

type knowledgeRevisionSourceDeleteGuard interface {
	HasPinnedRevisionSource(context.Context, uint64, string) (bool, error)
}

// KnowledgeRevisionSourceService owns the sole operational backfill and exact
// fixed-revision byte path. It never resolves a current/latest/presigned file.
type KnowledgeRevisionSourceService struct {
	config     *config.Config
	repo       knowledgeRevisionSourceRepository
	exact3Repo knowledgeRevisionSourceExact3Repository
	files      interfaces.FileService
	resources  interfaces.ResourceCatalog
}

func NewKnowledgeRevisionSourceService(
	cfg *config.Config,
	repo interfaces.KnowledgeRepository,
	files interfaces.FileService,
	resources interfaces.ResourceCatalog,
) *KnowledgeRevisionSourceService {
	revisionRepo, _ := repo.(knowledgeRevisionSourceRepository)
	exact3Repo, _ := repo.(knowledgeRevisionSourceExact3Repository)
	return &KnowledgeRevisionSourceService{
		config: cfg, repo: revisionRepo, exact3Repo: exact3Repo,
		files: files, resources: resources,
	}
}

func (s *KnowledgeRevisionSourceService) maxObjectBytes() int64 {
	if s != nil && s.config != nil && s.config.KnowledgeRevisionSource != nil &&
		s.config.KnowledgeRevisionSource.MaxObjectBytes > 0 {
		return s.config.KnowledgeRevisionSource.MaxObjectBytes
	}
	return defaultRevisionSourceMaxObjectBytes
}

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
	data, err := readExactRevisionSourceObject(
		ctx, s.files, types.BuildResourcePath(resource.Handle), s.maxObjectBytes(),
	)
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

func (s *KnowledgeRevisionSourceService) BackfillExact3(
	ctx context.Context,
	knowledgeBaseID string,
	request KnowledgeRevisionSourceExact3RequestV1,
) (*KnowledgeRevisionSourceExact3ResultV1, error) {
	tenantID, err := s.authorizeBackfill(ctx)
	if err != nil {
		return nil, err
	}
	if !validKnowledgeRevisionSourceExact3Request(knowledgeBaseID, request) {
		return nil, ErrRevisionSourceMismatch
	}
	if s.exact3Repo == nil {
		return nil, ErrRevisionSourceBackfillDisabled
	}
	result := &KnowledgeRevisionSourceExact3ResultV1{
		Contract:          KnowledgeRevisionSourceExact3ContractV1,
		DryRun:            request.DryRun,
		SnapshotIsolation: "REPEATABLE_READ",
		SnapshotReadOnly:  true,
		ValidatedRoles: []string{
			KnowledgeRevisionSourceRoleTerms,
			KnowledgeRevisionSourceRoleBrochure,
			KnowledgeRevisionSourceRoleRateTable,
		},
		Sources: make([]KnowledgeRevisionSourceExact3ReceiptV1, 0, len(request.Sources)),
	}
	prepared := make([]types.KnowledgeRevisionSource, 0, len(request.Sources))
	err = s.exact3Repo.WithExact3ReadSnapshot(
		ctx,
		func(reader interfaces.KnowledgeRevisionSourceExact3SnapshotReader) error {
			authorities := make([]*interfaces.KnowledgeRevisionSourceExact3Authority, 0, len(request.Sources))
			for _, item := range request.Sources {
				authority, readErr := reader.GetExact3RevisionSourceAuthority(
					ctx, tenantID, knowledgeBaseID, item.KnowledgeID, item.ParseAttempt,
				)
				if readErr != nil {
					return &KnowledgeRevisionSourceExact3Error{FailedRole: item.Role, Err: readErr}
				}
				authorities = append(authorities, authority)
			}
			result.SnapshotSHA256 = exact3AuthoritySnapshotDigest(request.Sources, authorities)
			for index, item := range request.Sources {
				authority := authorities[index]
				source, prepareErr := s.prepareExact3Authority(ctx, tenantID, knowledgeBaseID, authority)
				if prepareErr != nil || source.FileSHA256 != item.ExpectedFileSHA256 ||
					source.ManifestDigest != item.ExpectedManifestDigest {
					if prepareErr == nil {
						prepareErr = ErrRevisionSourceMismatch
					}
					return &KnowledgeRevisionSourceExact3Error{FailedRole: item.Role, Err: prepareErr}
				}
				planCode := KnowledgeRevisionSourceExact3PlanInsert
				if authority.ExistingSource != nil {
					if authority.Resource.ContentHash != source.ObjectSHA256 ||
						!sameRevisionSourceAuthority(*authority.ExistingSource, source) {
						planCode = KnowledgeRevisionSourceExact3PlanStop
					} else {
						planCode = KnowledgeRevisionSourceExact3PlanNoop
					}
				}
				receipt := exact3RevisionSourceReceipt(item.Role, planCode, source)
				result.Sources = append(result.Sources, receipt)
				prepared = append(prepared, source)
				switch planCode {
				case KnowledgeRevisionSourceExact3PlanInsert:
					result.PlannedRows++
				case KnowledgeRevisionSourceExact3PlanNoop:
					result.DuplicateRows++
				case KnowledgeRevisionSourceExact3PlanStop:
					result.ConflictRows++
					return &KnowledgeRevisionSourceExact3Error{
						FailedRole: item.Role, Err: ErrRevisionSourceExact3Conflict,
						Receipt: result,
					}
				}
			}
			return nil
		},
	)
	if err != nil {
		return nil, err
	}
	if request.DryRun {
		return result, nil
	}
	for index, source := range prepared {
		fresh, prepareErr := s.prepareCurrentCompleted(
			ctx, tenantID, knowledgeBaseID,
			request.Sources[index].KnowledgeID, request.Sources[index].ParseAttempt,
		)
		if prepareErr != nil || fresh.BindingDigest != source.BindingDigest {
			if prepareErr == nil {
				prepareErr = ErrRevisionSourceMismatch
			}
			return nil, &KnowledgeRevisionSourceExact3Error{
				FailedRole: request.Sources[index].Role, Err: prepareErr,
			}
		}
		if result.Sources[index].PlanCode == KnowledgeRevisionSourceExact3PlanNoop {
			existing, _, readErr := s.repo.GetRevisionSource(
				ctx, tenantID, request.Sources[index].KnowledgeID,
				request.Sources[index].ParseAttempt,
			)
			if readErr != nil || existing == nil || !sameRevisionSourceAuthority(*existing, fresh) {
				return nil, &KnowledgeRevisionSourceExact3Error{
					FailedRole: request.Sources[index].Role,
					Err:        ErrRevisionSourceExact3Conflict,
				}
			}
			continue
		}
		if _, sealErr := s.sealPreparedRevisionSource(ctx, fresh); sealErr != nil {
			return nil, &KnowledgeRevisionSourceExact3Error{
				FailedRole: request.Sources[index].Role, Err: sealErr,
			}
		}
		if result.Sources[index].PlanCode == KnowledgeRevisionSourceExact3PlanInsert {
			result.Writes++
		}
	}
	return result, nil
}

func (s *KnowledgeRevisionSourceService) prepareExact3Authority(
	ctx context.Context,
	tenantID uint64,
	knowledgeBaseID string,
	authority *interfaces.KnowledgeRevisionSourceExact3Authority,
) (types.KnowledgeRevisionSource, error) {
	if authority == nil || authority.Knowledge == nil || authority.Current == nil ||
		authority.Last == nil || authority.Resource == nil || authority.ResourceBindingCount != 1 {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	knowledge := authority.Knowledge
	current := authority.Current
	last := authority.Last
	resource := authority.Resource
	if knowledge.DeletedAt.Valid || knowledge.TenantID != tenantID ||
		knowledge.KnowledgeBaseID != knowledgeBaseID || knowledge.ParseStatus != types.ParseStatusCompleted ||
		knowledge.CurrentParseAttempt != current.ParseAttempt || current.ParseAttempt <= 0 ||
		current.KnowledgeID != knowledge.ID || current.FileSHA256 != knowledge.FileSHA256 ||
		last.KnowledgeID != current.KnowledgeID || last.ParseAttempt != current.ParseAttempt ||
		last.FileSHA256 != current.FileSHA256 || last.ManifestDigest != current.ManifestDigest ||
		current.ManifestAlgorithm != types.RevisionManifestAlgorithm || current.ChunkCount <= 0 ||
		resource.TenantID != tenantID || resource.State != types.ResourceStateActive ||
		resource.Lifecycle != types.ResourceLifecyclePersistent ||
		!strings.EqualFold(strings.TrimSpace(resource.MimeType), "application/pdf") ||
		resource.Size <= 0 || knowledge.FilePath != types.BuildResourcePath(resource.Handle) {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	data, err := readExactRevisionSourceObject(
		ctx, s.files, types.BuildResourcePath(resource.Handle), s.maxObjectBytes(),
	)
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
		TenantID: tenantID, KnowledgeID: knowledge.ID, ParseAttempt: current.ParseAttempt,
		ResourceID: resource.ID, ResourceHandle: resource.Handle,
		FileSHA256: current.FileSHA256, ObjectSHA256: objectSHA256,
		Size: resource.Size, MimeType: strings.ToLower(strings.TrimSpace(resource.MimeType)),
		PageCount: &pageCount, ManifestAlgorithm: current.ManifestAlgorithm,
		ManifestDigest: current.ManifestDigest, ChunkCount: current.ChunkCount,
		ImmutableLocator: knowledge.FilePath,
		RetentionState:   types.KnowledgeRevisionSourcePinned,
	}
	source.RevisionSourceID, err = types.ComputeKnowledgeRevisionSourceID(source)
	if err != nil {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(source)
	if err != nil || types.ValidateKnowledgeRevisionSourceBinding(source) != nil {
		return types.KnowledgeRevisionSource{}, ErrRevisionSourceMismatch
	}
	return source, nil
}

func sameRevisionSourceAuthority(left, right types.KnowledgeRevisionSource) bool {
	if left.PageCount == nil || right.PageCount == nil || *left.PageCount != *right.PageCount {
		return false
	}
	return left.TenantID == right.TenantID && left.KnowledgeID == right.KnowledgeID &&
		left.ParseAttempt == right.ParseAttempt && left.RevisionSourceID == right.RevisionSourceID &&
		left.ResourceID == right.ResourceID && left.ResourceHandle == right.ResourceHandle &&
		left.FileSHA256 == right.FileSHA256 && left.ObjectSHA256 == right.ObjectSHA256 &&
		left.Size == right.Size && strings.EqualFold(left.MimeType, right.MimeType) &&
		left.ManifestAlgorithm == right.ManifestAlgorithm && left.ManifestDigest == right.ManifestDigest &&
		left.ChunkCount == right.ChunkCount && left.ImmutableLocator == right.ImmutableLocator &&
		left.BindingDigest == right.BindingDigest &&
		left.RetentionState == types.KnowledgeRevisionSourcePinned && left.ReleasedAt == nil
}

func validKnowledgeRevisionSourceExact3Request(
	knowledgeBaseID string,
	request KnowledgeRevisionSourceExact3RequestV1,
) bool {
	roles := []string{
		KnowledgeRevisionSourceRoleTerms,
		KnowledgeRevisionSourceRoleBrochure,
		KnowledgeRevisionSourceRoleRateTable,
	}
	if knowledgeBaseID == "" || request.Contract != KnowledgeRevisionSourceExact3ContractV1 ||
		len(request.Sources) != len(roles) {
		return false
	}
	seen := make(map[string]struct{}, len(roles))
	for index, item := range request.Sources {
		if item.Role != roles[index] || item.KnowledgeID == "" || item.ParseAttempt <= 0 ||
			!revisionSourceSHA256(item.ExpectedFileSHA256) ||
			!revisionSourceSHA256(item.ExpectedManifestDigest) {
			return false
		}
		if _, exists := seen[item.KnowledgeID]; exists {
			return false
		}
		seen[item.KnowledgeID] = struct{}{}
	}
	return true
}

func exact3RevisionSourceReceipt(
	role string,
	planCode string,
	source types.KnowledgeRevisionSource,
) KnowledgeRevisionSourceExact3ReceiptV1 {
	sourceBytes, _ := json.Marshal(source)
	sourceDigest := sha256.Sum256(append(
		[]byte("knowledge-revision-source-exact3-source.v1\n"), sourceBytes...,
	))
	receipt := KnowledgeRevisionSourceExact3ReceiptV1{
		Role: role, PlanCode: planCode,
		SourceSHA256: hex.EncodeToString(sourceDigest[:]),
	}
	resultBytes, _ := json.Marshal(struct {
		Contract     string `json:"contract"`
		Role         string `json:"role"`
		PlanCode     string `json:"plan_code"`
		SourceSHA256 string `json:"source_sha256"`
	}{
		Contract: KnowledgeRevisionSourceExact3ContractV1,
		Role:     role, PlanCode: planCode, SourceSHA256: receipt.SourceSHA256,
	})
	resultDigest := sha256.Sum256(append(
		[]byte("knowledge-revision-source-exact3-result.v1\n"), resultBytes...,
	))
	receipt.ResultSHA256 = hex.EncodeToString(resultDigest[:])
	return receipt
}

func exact3AuthoritySnapshotDigest(
	items []KnowledgeRevisionSourceExact3ItemV1,
	authorities []*interfaces.KnowledgeRevisionSourceExact3Authority,
) string {
	type snapshotAuthority struct {
		Role                   string                         `json:"role"`
		Knowledge              *types.Knowledge               `json:"knowledge"`
		Current                *types.KnowledgeRevision       `json:"current"`
		Last                   *types.KnowledgeRevision       `json:"last"`
		Resource               *types.StoredResource          `json:"resource"`
		ResourceBindingCount   int64                          `json:"resource_binding_count"`
		ExistingRevisionSource *types.KnowledgeRevisionSource `json:"existing_revision_source"`
	}
	rows := make([]snapshotAuthority, 0, len(authorities))
	for index, authority := range authorities {
		rows = append(rows, snapshotAuthority{
			Role: items[index].Role, Knowledge: authority.Knowledge,
			Current: authority.Current, Last: authority.Last, Resource: authority.Resource,
			ResourceBindingCount:   authority.ResourceBindingCount,
			ExistingRevisionSource: authority.ExistingSource,
		})
	}
	data, _ := json.Marshal(struct {
		Contract string              `json:"contract"`
		Rows     []snapshotAuthority `json:"rows"`
	}{Contract: KnowledgeRevisionSourceExact3ContractV1, Rows: rows})
	digest := sha256.Sum256(append(
		[]byte("knowledge-revision-source-exact3-snapshot.v1\n"), data...,
	))
	return hex.EncodeToString(digest[:])
}

func (s *KnowledgeRevisionSourceService) ReadFixedRevision(
	ctx context.Context,
	knowledgeID string,
	parseAttempt int64,
	expectedFileSHA256 string,
	expectedBindingDigest string,
	pageNumber int,
) ([]byte, error) {
	if s == nil || s.repo == nil || s.files == nil || knowledgeID == "" || parseAttempt <= 0 ||
		pageNumber <= 0 || !revisionSourceSHA256(expectedFileSHA256) ||
		!revisionSourceSHA256(expectedBindingDigest) {
		return nil, ErrRevisionSourceMismatch
	}
	tenantID, ok := ctx.Value(types.TenantIDContextKey).(uint64)
	if !ok || tenantID == 0 {
		return nil, ErrRevisionSourceMismatch
	}
	source, resource, err := s.repo.GetRevisionSource(ctx, tenantID, knowledgeID, parseAttempt)
	if err != nil || source == nil || resource == nil ||
		types.ValidateKnowledgeRevisionSourceBinding(*source) != nil ||
		source.FileSHA256 != expectedFileSHA256 || source.BindingDigest != expectedBindingDigest ||
		source.RetentionState != types.KnowledgeRevisionSourcePinned ||
		resource.ID != source.ResourceID || resource.Handle != source.ResourceHandle ||
		resource.TenantID != tenantID || resource.ContentHash != source.ObjectSHA256 ||
		resource.State != types.ResourceStateActive ||
		resource.Lifecycle != types.ResourceLifecyclePersistent {
		return nil, ErrRevisionSourceMismatch
	}
	if source.PageCount == nil || pageNumber > *source.PageCount {
		return nil, ErrRevisionSourcePageUnavailable
	}
	data, err := readExactRevisionSourceObject(
		ctx, s.files, source.ImmutableLocator, s.maxObjectBytes(),
	)
	if err != nil || int64(len(data)) != source.Size {
		return nil, ErrRevisionSourceMismatch
	}
	digest := sha256.Sum256(data)
	if hex.EncodeToString(digest[:]) != source.ObjectSHA256 {
		return nil, ErrRevisionSourceMismatch
	}
	pageCount, err := countImmutablePDFPages(data)
	if err != nil || pageCount != *source.PageCount || pageNumber > pageCount {
		return nil, ErrRevisionSourcePageUnavailable
	}
	return data, nil
}

func requireKnowledgeRevisionSourceDeleteAllowed(
	ctx context.Context,
	repo interfaces.KnowledgeRepository,
	tenantID uint64,
	knowledgeID string,
) error {
	guard, ok := repo.(knowledgeRevisionSourceDeleteGuard)
	if tenantID == 0 || knowledgeID == "" {
		return ErrKnowledgeRevisionSourcePinned
	}
	// Non-production test doubles and older adapters may not expose the early
	// preflight. The concrete repository still enforces the same condition
	// atomically at DeleteKnowledge/DeleteKnowledgeList.
	if !ok {
		return nil
	}
	pinned, err := guard.HasPinnedRevisionSource(ctx, tenantID, knowledgeID)
	if err != nil {
		return ErrKnowledgeRevisionSourcePinned
	}
	if pinned {
		return ErrKnowledgeRevisionSourcePinned
	}
	return nil
}

func requireKnowledgeRevisionSourceReparseAllowed(
	ctx context.Context,
	repo interfaces.KnowledgeRepository,
	tenantID uint64,
	knowledgeID string,
) error {
	return requireKnowledgeRevisionSourceDeleteAllowed(ctx, repo, tenantID, knowledgeID)
}

func readExactRevisionSourceObject(
	ctx context.Context,
	files interfaces.FileService,
	locator string,
	maxBytes int64,
) ([]byte, error) {
	if files == nil || maxBytes <= 0 {
		return nil, ErrRevisionSourceMismatch
	}
	opened, err := files.GetFile(ctx, locator)
	if err != nil || opened == nil {
		return nil, ErrRevisionSourceMismatch
	}
	data, readErr := io.ReadAll(io.LimitReader(opened, maxBytes+1))
	closeErr := opened.Close()
	if readErr != nil || closeErr != nil || int64(len(data)) > maxBytes {
		return nil, ErrRevisionSourceMismatch
	}
	return data, nil
}

// countImmutablePDFPages validates the complete in-memory PDF and returns the
// page-tree count. The fixed parser supports encrypted PDFs and object streams;
// malformed files and non-empty password requirements fail closed.
func countImmutablePDFPages(data []byte) (count int, err error) {
	if !bytes.HasPrefix(data, []byte("%PDF-")) {
		return 0, ErrRevisionSourcePageUnavailable
	}
	api.DisableConfigDir()
	defer func() {
		if recover() != nil {
			count = 0
			err = ErrRevisionSourcePageUnavailable
		}
	}()
	count, err = api.PageCount(bytes.NewReader(data), model.NewDefaultConfiguration())
	if err != nil || count <= 0 {
		return 0, ErrRevisionSourcePageUnavailable
	}
	return count, nil
}

func revisionSourceSHA256(value string) bool {
	if len(value) != sha256.Size*2 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}
