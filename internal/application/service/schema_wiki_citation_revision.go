package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"sort"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type schemaWikiCitationRevisionRepository interface {
	GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error)
	GetRevision(context.Context, string, int64) (*types.KnowledgeRevision, error)
}

type schemaWikiCitationChunkRepository interface {
	GetChunkByID(context.Context, uint64, string) (*types.Chunk, error)
	ListChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error)
}

// schemaWikiCitationRevisionReadAdapter verifies every revision fact currently
// available from WeKnora. It deliberately does not open the current-file
// preview: that endpoint is not parse-attempt-bound and therefore cannot
// satisfy CitationRevisionReadPort's immutable-revision promise.
type schemaWikiCitationRevisionReadAdapter struct {
	revisions schemaWikiCitationRevisionRepository
	chunks    schemaWikiCitationChunkRepository
}

// NewSchemaWikiCitationRevisionReadAdapter wires the production repositories
// without widening their long-standing public interfaces. The concrete
// knowledge repository already exposes immutable revision reads; a deployment
// that substitutes an implementation without that capability fails closed.
func NewSchemaWikiCitationRevisionReadAdapter(
	knowledgeRepository interfaces.KnowledgeRepository,
	chunkRepository interfaces.ChunkRepository,
) CitationRevisionReadPort {
	revisions, ok := knowledgeRepository.(schemaWikiCitationRevisionRepository)
	if !ok {
		return &schemaWikiCitationRevisionReadAdapter{}
	}
	return newSchemaWikiCitationRevisionReadAdapter(revisions, chunkRepository)
}

func newSchemaWikiCitationRevisionReadAdapter(
	revisions schemaWikiCitationRevisionRepository,
	chunks schemaWikiCitationChunkRepository,
) CitationRevisionReadPort {
	return &schemaWikiCitationRevisionReadAdapter{revisions: revisions, chunks: chunks}
}

