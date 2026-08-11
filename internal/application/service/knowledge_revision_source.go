package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
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
)

const (
	KnowledgeRevisionSourceExact3ContractV1 = "knowledge-revision-source-exact3-backfill.v1"
	KnowledgeRevisionSourceRoleTerms        = "terms"
	KnowledgeRevisionSourceRoleBrochure     = "brochure"
	KnowledgeRevisionSourceRoleRateTable    = "rate_table"
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
	Role             string `json:"role"`
	KnowledgeID      string `json:"knowledge_id"`
	ParseAttempt     int64  `json:"parse_attempt"`
	RevisionSourceID string `json:"revision_source_id"`
	FileSHA256       string `json:"file_sha256"`
	PageCount        int    `json:"page_count"`
	ManifestDigest   string `json:"manifest_digest"`
	BindingDigest    string `json:"binding_digest"`
	RetentionState   string `json:"retention_state"`
}

type KnowledgeRevisionSourceExact3ResultV1 struct {
	Contract       string                                   `json:"contract"`
	DryRun         bool                                     `json:"dry_run"`
	ValidatedRoles []string                                 `json:"validated_roles"`
	Sources        []KnowledgeRevisionSourceExact3ReceiptV1 `json:"sources"`
}

type KnowledgeRevisionSourceExact3Error struct {
	FailedRole string
	Err        error
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

type knowledgeRevisionSourceDeleteGuard interface {
	HasPinnedRevisionSource(context.Context, uint64, string) (bool, error)
}

// KnowledgeRevisionSourceService owns the sole operational backfill and exact
// fixed-revision byte path. It never resolves a current/latest/presigned file.
type KnowledgeRevisionSourceService struct {
	config    *config.Config
	repo      knowledgeRevisionSourceRepository
	files     interfaces.FileService
	resources interfaces.ResourceCatalog
}

func NewKnowledgeRevisionSourceService(
	cfg *config.Config,
	repo interfaces.KnowledgeRepository,
	files interfaces.FileService,
	resources interfaces.ResourceCatalog,
) *KnowledgeRevisionSourceService {
	revisionRepo, _ := repo.(knowledgeRevisionSourceRepository)
	return &KnowledgeRevisionSourceService{
		config: cfg, repo: revisionRepo, files: files, resources: resources,
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
	prepared := make([]types.KnowledgeRevisionSource, 0, len(request.Sources))
	for _, item := range request.Sources {
		source, err := s.prepareCurrentCompleted(
			ctx, tenantID, knowledgeBaseID, item.KnowledgeID, item.ParseAttempt,
		)
		if err != nil || source.FileSHA256 != item.ExpectedFileSHA256 ||
			source.ManifestDigest != item.ExpectedManifestDigest {
			if err == nil {
				err = ErrRevisionSourceMismatch
			}
			return nil, &KnowledgeRevisionSourceExact3Error{FailedRole: item.Role, Err: err}
		}
		prepared = append(prepared, source)
	}
	result := &KnowledgeRevisionSourceExact3ResultV1{
		Contract: KnowledgeRevisionSourceExact3ContractV1,
		DryRun:   request.DryRun,
		ValidatedRoles: []string{
			KnowledgeRevisionSourceRoleTerms,
			KnowledgeRevisionSourceRoleBrochure,
			KnowledgeRevisionSourceRoleRateTable,
		},
		Sources: make([]KnowledgeRevisionSourceExact3ReceiptV1, 0, len(prepared)),
	}
	for index, source := range prepared {
		if !request.DryRun {
			fresh, err := s.prepareCurrentCompleted(
				ctx,
				tenantID,
				knowledgeBaseID,
				request.Sources[index].KnowledgeID,
				request.Sources[index].ParseAttempt,
			)
			if err != nil || fresh.BindingDigest != source.BindingDigest {
				if err == nil {
					err = ErrRevisionSourceMismatch
				}
				return nil, &KnowledgeRevisionSourceExact3Error{
					FailedRole: request.Sources[index].Role, Err: err,
				}
			}
			sealed, err := s.sealPreparedRevisionSource(ctx, fresh)
			if err != nil {
				return nil, &KnowledgeRevisionSourceExact3Error{
					FailedRole: request.Sources[index].Role, Err: err,
				}
			}
			source = *sealed
		}
		result.Sources = append(result.Sources, exact3RevisionSourceReceipt(
			request.Sources[index].Role, source,
		))
	}
	return result, nil
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
	source types.KnowledgeRevisionSource,
) KnowledgeRevisionSourceExact3ReceiptV1 {
	pageCount := 0
	if source.PageCount != nil {
		pageCount = *source.PageCount
	}
	return KnowledgeRevisionSourceExact3ReceiptV1{
		Role: role, KnowledgeID: source.KnowledgeID, ParseAttempt: source.ParseAttempt,
		RevisionSourceID: source.RevisionSourceID, FileSHA256: source.FileSHA256,
		PageCount: pageCount, ManifestDigest: source.ManifestDigest,
		BindingDigest: source.BindingDigest, RetentionState: source.RetentionState,
	}
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
