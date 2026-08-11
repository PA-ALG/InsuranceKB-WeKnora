package handler

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	stderrors "errors"
	"fmt"
	"io"
	"net/http"
	"strings"

	apprepo "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

const schemaWikiResolvedHeadContextKey = "schema_wiki.resolved_head"

const maxSchemaWikiRequestBytes = 8 << 20

// SchemaWikiScopeResolver resolves the sole active Schema Wiki scope owned by
// a tenant Wiki KB. Implementations must fail closed on zero or multiple Heads.
type SchemaWikiScopeResolver interface {
	GetHeadForWikiKB(context.Context, uint64, string) (*types.WikiReleaseHead, error)
}

type schemaWikiPreparationScopeResolver interface {
	GetPreparationScopeForWikiKB(context.Context, uint64, string, string) (*types.WikiReleaseScope, error)
}

type schemaWikiHTTPService interface {
	CreateSchemaDraft(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		types.KnowledgeWikiReleaseV1,
		types.Schema67CandidateEvidenceAuthorityV1,
		types.SchemaWikiReviewBundleV1,
		types.Schema67GoldenEvaluationReviewBundleV1,
		types.Schema67GoldenReviewSuccessorMetadataV1,
	) (*types.WikiReleasePreparation, error)
	ReviewSchemaDraft(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		[]byte,
	) (*types.WikiReleasePreparation, error)
	ReadSchemaDraftMember(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
		string,
	) (*types.WikiReleaseMemberSnapshot, error)
	ReadCurrentSchemaMember(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
	) (*service.SchemaWikiMemberReadV1, error)
	SearchCurrentSchemaMembers(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
	) ([]service.SchemaWikiMemberReadV1, error)
	ReadCurrentSchemaAuthority(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
	) (*service.SchemaWikiCurrentAuthorityV1, error)
	ReadReviewedPreparationMember(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
	) (*service.SchemaWikiMemberReadV1, error)
	ReadSchemaPreparationMember(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
	) (*service.SchemaWikiMemberReadV1, error)
	ReadReviewedPreparationRoot(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
	) (*types.SchemaRootPageV1, error)
	ReadCurrentSchemaCitation(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
		string,
	) ([]byte, error)
	IssueCurrentSchemaCitationAuthority(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
		string,
	) (*types.SchemaWikiCitationContentAuthorityV1, error)
	ReadSchemaCitationContent(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
	) ([]byte, error)
	ReadReviewedPreparationCitation(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
		string,
	) ([]byte, error)
	ReadSchemaPreparationGoldenQualitySummary(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
	) (*types.SchemaWikiGoldenQualitySummaryV1, error)
	ReadSchemaPreparationGoldenQualityDossier(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
	) (*types.SchemaWikiGoldenQualityDossierV2, error)
	IssueSchemaPreparationGoldenEvidencePreview(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
		string,
		string,
	) (*types.SchemaWikiGoldenEvidencePreviewAuthorityV1, error)
	ReadSchemaWikiGoldenSuccessorStatus(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
	) (*types.SchemaWikiGoldenSuccessorStatusV1, error)
}

// SchemaWikiHandler exposes the bounded Schema Wiki HTTP facade. Release and
// citation authority stays inside SchemaWikiService; HTTP callers provide only
// path identities and never custody DTOs.
type SchemaWikiHandler struct {
	scopeResolver SchemaWikiScopeResolver
	schemaService schemaWikiHTTPService
}

// NewSchemaWikiHandler constructs the explicitly injected Schema Wiki facade.
func NewSchemaWikiHandler(
	scopeResolver SchemaWikiScopeResolver,
	schemaService schemaWikiHTTPService,
) *SchemaWikiHandler {
	return &SchemaWikiHandler{scopeResolver: scopeResolver, schemaService: schemaService}
}

type schemaWikiCreateDraftRequest struct {
	PreparationID              string                                        `json:"preparation_id"`
	Release                    types.KnowledgeWikiReleaseV1                  `json:"release"`
	CandidateEvidenceAuthority types.Schema67CandidateEvidenceAuthorityV1    `json:"candidate_evidence_authority"`
	ReviewBundle               types.SchemaWikiReviewBundleV1                `json:"review_bundle"`
	EvaluationBundle           types.Schema67GoldenEvaluationReviewBundleV1  `json:"evaluation_bundle"`
	ReviewSuccessor            types.Schema67GoldenReviewSuccessorMetadataV1 `json:"review_successor"`
}

