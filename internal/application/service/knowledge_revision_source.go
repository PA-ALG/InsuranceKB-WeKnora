package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"regexp"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const defaultRevisionSourceMaxObjectBytes int64 = 128 << 20

var (
	ErrRevisionSourceMismatch         = errors.New("REVISION_SOURCE_MISMATCH")
	ErrRevisionSourcePageUnavailable  = errors.New("PAGE_UNAVAILABLE")
	ErrRevisionSourceBackfillDisabled = errors.New("REVISION_SOURCE_BACKFILL_DISABLED")
	ErrKnowledgeRevisionSourcePinned  = errors.New("KNOWLEDGE_REVISION_SOURCE_PINNED")
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
	if _, apiKey := types.TenantAPIKeyScopeFromContext(ctx); apiKey ||
		!types.TenantRoleFromContext(ctx).HasPermission(types.TenantRoleAdmin) {
		return nil, ErrRevisionSourceBackfillDisabled
	}
	if s == nil || s.repo == nil || s.files == nil || s.resources == nil ||
		s.config == nil || s.config.KnowledgeRevisionSource == nil ||
		!s.config.KnowledgeRevisionSource.BackfillEnabled {
		return nil, ErrRevisionSourceBackfillDisabled
	}
	tenantID, ok := ctx.Value(types.TenantIDContextKey).(uint64)
	if !ok || tenantID == 0 || knowledgeID == "" || parseAttempt <= 0 {
		return nil, ErrRevisionSourceMismatch
	}
	knowledge, current, last, err := s.repo.GetRevisionState(ctx, knowledgeID)
	if err != nil || knowledge == nil || current == nil || last == nil || knowledge.DeletedAt.Valid ||
		knowledge.TenantID != tenantID || knowledge.ID != knowledgeID ||
		knowledge.ParseStatus != types.ParseStatusCompleted ||
		knowledge.CurrentParseAttempt != parseAttempt || current.ParseAttempt != parseAttempt ||
		current.KnowledgeID != knowledgeID || current.FileSHA256 != knowledge.FileSHA256 ||
		last.KnowledgeID != current.KnowledgeID || last.ParseAttempt != current.ParseAttempt ||
		last.FileSHA256 != current.FileSHA256 || last.ManifestDigest != current.ManifestDigest ||
		current.ManifestAlgorithm != types.RevisionManifestAlgorithm || current.ChunkCount <= 0 {
		return nil, ErrRevisionSourceMismatch
	}
	resource, err := s.resources.Resolve(ctx, knowledge.FilePath)
	if err != nil || resource == nil || resource.TenantID != tenantID ||
		resource.State != types.ResourceStateActive ||
		resource.Lifecycle != types.ResourceLifecyclePersistent ||
		!strings.EqualFold(strings.TrimSpace(resource.MimeType), "application/pdf") ||
		resource.Size <= 0 || resource.Handle == "" {
		return nil, ErrRevisionSourceMismatch
	}
	data, err := readExactRevisionSourceObject(
		ctx, s.files, types.BuildResourcePath(resource.Handle), s.maxObjectBytes(),
	)
	if err != nil || int64(len(data)) != resource.Size {
		return nil, ErrRevisionSourceMismatch
	}
	objectDigest := sha256.Sum256(data)
	objectSHA256 := hex.EncodeToString(objectDigest[:])
	if objectSHA256 != current.FileSHA256 ||
		(resource.ContentHash != "" && resource.ContentHash != objectSHA256) {
		return nil, ErrRevisionSourceMismatch
	}
	pageCount, err := countImmutablePDFPages(data)
	if err != nil || pageCount <= 0 {
		return nil, ErrRevisionSourcePageUnavailable
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
		return nil, ErrRevisionSourceMismatch
	}
	source.RevisionSourceID = sourceID
	bindingDigest, err := types.ComputeKnowledgeRevisionSourceBindingDigest(source)
	if err != nil {
		return nil, ErrRevisionSourceMismatch
	}
	source.BindingDigest = bindingDigest
	sealed, err := s.repo.SealRevisionSourceBinding(ctx, source)
	if err != nil || sealed == nil || types.ValidateKnowledgeRevisionSourceBinding(*sealed) != nil {
		return nil, ErrRevisionSourceMismatch
	}
	return sealed, nil
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

var (
	pdfObjectPattern      = regexp.MustCompile(`(?s)([1-9][0-9]*)\s+[0-9]+\s+obj\s*(.*?)\s*endobj`)
	pdfTypeCatalogPattern = regexp.MustCompile(`/Type\s*/Catalog(?:\s|/|>>)`)
	pdfTypePagesPattern   = regexp.MustCompile(`/Type\s*/Pages(?:\s|/|>>)`)
	pdfTypePagePattern    = regexp.MustCompile(`/Type\s*/Page(?:\s|/|>>)`)
	pdfPagesRefPattern    = regexp.MustCompile(`/Pages\s+([1-9][0-9]*)\s+[0-9]+\s+R`)
	pdfParentRefPattern   = regexp.MustCompile(`/Parent\s+([1-9][0-9]*)\s+[0-9]+\s+R`)
	pdfCountPattern       = regexp.MustCompile(`/Count\s+([1-9][0-9]*)`)
	pdfKidsPattern        = regexp.MustCompile(`(?s)/Kids\s*\[(.*?)\]`)
	pdfReferencePattern   = regexp.MustCompile(`([1-9][0-9]*)\s+[0-9]+\s+R`)
)

// countImmutablePDFPages walks an uncompressed PDF page tree. Object streams,
// encrypted PDFs and malformed/cyclic trees are rejected instead of guessed.
func countImmutablePDFPages(data []byte) (int, error) {
	if !bytes.HasPrefix(data, []byte("%PDF-")) ||
		bytes.Contains(data, []byte("/Encrypt")) || bytes.Contains(data, []byte("/ObjStm")) {
		return 0, ErrRevisionSourcePageUnavailable
	}
	objects := map[int][]byte{}
	for _, match := range pdfObjectPattern.FindAllSubmatch(data, -1) {
		objectID, err := strconv.Atoi(string(match[1]))
		if err != nil || objectID <= 0 {
			return 0, ErrRevisionSourcePageUnavailable
		}
		if _, duplicate := objects[objectID]; duplicate {
			return 0, ErrRevisionSourcePageUnavailable
		}
		objects[objectID] = match[2]
	}
	rootPagesID := 0
	for _, body := range objects {
		if !pdfTypeCatalogPattern.Match(body) {
			continue
		}
		ref := pdfPagesRefPattern.FindSubmatch(body)
		if len(ref) != 2 || rootPagesID != 0 {
			return 0, ErrRevisionSourcePageUnavailable
		}
		rootPagesID, _ = strconv.Atoi(string(ref[1]))
	}
	if rootPagesID == 0 {
		return 0, ErrRevisionSourcePageUnavailable
	}
	seen := map[int]struct{}{}
	var walk func(int, int) (int, error)
	walk = func(objectID int, parentID int) (int, error) {
		if _, duplicate := seen[objectID]; duplicate {
			return 0, ErrRevisionSourcePageUnavailable
		}
		seen[objectID] = struct{}{}
		body, exists := objects[objectID]
		if !exists {
			return 0, ErrRevisionSourcePageUnavailable
		}
		if pdfTypePagePattern.Match(body) && !pdfTypePagesPattern.Match(body) {
			parent := pdfParentRefPattern.FindSubmatch(body)
			if parentID == 0 || len(parent) != 2 || string(parent[1]) != strconv.Itoa(parentID) {
				return 0, ErrRevisionSourcePageUnavailable
			}
			return 1, nil
		}
		if !pdfTypePagesPattern.Match(body) {
			return 0, ErrRevisionSourcePageUnavailable
		}
		countMatch := pdfCountPattern.FindSubmatch(body)
		kidsMatch := pdfKidsPattern.FindSubmatch(body)
		if len(countMatch) != 2 || len(kidsMatch) != 2 {
			return 0, ErrRevisionSourcePageUnavailable
		}
		expected, _ := strconv.Atoi(string(countMatch[1]))
		refs := pdfReferencePattern.FindAllSubmatch(kidsMatch[1], -1)
		if expected <= 0 || len(refs) == 0 {
			return 0, ErrRevisionSourcePageUnavailable
		}
		total := 0
		for _, ref := range refs {
			childID, _ := strconv.Atoi(string(ref[1]))
			childCount, err := walk(childID, objectID)
			if err != nil {
				return 0, err
			}
			total += childCount
		}
		if total != expected {
			return 0, ErrRevisionSourcePageUnavailable
		}
		return total, nil
	}
	count, err := walk(rootPagesID, 0)
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