func (a *schemaWikiCitationRevisionReadAdapter) ReadExactRevision(
	ctx context.Context,
	request CitationRevisionReadRequestV1,
) ([]byte, error) {
	if a == nil || a.revisions == nil || a.chunks == nil ||
		request.Scope.TenantID == 0 || request.Scope.SpaceID == "" ||
		request.Scope.RawKBID == "" || request.Scope.WikiKBID == "" ||
		types.ValidateCitationTarget(request.Citation) != nil ||
		request.Citation.SpaceID != request.Scope.SpaceID ||
		request.Binding.CitationSHA256 != request.Citation.CitationSHA256 ||
		request.Binding.LogicalMemberRef != request.Citation.LogicalMemberRef {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	tenantID, ok := ctx.Value(types.TenantIDContextKey).(uint64)
	if !ok || tenantID == 0 || tenantID != request.Scope.TenantID {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	attempt, ok := schemaWikiNativeParseAttempt(request.Citation)
	if !ok {
		return nil, ErrSchemaWikiCitationUnavailable
	}

	knowledge, err := a.revisions.GetKnowledgeByID(ctx, tenantID, request.Citation.KnowledgeID)
	if err != nil || knowledge == nil || knowledge.ID != request.Citation.KnowledgeID ||
		knowledge.TenantID != tenantID || knowledge.KnowledgeBaseID != request.Scope.RawKBID ||
		knowledge.ParseStatus != types.ParseStatusCompleted || !strings.EqualFold(knowledge.FileType, "pdf") {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	revision, err := a.revisions.GetRevision(ctx, request.Citation.KnowledgeID, attempt)
	if err != nil || revision == nil || revision.KnowledgeID != request.Citation.KnowledgeID ||
		revision.ParseAttempt != attempt || revision.FileSHA256 != request.Citation.ParsedDocumentSHA256 ||
		revision.ManifestAlgorithm != types.RevisionManifestAlgorithm ||
		revision.ManifestDigest != request.Citation.ParseManifestSHA256 || revision.ChunkCount <= 0 {
		return nil, ErrSchemaWikiCitationUnavailable
	}

	selected, err := a.chunks.GetChunkByID(ctx, tenantID, request.Citation.ChunkID)
	if err != nil || !schemaWikiCitationChunkMatches(
		selected, request.Scope, request.Citation, attempt,
	) {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	all, err := a.chunks.ListChunksByKnowledgeID(ctx, tenantID, request.Citation.KnowledgeID)
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	manifestRows := make([]types.RevisionManifestChunk, 0, len(all))
	selectedInManifest := false
	for _, chunk := range all {
		if chunk == nil || chunk.ParseAttempt != attempt || chunk.ChunkType != types.ChunkTypeText {
			continue
		}
		if chunk.TenantID != tenantID || chunk.KnowledgeID != request.Citation.KnowledgeID ||
			chunk.KnowledgeBaseID != request.Scope.RawKBID || chunk.ChunkIndex < 0 ||
			chunk.StartAt < 0 || chunk.EndAt < chunk.StartAt {
			return nil, ErrSchemaWikiCitationUnavailable
		}
		manifestRows = append(manifestRows, types.RevisionManifestChunk{
			ID: chunk.ID, Index: chunk.ChunkIndex, Content: chunk.Content,
		})
		if chunk.ID == selected.ID && chunk.ChunkIndex == selected.ChunkIndex &&
			chunk.StartAt == selected.StartAt && chunk.EndAt == selected.EndAt &&
			chunk.Content == selected.Content {
			selectedInManifest = true
		}
	}
	sort.Slice(manifestRows, func(i, j int) bool { return manifestRows[i].Index < manifestRows[j].Index })
	manifestDigest, err := types.ComputeRevisionManifestDigest(
		request.Citation.KnowledgeID, attempt, manifestRows,
	)
	if err != nil || !selectedInManifest || len(manifestRows) != revision.ChunkCount ||
		manifestDigest != revision.ManifestDigest {
		return nil, ErrSchemaWikiCitationUnavailable
	}

	// The sealed page/bbox/coordinate/quote custody has now been joined to
	// the exact native revision and chunk manifest. WeKnora still exposes no
	// immutable attempt-bound blob/page source, so returning bytes would be a
	// false fixed-revision claim. Remain fail closed until such a port exists.
	return nil, ErrSchemaWikiCitationUnavailable
}

func schemaWikiNativeParseAttempt(citation types.CitationTargetV1) (int64, bool) {
	const attemptPrefix = "attempt-"
	const revisionPrefix = "revision-"
	if !strings.HasPrefix(citation.ParseAttemptID, attemptPrefix) ||
		!strings.HasPrefix(citation.SourceRevisionID, revisionPrefix) {
		return 0, false
	}
	attemptText := strings.TrimPrefix(citation.ParseAttemptID, attemptPrefix)
	revisionText := strings.TrimPrefix(citation.SourceRevisionID, revisionPrefix)
	attempt, err := strconv.ParseInt(attemptText, 10, 64)
	if err != nil || attempt <= 0 || attemptText != strconv.FormatInt(attempt, 10) ||
		revisionText != strconv.FormatInt(attempt, 10) {
		return 0, false
	}
	return attempt, true
}

func schemaWikiCitationChunkMatches(
	chunk *types.Chunk,
	scope types.WikiReleaseScope,
	citation types.CitationTargetV1,
	attempt int64,
) bool {
	if chunk == nil || chunk.ID != citation.ChunkID || chunk.TenantID != scope.TenantID ||
		chunk.KnowledgeBaseID != scope.RawKBID || chunk.KnowledgeID != citation.KnowledgeID ||
		chunk.ParseAttempt != attempt || chunk.ChunkType != types.ChunkTypeText ||
		chunk.ChunkIndex < 0 || chunk.StartAt < 0 || chunk.EndAt < chunk.StartAt ||
		!strings.Contains(chunk.Content, citation.QuoteSnapshot) {
		return false
	}
	contentDigest := sha256.Sum256([]byte(chunk.Content))
	return hex.EncodeToString(contentDigest[:]) == citation.ContentSnapshotSHA256
}