type schemaWikiReviewDraftRequest struct {
	HumanDecision json.RawMessage `json:"human_decision"`
}

type schemaWikiScopeV1 struct {
	Version     string `json:"version"`
	SpaceID     string `json:"space_id"`
	RawKBID     string `json:"raw_kb_id"`
	WikiKBID    string `json:"wiki_kb_id"`
	ScopeSHA256 string `json:"scope_sha256"`
}

type schemaWikiCurrentEntityVersionV1 struct {
	Version         string                 `json:"version"`
	EntityID        string                 `json:"entity_id"`
	EntityVersionID string                 `json:"entity_version_id"`
	ActiveReleaseID string                 `json:"active_release_id"`
	ActivationEpoch uint64                 `json:"activation_epoch"`
	Root            types.SchemaRootPageV1 `json:"root"`
}

// ResolveScopeParams derives non-overridable Space/RAW scope from the sole
// active Head. It is used only by the unscoped Wiki bootstrap route.
func (h *SchemaWikiHandler) ResolveScopeParams() gin.HandlerFunc {
	return func(c *gin.Context) {
		if strings.TrimSpace(c.Param("space_id")) != "" ||
			strings.TrimSpace(c.Param("raw_kb_id")) != "" {
			writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		head, err := h.resolveHead(c)
		if err != nil {
			writeSchemaWikiError(c, err)
			c.Abort()
			return
		}
		c.Params = append(c.Params,
			gin.Param{Key: "space_id", Value: head.SpaceID},
			gin.Param{Key: "raw_kb_id", Value: head.RawKBID},
		)
		c.Set(schemaWikiResolvedHeadContextKey, *head)
		c.Next()
	}
}

// RequireScopeParams re-resolves the active Head and proves that a scoped URL
// carries exactly the server-owned Space/RAW identities. It never rewrites a
// caller path and therefore cannot turn an unrelated allow-listed RAW KB into
// Schema authority.
func (h *SchemaWikiHandler) RequireScopeParams() gin.HandlerFunc {
	return func(c *gin.Context) {
		head, err := h.resolveHead(c)
		if err != nil || strings.TrimSpace(c.Param("space_id")) != head.SpaceID ||
			strings.TrimSpace(c.Param("raw_kb_id")) != head.RawKBID {
			writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		c.Set(schemaWikiResolvedHeadContextKey, *head)
		c.Next()
	}
}

// BindCreateScopeParams allows the initial no-Head Draft while refusing a
// path that conflicts with an already active Head. Scope remains path-only;
// the closed request body has no scope fields.
func (h *SchemaWikiHandler) BindCreateScopeParams() gin.HandlerFunc {
	return func(c *gin.Context) {
		tenantID, wikiKBID, scope, ok := schemaWikiPathScope(c)
		if !ok || h == nil || h.scopeResolver == nil {
			writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		head, err := h.scopeResolver.GetHeadForWikiKB(c.Request.Context(), tenantID, wikiKBID)
		switch {
		case err == nil:
			if head == nil || head.WikiReleaseScope != scope {
				writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
				c.Abort()
				return
			}
		case stderrors.Is(err, apprepo.ErrWikiReleaseNotFound):
			// Initial Draft: no active Head is expected and the sealed path is
			// the only scope input.
		default:
			writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		c.Next()
	}
}

// RequirePreparationScopeParams resolves Draft/Ready scope from the immutable
// preparation identity before RAW authorization. It never depends on Head.
func (h *SchemaWikiHandler) RequirePreparationScopeParams() gin.HandlerFunc {
	return func(c *gin.Context) {
		tenantID, wikiKBID, pathScope, ok := schemaWikiPathScope(c)
		resolver, resolverOK := h.scopeResolver.(schemaWikiPreparationScopeResolver)
		preparationID := strings.TrimSpace(c.Param("preparation_id"))
		if !ok || !resolverOK || preparationID == "" {
			writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		storedScope, err := resolver.GetPreparationScopeForWikiKB(
			c.Request.Context(), tenantID, wikiKBID, preparationID,
		)
		if err != nil || storedScope == nil || *storedScope != pathScope {
			writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		c.Next()
	}
}

func schemaWikiPathScope(c *gin.Context) (uint64, string, types.WikiReleaseScope, bool) {
	if c == nil || c.Request == nil {
		return 0, "", types.WikiReleaseScope{}, false
	}
	tenantValue, exists := c.Get(types.TenantIDContextKey.String())
	tenantID, tenantOK := tenantValue.(uint64)
	wikiKBID := strings.TrimSpace(c.Param("kb_id"))
	scope := types.WikiReleaseScope{
		TenantID: tenantID, SpaceID: strings.TrimSpace(c.Param("space_id")),
		RawKBID: strings.TrimSpace(c.Param("raw_kb_id")), WikiKBID: wikiKBID,
	}
	ok := exists && tenantOK && tenantID != 0 && wikiKBID != "" &&
		scope.SpaceID != "" && scope.RawKBID != ""
	return tenantID, wikiKBID, scope, ok
}

func (h *SchemaWikiHandler) resolveHead(c *gin.Context) (*types.WikiReleaseHead, error) {
	if h == nil || h.scopeResolver == nil || c == nil || c.Request == nil {
		return nil, service.ErrWikiReleaseAccessDenied
	}
	tenantValue, exists := c.Get(types.TenantIDContextKey.String())
	tenantID, ok := tenantValue.(uint64)
	wikiKBID := strings.TrimSpace(c.Param("kb_id"))
	if !exists || !ok || tenantID == 0 || wikiKBID == "" {
		return nil, service.ErrWikiReleaseAccessDenied
	}
	head, err := h.scopeResolver.GetHeadForWikiKB(c.Request.Context(), tenantID, wikiKBID)
	if err != nil {
		if stderrors.Is(err, apprepo.ErrWikiReleaseNotFound) ||
			stderrors.Is(err, apprepo.ErrWikiReleaseConflict) {
			return nil, service.ErrWikiReleaseAccessDenied
		}
		return nil, service.ErrWikiReleaseAccessDenied
	}
	if head == nil || head.TenantID != tenantID || head.WikiKBID != wikiKBID ||
		strings.TrimSpace(head.SpaceID) == "" || strings.TrimSpace(head.RawKBID) == "" ||
		strings.TrimSpace(head.ActiveReleaseID) == "" || head.ActivationEpoch == 0 {
		return nil, service.ErrWikiReleaseAccessDenied
	}
	return head, nil
}

// Scope returns only the closed, server-derived active scope after both KB
// access checks and the existing release access seal have succeeded.
func (h *SchemaWikiHandler) Scope(c *gin.Context) {
	value, ok := c.Get(schemaWikiResolvedHeadContextKey)
	head, typeOK := value.(types.WikiReleaseHead)
	if !ok || !typeOK {
		writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
		return
	}
	scope, err := newSchemaWikiScopeV1(head.WikiReleaseScope)
	if err != nil {
		writeSchemaWikiError(c, service.ErrWikiReleaseAccessDenied)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": scope})
}

func newSchemaWikiScopeV1(scope types.WikiReleaseScope) (schemaWikiScopeV1, error) {
	preimage := struct {
		Version  string `json:"version"`
		SpaceID  string `json:"space_id"`
		RawKBID  string `json:"raw_kb_id"`
		WikiKBID string `json:"wiki_kb_id"`
	}{
		Version: "schema-wiki-scope.v1", SpaceID: scope.SpaceID,
		RawKBID: scope.RawKBID, WikiKBID: scope.WikiKBID,
	}
	if strings.TrimSpace(preimage.SpaceID) == "" || strings.TrimSpace(preimage.RawKBID) == "" ||
		strings.TrimSpace(preimage.WikiKBID) == "" {
		return schemaWikiScopeV1{}, service.ErrWikiReleaseAccessDenied
	}
	canonical, err := json.Marshal(preimage)
	if err != nil {
		return schemaWikiScopeV1{}, service.ErrWikiReleaseAccessDenied
	}
	return schemaWikiScopeV1{
		Version: preimage.Version, SpaceID: preimage.SpaceID, RawKBID: preimage.RawKBID,
		WikiKBID: preimage.WikiKBID, ScopeSHA256: fmt.Sprintf("%x", sha256.Sum256(canonical)),
	}, nil
}

// Domains is the bounded active Schema Wiki read surface. The service pins the
// active Head and replays the complete stored Schema custody before returning
// any member; generic Wiki payloads never reach this response.
func (h *SchemaWikiHandler) Domains(c *gin.Context) {
	authority, err := h.currentAuthority(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": []types.KnowledgeDomainV1{authority.Domain}})
}

func (h *SchemaWikiHandler) CurrentTaxonomy(c *gin.Context) {
	authority, err := h.currentAuthority(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": authority.Taxonomy})
}

func (h *SchemaWikiHandler) CurrentEntityVersion(c *gin.Context) {
	authority, err := h.currentAuthority(c)
	if err == nil && (authority.Entity.EntityID != strings.TrimSpace(c.Param("entity_id")) ||
		authority.EntityVersion.VersionID != strings.TrimSpace(c.Param("version_id"))) {
		err = service.ErrWikiReleaseNotFound
	}
	if err == nil && (authority.ReleaseID == "" || authority.ActivationEpoch == 0 ||
		authority.Root.EntityID != authority.Entity.EntityID ||
		authority.Root.EntityVersionID != authority.EntityVersion.VersionID) {
		err = service.ErrWikiReleaseConflict
	}
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": schemaWikiCurrentEntityVersionV1{
		Version:         "schema-wiki-current-entity-version.v1",
		EntityID:        authority.Entity.EntityID,
		EntityVersionID: authority.EntityVersion.VersionID,
		ActiveReleaseID: authority.ReleaseID,
		ActivationEpoch: authority.ActivationEpoch,
		Root:            authority.Root,
	}})
}

func (h *SchemaWikiHandler) ReadActiveRoot(c *gin.Context) {
	authority, err := h.currentAuthority(c)
	if err == nil && authority.ReleaseID != strings.TrimSpace(c.Param("release_id")) {
		err = service.ErrWikiReleaseConflict
	}
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": authority.Root})
}

func (h *SchemaWikiHandler) currentAuthority(c *gin.Context) (*service.SchemaWikiCurrentAuthorityV1, error) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		return nil, err
	}
	if h == nil || h.schemaService == nil {
		return nil, service.ErrNoSchemaWikiActiveRelease
	}
	authority, err := h.schemaService.ReadCurrentSchemaAuthority(c.Request.Context(), principal, scope)
	if err != nil {
		return nil, err
	}
	value, exists := c.Get(schemaWikiResolvedHeadContextKey)
	resolved, valid := value.(types.WikiReleaseHead)
	if !exists || !valid || authority == nil || resolved.WikiReleaseScope != scope ||
		resolved.ActiveReleaseID != authority.ReleaseID ||
		resolved.ActivationEpoch != authority.ActivationEpoch {
		return nil, service.ErrWikiReleaseConflict
	}
	return authority, nil
}

// CreateDraft accepts only the concrete release and review bundle. The
// service replays their closed custody and persists the immutable Draft.
func (h *SchemaWikiHandler) CreateDraft(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	var request schemaWikiCreateDraftRequest
	if err := decodeClosedSchemaWikiRequest(c, &request); err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	draft, err := h.schemaService.CreateSchemaDraft(
		c.Request.Context(), principal, scope, strings.TrimSpace(request.PreparationID),
		request.Release, request.CandidateEvidenceAuthority, request.ReviewBundle,
		request.EvaluationBundle,
		request.ReviewSuccessor,
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": draft})
}

// ReviewDraft passes one closed named-human receipt to the existing concrete
// review authority; no caller-selected verifier or approval hash is accepted.
func (h *SchemaWikiHandler) ReviewDraft(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	var request schemaWikiReviewDraftRequest
	if err := decodeClosedSchemaWikiRequest(c, &request); err != nil || len(request.HumanDecision) == 0 {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	ready, err := h.schemaService.ReviewSchemaDraft(
		c.Request.Context(), principal, scope,
		strings.TrimSpace(c.Param("preparation_id")), request.HumanDecision,
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": ready})
}

// ReadDraftField is the human-only exact Draft preview. The caller supplies
// only the preparation, field and immutable member revision identities.
func (h *SchemaWikiHandler) ReadDraftField(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	member, err := h.schemaService.ReadSchemaDraftMember(
		c.Request.Context(), principal, scope,
		strings.TrimSpace(c.Param("preparation_id")),
		schemaWikiFieldSlug(c.Param("field_id")),
		strings.TrimSpace(c.Query("member_revision_id")),
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": member})
}

// ReadActiveField pins current Head inside the service and refuses release-id
// substitution before returning a canonical field payload.
func (h *SchemaWikiHandler) ReadActiveField(c *gin.Context) {
	h.readActiveMember(c, schemaWikiFieldSlug(c.Param("field_id")))
}

func (h *SchemaWikiHandler) ReadActiveSection(c *gin.Context) {
	h.readActiveMember(c, schemaWikiSectionSlug(c.Param("section_id")))
}

func (h *SchemaWikiHandler) readActiveMember(c *gin.Context, logicalSlug string) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrNoSchemaWikiActiveRelease)
		return
	}
	read, err := h.schemaService.ReadCurrentSchemaMember(
		c.Request.Context(), principal, scope, logicalSlug,
	)
	if err == nil && read.ReleaseID != strings.TrimSpace(c.Param("release_id")) {
		err = service.ErrWikiReleaseConflict
	}
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": read.Payload})
}

// SearchActive pins and searches one Active release; the URL release must be
// identical to every server-derived result.
func (h *SchemaWikiHandler) SearchActive(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrNoSchemaWikiActiveRelease)
		return
	}
	reads, err := h.schemaService.SearchCurrentSchemaMembers(
		c.Request.Context(), principal, scope, c.Query("q"),
	)
	expectedReleaseID := strings.TrimSpace(c.Param("release_id"))
	if err == nil {
		for _, read := range reads {
			if read.ReleaseID != expectedReleaseID {
				err = service.ErrWikiReleaseConflict
				break
			}
		}
	}
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": reads})
}

// ReadReviewedField returns only a full-custody Ready preparation field.
func (h *SchemaWikiHandler) ReadReviewedField(c *gin.Context) {
	h.readPreparationMember(c, schemaWikiFieldSlug(c.Param("field_id")))
}

func (h *SchemaWikiHandler) ReadReviewedSection(c *gin.Context) {
	h.readPreparationMember(c, schemaWikiSectionSlug(c.Param("section_id")))
}

func (h *SchemaWikiHandler) readPreparationMember(c *gin.Context, logicalSlug string) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	read, err := h.schemaService.ReadSchemaPreparationMember(
		c.Request.Context(), principal, scope,
		strings.TrimSpace(c.Param("preparation_id")), logicalSlug,
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": read.Payload})
}

func (h *SchemaWikiHandler) ReadReviewedRoot(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	read, err := h.schemaService.ReadSchemaPreparationMember(
		c.Request.Context(), principal, scope, strings.TrimSpace(c.Param("preparation_id")), "",
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": read.Payload})
}

func (h *SchemaWikiHandler) ReadPreparationGoldenQualitySummary(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	summary, err := h.schemaService.ReadSchemaPreparationGoldenQualitySummary(
		c.Request.Context(),
		principal,
		scope,
		strings.TrimSpace(c.Param("preparation_id")),
		strings.TrimSpace(c.Param("evaluation_id")),
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": summary})
}

func (h *SchemaWikiHandler) ReadPreparationGoldenQualityDossier(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiPreparationInvalid)
		return
	}
	dossier, err := h.schemaService.ReadSchemaPreparationGoldenQualityDossier(
		c.Request.Context(),
		principal,
		scope,
		strings.TrimSpace(c.Param("preparation_id")),
		strings.TrimSpace(c.Param("evaluation_id")),
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": dossier})
}

// ReadGoldenSuccessorStatus exposes only the deployment-frozen, non-serving
// source-review/mapping/admission status. It accepts no caller payload.
func (h *SchemaWikiHandler) ReadGoldenSuccessorStatus(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrNoGoldenSuccessorStatus)
		return
	}
	status, err := h.schemaService.ReadSchemaWikiGoldenSuccessorStatus(
		c.Request.Context(), principal, scope,
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": status})
}

func (h *SchemaWikiHandler) PreviewPreparationGoldenEvidence(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiCitationUnavailable)
		return
	}
	authority, err := h.schemaService.IssueSchemaPreparationGoldenEvidencePreview(
		c.Request.Context(),
		principal,
		scope,
		strings.TrimSpace(c.Param("preparation_id")),
		strings.TrimSpace(c.Param("evaluation_id")),
		strings.TrimSpace(c.Param("field_id")),
		strings.TrimSpace(c.Param("evidence_id")),
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": authority})
}

// PreviewCurrentCitation selects CitationTarget and binding from the pinned
// release inside the service. Only field/citation IDs cross the HTTP boundary.
func (h *SchemaWikiHandler) PreviewCurrentCitation(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiCitationUnavailable)
		return
	}
	authority, err := h.schemaService.IssueCurrentSchemaCitationAuthority(
		c.Request.Context(), principal, scope,
		strings.TrimSpace(c.Param("release_id")),
		schemaWikiFieldSlug(c.Param("field_id")), strings.TrimSpace(c.Param("citation_id")),
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": authority})
}

// ReadCitationContent accepts the opaque token as the sole citation/revision
// authority. The scoped URL remains only the independently sealed dual-ACL
// context and cannot select page, attempt, revision, bbox or hashes.
func (h *SchemaWikiHandler) ReadCitationContent(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiCitationUnavailable)
		return
	}
	opened, err := h.schemaService.ReadSchemaCitationContent(
		c.Request.Context(), principal, scope, strings.TrimSpace(c.Param("token")),
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.Data(http.StatusOK, "application/pdf", opened)
}

