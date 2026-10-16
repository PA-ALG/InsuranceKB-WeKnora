package releasestore

import (
	"context"
	"errors"
	"strconv"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// SourceRevisions is the read-only part of the knowledge repository the resolver needs.
type SourceRevisions interface {
	GetKnowledgeByID(ctx context.Context, tenantID uint64, id string) (*types.Knowledge, error)
	GetRevision(ctx context.Context, knowledgeID string, attempt int64) (*types.KnowledgeRevision, error)
}

// Evidence resolves the reference format frozen by S4c-2a Spec §3.2:
//
//	source:v1:<knowledge_id>:<parse_attempt>:<file_sha256>
//
// A reference resolves when the knowledge belongs to the request tenant and to the
// raw KB of the request Space, and that parse attempt exists with exactly that file
// fingerprint. Quote-level verification and locators arrive with S4c-2b. Unknown
// formats, foreign or missing sources resolve to false; storage errors reject the bundle.
type Evidence struct {
	spaces  Spaces
	sources SourceRevisions
}

// NewEvidence builds the resolver for the configured Spaces.
func NewEvidence(spaces Spaces, sources SourceRevisions) *Evidence {
	return &Evidence{spaces: spaces, sources: sources}
}

var errNoScope = errors.New("evidence resolution needs the authenticated request scope")

// Resolve checks one reference within the authenticated scope of the request.
func (e *Evidence) Resolve(ctx context.Context, ref string) (bool, error) {
	scope, ok := release.ScopeFromContext(ctx)
	if !ok {
		return false, errNoScope
	}
	space, err := e.spaces.Scope(scope.Principal.TenantID, scope.SpaceID)
	if err != nil {
		return false, nil
	}
	parsed, ok := release.ParseSourceRef(ref)
	if !ok {
		return false, nil
	}
	found, err := e.revision(ctx, scope, parsed.KnowledgeID, parsed.ParseAttempt)
	if err != nil {
		return false, err
	}
	return found.exists && found.rawKBID == space.RawKBID && found.fileSHA256 == parsed.FileSHA256, nil
}

// sourceRevision is what one (knowledge, attempt) lookup establishes.
type sourceRevision struct {
	exists     bool
	rawKBID    string
	fileSHA256 string
}

// revision looks a (knowledge, attempt) up once per request (S4c-2a Spec §3.2): bundles often
// cite the same document many times. Each reference still compares its own fingerprint.
func (e *Evidence) revision(
	ctx context.Context, scope release.Scope, knowledgeID string, attempt int64,
) (sourceRevision, error) {
	value, err := scope.Remember(knowledgeID+"\x00"+strconv.FormatInt(attempt, 10), func() (any, error) {
		knowledge, err := e.sources.GetKnowledgeByID(ctx, scope.Principal.TenantID, knowledgeID)
		if errors.Is(err, repository.ErrKnowledgeNotFound) {
			return sourceRevision{}, nil
		}
		if err != nil {
			return nil, err
		}
		revision, err := e.sources.GetRevision(ctx, knowledgeID, attempt)
		if errors.Is(err, repository.ErrKnowledgeNotFound) {
			return sourceRevision{}, nil
		}
		if err != nil {
			return nil, err
		}
		return sourceRevision{exists: true, rawKBID: knowledge.KnowledgeBaseID, fileSHA256: revision.FileSHA256}, nil
	})
	if err != nil {
		return sourceRevision{}, err
	}
	return value.(sourceRevision), nil
}
