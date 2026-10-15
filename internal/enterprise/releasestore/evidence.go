package releasestore

import (
	"context"
	"errors"
	"regexp"
	"strconv"
	"strings"

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

var (
	sourceRef  = regexp.MustCompile(`^source:v1:([A-Za-z0-9][A-Za-z0-9_-]{0,63}):([1-9][0-9]{0,18}):([0-9a-f]{64})$`)
	errNoScope = errors.New("evidence resolution needs the authenticated request scope")
)

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
	parts := sourceRef.FindStringSubmatch(strings.TrimSpace(ref))
	if parts == nil || parts[0] != ref {
		return false, nil
	}
	attempt, err := strconv.ParseInt(parts[2], 10, 64)
	if err != nil {
		return false, nil
	}
	knowledge, err := e.sources.GetKnowledgeByID(ctx, scope.Principal.TenantID, parts[1])
	if errors.Is(err, repository.ErrKnowledgeNotFound) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if knowledge.KnowledgeBaseID != space.RawKBID {
		return false, nil
	}
	revision, err := e.sources.GetRevision(ctx, parts[1], attempt)
	if errors.Is(err, repository.ErrKnowledgeNotFound) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return revision.FileSHA256 == parts[3], nil
}
