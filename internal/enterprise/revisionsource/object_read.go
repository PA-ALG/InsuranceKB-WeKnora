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