// PreviewReviewedCitation is the human-only Ready-preparation counterpart.
func (h *SchemaWikiHandler) PreviewReviewedCitation(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.schemaService == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiCitationUnavailable)
		return
	}
	opened, err := h.schemaService.ReadReviewedPreparationCitation(
		c.Request.Context(), principal, scope,
		strings.TrimSpace(c.Param("preparation_id")),
		schemaWikiFieldSlug(c.Param("field_id")), strings.TrimSpace(c.Param("citation_id")),
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.Data(http.StatusOK, "application/octet-stream", opened)
}

func schemaWikiFieldSlug(fieldID string) string {
	fieldID = strings.TrimSpace(fieldID)
	if fieldID == "" {
		return ""
	}
	return "field:" + fieldID
}

func schemaWikiSectionSlug(sectionID string) string {
	sectionID = strings.TrimSpace(sectionID)
	if sectionID == "" {
		return ""
	}
	return "section:" + sectionID
}

func decodeClosedSchemaWikiRequest(c *gin.Context, destination any) error {
	if c == nil || c.Request == nil || c.Request.Body == nil {
		return service.ErrSchemaWikiPreparationInvalid
	}
	decoder := json.NewDecoder(io.LimitReader(c.Request.Body, maxSchemaWikiRequestBytes+1))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return service.ErrSchemaWikiPreparationInvalid
	}
	if err := ensureWikiReleaseJSONEOF(decoder); err != nil {
		return service.ErrSchemaWikiPreparationInvalid
	}
	canonical, err := json.Marshal(destination)
	if err != nil || len(canonical) == 0 || bytes.Equal(bytes.TrimSpace(canonical), []byte("null")) {
		return service.ErrSchemaWikiPreparationInvalid
	}
	return nil
}

