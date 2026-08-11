package router

import (
	"net/http"

	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/gin-gonic/gin"
)

type schemaWikiReleaseAccessMiddleware interface {
	RecordWikiAccessEvidence() gin.HandlerFunc
	RecordRawAccessEvidence() gin.HandlerFunc
	SealAccess() gin.HandlerFunc
}

// RegisterSchemaWikiRoutes mounts the bounded Schema Wiki facade under the
// existing Wiki KB namespace. It reuses the two production KB ACL checks and
// the existing Wiki release access seal; no caller-composed scope is trusted.
func RegisterSchemaWikiRoutes(
	r *gin.RouterGroup,
	schemaHandler *handler.SchemaWikiHandler,
	access schemaWikiReleaseAccessMiddleware,
	g *rbacGuards,
) {
	if r == nil || schemaHandler == nil || access == nil || g == nil {
		return
	}

	g.apiKeyRoute(
		r,
		http.MethodGet,
		"/knowledgebase/:kb_id/wiki/schema-scope",
		apiKeyRetrieve(apiKeyFullAccess()),
		g.Viewer(),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaHandler.ResolveScopeParams(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
		schemaHandler.Scope,
	)

	read := g.apiKeyGroup(
		r.Group("/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema"),
		apiKeyRetrieve(apiKeyFullAccess()),
	)
	activeGuards := []gin.HandlerFunc{
		g.Viewer(),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaHandler.RequireScopeParams(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
	}
	activeGET := func(path string, endpoint gin.HandlerFunc) {
		read.GET(path, append(append([]gin.HandlerFunc(nil), activeGuards...), endpoint)...)
	}
	activeGET("/domains", schemaHandler.Domains)
	activeGET("/taxonomy/current", schemaHandler.CurrentTaxonomy)
	activeGET("/entities/:entity_id/versions/:version_id/current", schemaHandler.CurrentEntityVersion)
	activeGET("/releases/:release_id/root", schemaHandler.ReadActiveRoot)
	activeGET("/releases/:release_id/sections/:section_id", schemaHandler.ReadActiveSection)
	activeGET("/releases/:release_id/fields/:field_id", schemaHandler.ReadActiveField)
	activeGET(
		"/releases/:release_id/fields/:field_id/citations/:citation_id/preview",
		schemaHandler.PreviewCurrentCitation,
	)
	activeGET("/citation-content/:token", schemaHandler.ReadCitationContent)

	human := read.With(apiKeyAny())
	humanPrefix := []gin.HandlerFunc{middleware.DenyAPIKeyPrincipal(), g.Admin()}
	humanCreateGuards := append(append([]gin.HandlerFunc(nil), humanPrefix...),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaHandler.BindCreateScopeParams(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
	)
	humanPreparationGuards := append(append([]gin.HandlerFunc(nil), humanPrefix...),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaHandler.RequirePreparationScopeParams(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
	)
	human.POST(
		"/preparations",
		append(append([]gin.HandlerFunc(nil), humanCreateGuards...), schemaHandler.CreateDraft)...,
	)
	human.POST(
		"/preparations/:preparation_id/review",
		append(append([]gin.HandlerFunc(nil), humanPreparationGuards...), schemaHandler.ReviewDraft)...,
	)
	humanGET := func(path string, endpoint gin.HandlerFunc) {
		human.GET(path, append(append([]gin.HandlerFunc(nil), humanPreparationGuards...), endpoint)...)
	}
	humanGET("/preparations/:preparation_id/root", schemaHandler.ReadReviewedRoot)
	humanGET("/preparations/:preparation_id/sections/:section_id", schemaHandler.ReadReviewedSection)
	humanGET("/preparations/:preparation_id/fields/:field_id", schemaHandler.ReadReviewedField)
}

func schemaWikiKBAccess(guard gin.HandlerFunc) gin.HandlerFunc {
	return func(c *gin.Context) {
		errorCount := len(c.Errors)
		guard(c)
		if !c.IsAborted() || len(c.Errors) <= errorCount {
			return
		}
		c.Errors = c.Errors[:errorCount]
		if !c.Writer.Written() {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"success": false,
				"error":   gin.H{"message": "wiki release access denied"},
			})
		}
	}
}
