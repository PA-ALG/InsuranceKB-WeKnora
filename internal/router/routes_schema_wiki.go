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
	c5Guards := []gin.HandlerFunc{
		g.Viewer(),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
	}
	g.apiKeyRoute(
		r,
		http.MethodGet,
		"/knowledgebase/:kb_id/wiki/schema-experiments/:experiment_id/versions/:version_identity",
		apiKeyRetrieve(apiKeyFullAccess()),
		append(append([]gin.HandlerFunc(nil), c5Guards...), schemaHandler.ReadFormalCandidatePreview)...,
	)
	g.apiKeyRoute(
		r,
		http.MethodGet,
		"/knowledgebase/:kb_id/wiki/schema-experiments/:experiment_id/versions/:version_identity/fields/:field_id/selections/:selection_id/content",
		apiKeyRetrieve(apiKeyFullAccess()),
		append(append([]gin.HandlerFunc(nil), c5Guards...), schemaHandler.ReadFormalCandidatePreviewContent)...,
	)

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
	g.apiKeyRoute(
		r,
		http.MethodGet,
		"/knowledgebase/:kb_id/wiki/preparations/:preparation_id/schema-scope",
		apiKeyAny(),
		middleware.DenyAPIKeyPrincipal(),
		g.Admin(),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaHandler.ResolvePreparationScopeParams(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
		schemaHandler.PreparationScope,
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
	entityPages := handler.NewEntityPageGraphHandler830G1(schemaHandler)
	entityGuards := []gin.HandlerFunc{
		g.Viewer(),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
	}
	entityGET := func(path string, endpoint gin.HandlerFunc) {
		read.GET(path, append(append([]gin.HandlerFunc(nil), entityGuards...), endpoint)...)
	}
	entityGET("/entities/:entity_id/overview", entityPages.ReadOverview)
	entityGET("/entities/:entity_id/sections/:section_key", entityPages.ReadSection)
	entityGET("/entities/:entity_id/fields/:field_key", entityPages.ReadField)
	entityGET("/entities/:entity_id/free-wiki", entityPages.ReadFreeWiki)
	activeGET("/releases/:release_id/root", schemaHandler.ReadActiveRoot)
	activeGET("/releases/:release_id/sections/:section_id", schemaHandler.ReadActiveSection)
	activeGET("/releases/:release_id/fields/:field_id", schemaHandler.ReadActiveField)
	activeGET(
		"/releases/:release_id/fields/:field_id/citations/:citation_id/preview",
		schemaHandler.PreviewCurrentCitation,
	)
	read.GET(
		"/citation-content/:token",
		g.Viewer(),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaHandler.RequireCitationContentScope(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
		schemaHandler.ReadCitationContent,
	)

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
	humanStatusGuards := append(append([]gin.HandlerFunc(nil), humanPrefix...),
		schemaWikiKBAccess(g.KBAccessRead("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
	)
	decision := g.apiKeyGroup(
		r.Group("/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id"),
		apiKeyAny(),
	)
	humanDecisionGuards := append(append([]gin.HandlerFunc(nil), humanPrefix...),
		schemaWikiKBAccess(g.KBAccessWrite("kb_id")),
		access.RecordWikiAccessEvidence(),
		schemaHandler.BindCreateScopeParams(),
		schemaWikiKBAccess(g.KBAccessRead("raw_kb_id")),
		access.RecordRawAccessEvidence(),
		access.SealAccess(),
	)
	decision.POST(
		"/schema-experiments/:experiment_id/versions/:version_identity/decision",
		append(append([]gin.HandlerFunc(nil), humanDecisionGuards...),
			schemaHandler.DecideFormalCandidatePreview)...,
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
	humanGET(
		"/preparations/:preparation_id/entities/:entity_id/fields/:field_key/citations/:citation_id/preview",
		schemaHandler.PreviewEntityPagePreparationCitation830G1,
	)
	humanGET(
		"/preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/summary",
		schemaHandler.ReadPreparationGoldenQualitySummary,
	)
	humanGET(
		"/preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/dossier",
		schemaHandler.ReadPreparationGoldenQualityDossier,
	)
	humanGET(
		"/preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/fields/:field_id/evidence/:evidence_id/preview",
		schemaHandler.PreviewPreparationGoldenEvidence,
	)
	human.GET(
		"/golden-quality/successor-status",
		append(append([]gin.HandlerFunc(nil), humanStatusGuards...), schemaHandler.ReadGoldenSuccessorStatus)...,
	)
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
