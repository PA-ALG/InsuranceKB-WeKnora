package releasestore

import (
	"context"
	"errors"
	"io"
	"io/fs"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

// KnowledgeLookup finds a knowledge of a tenant; deleted knowledge is not found.
type KnowledgeLookup interface {
	GetKnowledgeByID(ctx context.Context, tenantID uint64, id string) (*types.Knowledge, error)
}

// FileOpener opens the stored original file of a knowledge of the request tenant.
type FileOpener interface {
	GetKnowledgeFile(ctx context.Context, id string) (io.ReadCloser, string, error)
}

// SourceFiles opens original files only for knowledge in the RAW KB of a configured
// enterprise Space (S4c-2b-2 Spec §3.5). The caller verifies the bytes against the cited
// fingerprint; this function only decides whether the knowledge may be opened at all.
func SourceFiles(
	spaces Spaces, knowledge KnowledgeLookup, files FileOpener,
) func(ctx context.Context, scope source.Scope, knowledgeID string) (io.ReadCloser, string, error) {
	return func(ctx context.Context, scope source.Scope, knowledgeID string) (io.ReadCloser, string, error) {
		binding, err := spaces.Scope(scope.TenantID, scope.SpaceID)
		if err != nil || knowledge == nil || files == nil {
			return nil, "", source.ErrNotFound
		}
		k, err := knowledge.GetKnowledgeByID(ctx, scope.TenantID, knowledgeID)
		if errors.Is(err, repository.ErrKnowledgeNotFound) {
			return nil, "", source.ErrNotFound
		}
		if err != nil {
			return nil, "", err
		}
		if k == nil || k.TenantID != scope.TenantID || k.KnowledgeBaseID != binding.RawKBID || k.DeletedAt.Valid {
			return nil, "", source.ErrNotFound
		}
		reader, name, err := files.GetKnowledgeFile(ctx, knowledgeID)
		if errors.Is(err, fs.ErrNotExist) {
			return nil, "", source.ErrNotFound
		}
		return reader, name, err
	}
}