func writeSchemaWikiError(c *gin.Context, err error) {
	switch {
	case stderrors.Is(err, service.ErrSchemaWikiPreparationInvalid):
		c.JSON(http.StatusBadRequest, gin.H{
			"success": false, "error": gin.H{"message": "schema wiki preparation invalid"},
		})
	case stderrors.Is(err, service.ErrSchemaWikiCitationUnavailable):
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"success": false, "error": gin.H{"message": "schema wiki citation unavailable"},
		})
	case stderrors.Is(err, service.ErrSchemaWikiCitationPageUnavailable):
		c.JSON(http.StatusUnprocessableEntity, gin.H{
			"success": false,
			"error": gin.H{
				"code": "PAGE_UNAVAILABLE", "message": "schema wiki citation page unavailable",
			},
		})
	case stderrors.Is(err, service.ErrNoSchemaWikiActiveRelease):
		c.JSON(http.StatusNotFound, gin.H{
			"success": false, "error": gin.H{"message": "no schema wiki active release"},
		})
	case stderrors.Is(err, service.ErrNoGoldenSuccessorStatus):
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"success": false,
			"error": gin.H{
				"code": "NO_GOLDEN_SUCCESSOR_STATUS", "message": "golden successor status unavailable",
			},
		})
	default:
		writeWikiReleaseError(c, err)
	}
}
