package releasestore

import (
	appservice "github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"gorm.io/gorm"
)

// NewMCPDeps uses the same captured enterprise pages as publishing. Missing
// capture services stay unavailable; reads never fall back to the legacy scope.
func NewMCPDeps(
	db *gorm.DB, spaces Spaces, published *knowledge.Service, releases *release.Service,
	firstParse *appservice.G3FirstParseStore, repo interfaces.KnowledgeRepository,
	kbs interfaces.KnowledgeBaseService, shares interfaces.KBShareService, agents interfaces.AgentShareService,
) mcptools.Deps {
	return mcptools.Deps{
		Spaces: spaces, Heads: New(db, spaces), Knowledge: published,
		Citations: mcptools.NewCitations(releases, enterprisePages(spaces, repo, firstParse)),
		Caller:    mcptools.EndpointCaller(kbs, shares, agents),
	}
}
