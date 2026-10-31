package mcptools

import (
	"context"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

type citationReader struct {
	service *release.Service
	pages   *source.Service
}

// NewCitations shares HTTP's source verification and applies the same Space-only
// visibility view as published knowledge reads.
func NewCitations(service *release.Service, pages *source.Service) Citations {
	return &citationReader{service: service.SpaceReadView(), pages: pages}
}

func (r *citationReader) Citation(
	ctx context.Context, tenantID uint64, spaceID, releaseID, member string, evidence int,
) (Citation, error) {
	_, caller, ok := endpointIdentity(ctx)
	if !ok || tenantID != caller.TenantID {
		return Citation{}, accessDenied()
	}
	if strings.TrimSpace(releaseID) == "" || strings.EqualFold(strings.TrimSpace(releaseID), "active") ||
		strings.TrimSpace(spaceID) == "" || strings.TrimSpace(member) == "" || evidence < 0 {
		return Citation{}, invalidArguments()
	}
	principal, _ := types.PrincipalFromContext(ctx)
	view, err := enterprise.ReadCitation(ctx, r.service, r.pages,
		release.Principal{TenantID: tenantID, Subject: principal.StorageID()}, spaceID, releaseID, member, evidence)
	if err != nil {
		return Citation{}, err
	}
	if view.Evidence.ReleaseID != releaseID {
		return Citation{}, &release.Error{Code: release.ErrorReleaseConflict}
	}
	if block := view.Block; block != nil {
		return Citation{Document: block.Document, Page: block.Page, Quote: block.Quote}, nil
	}
	return Citation{Document: view.Span.Document, Page: view.Span.Page, Quote: view.Span.Quote}, nil
}
