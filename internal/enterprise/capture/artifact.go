package capture

import (
	"context"
	"errors"
	"os"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

// KnowledgeReader is what ReadSourceArtifact needs from the knowledge repository.
type KnowledgeReader interface {
	GetKnowledgeByID(ctx context.Context, tenantID uint64, id string) (*types.Knowledge, error)
	GetRevision(ctx context.Context, knowledgeID string, parseAttempt int64) (*types.KnowledgeRevision, error)
}

// ReadSourceArtifact reads the exact capture of one historical parse for the source pages. The
// caller resolves an authorized Space and RAW scope; this function still checks the knowledge's
// tenant and RAW ownership and the revision before opening any capture. It never parses.
func ReadSourceArtifact(
	ctx context.Context, store *Store, knowledge KnowledgeReader, scope types.WikiReleaseScope,
	knowledgeID string, attempt int64,
) (*source.Artifact, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if scope.TenantID == 0 || scope.SpaceID == "" || scope.RawKBID == "" ||
		strings.TrimSpace(knowledgeID) == "" || attempt <= 0 {
		return nil, &source.Error{
			Code: source.ErrorInvalidRequest, Detail: "an exact source scope and attempt are required",
		}
	}
	if store == nil || knowledge == nil {
		return nil, &source.Error{Code: source.ErrorUnavailable, Detail: "source artifact is unavailable"}
	}
	owned, err := knowledge.GetKnowledgeByID(ctx, scope.TenantID, knowledgeID)
	if errors.Is(err, repository.ErrKnowledgeNotFound) {
		return nil, source.ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if owned == nil || owned.ID != knowledgeID || owned.TenantID != scope.TenantID ||
		owned.KnowledgeBaseID != scope.RawKBID || owned.DeletedAt.Valid {
		return nil, source.ErrNotFound
	}
	revision, err := knowledge.GetRevision(ctx, knowledgeID, attempt)
	if errors.Is(err, repository.ErrKnowledgeNotFound) {
		return nil, source.ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if revision == nil || revision.KnowledgeID != knowledgeID || revision.ParseAttempt != attempt {
		return nil, source.ErrNotFound
	}
	if !ValidSHA256(revision.FileSHA256) {
		return nil, &source.Error{Code: source.ErrorIntegrity, Detail: "source revision failed integrity verification"}
	}
	id := Identity{
		TenantID: scope.TenantID, RawKBID: scope.RawKBID, KnowledgeID: knowledgeID,
		ParseAttempt: attempt, SourceSHA256: revision.FileSHA256,
	}
	record, err := store.Read(id)
	if errors.Is(err, os.ErrNotExist) {
		return nil, notCaptured(store, id, owned.FileType)
	}
	if errors.Is(err, ErrUnavailable) {
		return nil, &source.Error{Code: source.ErrorIntegrity, Detail: "parse artifact failed integrity verification"}
	}
	if err != nil {
		return nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return &source.Artifact{
		KnowledgeID: knowledgeID, ParseAttempt: attempt, FileName: owned.FileName,
		FileSHA256: revision.FileSHA256, ParserIdentitySHA256: record.ParserIdentitySHA256,
		Markdown: record.Markdown, NativeJSON: append([]byte(nil), record.Native.SanitizedJSON...),
		RevisedAt: revision.CompletedAt,
	}, nil
}
