package revisionsource

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"
)

// ReadFixedRevision returns the exact pinned object bytes of one fixed revision source after the
// binding, file digest and page are checked; it never opens a current or latest file.
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
	data, err := s.readResourceObject(ctx, resource)
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

// Resolve the stored backend before opening a resource. A deployment default
// cannot interpret storage:// paths or select another backend on failure.
func (s *KnowledgeRevisionSourceService) readResourceObject(
	ctx context.Context, resource *types.StoredResource,
) ([]byte, error) {
	tenantID, ok := ctx.Value(types.TenantIDContextKey).(uint64)
	if !ok || tenantID == 0 || resource == nil || resource.TenantID != tenantID {
		return nil, ErrRevisionSourceMismatch
	}
	reader := s.files
	backendID, _, scoped := types.ParseStorageBackendPath(resource.PhysicalPath)
	if resource.StorageBackendID != "" || scoped {
		if !scoped || backendID != resource.StorageBackendID || s.storageResolver == nil || s.tenants == nil {
			return nil, ErrRevisionSourceMismatch
		}
		tenant, err := s.tenants.GetTenantByID(ctx, tenantID)
		if err != nil || tenant == nil || tenant.ID != tenantID {
			return nil, ErrRevisionSourceMismatch
		}
		var provider string
		reader, provider, err = s.storageResolver.ResolveFileService(
			ctx, tenant, backendID, resource.Provider, os.Getenv("LOCAL_STORAGE_BASE_DIR"),
		)
		if err != nil || reader == nil || provider != resource.Provider {
			return nil, ErrRevisionSourceMismatch
		}
	}
	return readExactRevisionSourceObject(ctx, reader, types.BuildResourcePath(resource.Handle), s.maxObjectBytes())
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
