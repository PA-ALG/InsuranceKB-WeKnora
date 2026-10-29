package managed

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// SearchPagesAcross guards upstream's cross-KB native Wiki search (v0.9.0
// /wiki-search and Agent callers). Its KB ids arrive in the request body, so the
// path guards cannot see them; a release-managed KB in the list is refused
// before any native page is read, matching CheckRead on single-KB reads.
func (s *classifiedWikiService) SearchPagesAcross(
	ctx context.Context, kbIDs []string, query string, limit int,
) ([]*types.WikiPage, error) {
	tenant, ok := types.TenantIDFromContext(ctx)
	if !ok || tenant == 0 {
		return nil, &ReadError{Code: ErrorCodeClassificationUnavailable}
	}
	owner := ForKnowledgeBaseOwner(s.classifier, s.lookup)
	for _, kbID := range kbIDs {
		if err := CheckRead(ctx, owner, tenant, kbID); err != nil {
			return nil, err
		}
	}
	return s.WikiPageService.SearchPagesAcross(ctx, kbIDs, query, limit)
}
