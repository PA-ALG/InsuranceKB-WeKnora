// Package enterprise mounts the project's generic platform endpoints.
package enterprise

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

// Deps contains the explicitly supplied service and shared API authorization.
type Deps struct {
	Candidates *release.Service
	Sources    *source.Service
	SpotChecks *spotcheck.Service
	// Confirmations records items a person decides; nil answers 503 (S5b-3a).
	Confirmations *confirm.Service
	// Authorizer is the SAME registry attached to the authenticated API group.
	Authorizer *middleware.APIKeyRouteAuthorizer
	// Files opens cited original files; nil leaves the file route unavailable.
	Files SourceFiles
}

// Mount registers relative platform routes on a group carrying :space_id.
// The parent must run middleware.Auth; this package only consumes its trusted
// identity and reuses its API-key authorizer, never authenticates raw headers.
func Mount(r gin.IRouter, deps Deps) {
	group := r.Group("")
	group.Use(func(c *gin.Context) {
		if _, err := requestPrincipal(c); err != nil {
			writeError(c, err)
			return
		}
		if deps.Authorizer == nil {
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
				"success": false, "code": "SERVICE_UNAVAILABLE", "error": "enterprise service is unavailable",
			})
			return
		}
		c.Next()
	})
	if deps.Authorizer != nil {
		// A Space is not a KB. Until a platform adapter can check all source KBs,
		// only unrestricted full-access service keys can use these endpoints.
		policy := middleware.APIKeyRoutePolicy{RequireFullAccess: true}
		prefix := strings.TrimSuffix(group.BasePath(), "/")
		deps.Authorizer.Register(http.MethodPost, prefix+"/candidates", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/candidates", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/candidates/:candidate_id", policy)
		deps.Authorizer.Register(http.MethodPost, prefix+"/candidates/:candidate_id/points/decisions", policy)
		deps.Authorizer.Register(http.MethodPost, prefix+"/confirmations", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/confirmations", policy)
		deps.Authorizer.Register(http.MethodPost, prefix+"/confirmations/:confirmation_id/closure", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/candidates/:candidate_id/preview", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/sources/:knowledge_id/attempts/:attempt/pages", policy)
		deps.Authorizer.Register(http.MethodPost, prefix+"/candidates/:candidate_id/decisions", policy)
		deps.Authorizer.Register(http.MethodPost, prefix+"/candidates/:candidate_id/activations", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/releases/active", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/releases/:release_id", policy)
		deps.Authorizer.Register(http.MethodPost, prefix+"/releases/:release_id/samples", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/samples", policy)
		deps.Authorizer.Register(http.MethodPost, prefix+"/releases/:release_id/retirement", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/sources/:knowledge_id/pins", policy)
		deps.Authorizer.Register(http.MethodGet, prefix+"/releases/:release_id/citation", policy)
		deps.Authorizer.Register(
			http.MethodGet, prefix+"/releases/:release_id/sources/:knowledge_id/attempts/:attempt/file", policy,
		)
		group.Use(deps.Authorizer.Middleware())
	}
	group.POST("/candidates", func(c *gin.Context) { receive(c, deps.Candidates) })
	group.GET("/candidates", func(c *gin.Context) { machineReviewQueue(c, deps.Candidates) })
	group.GET("/candidates/:candidate_id", func(c *gin.Context) { machineReviewDetail(c, deps.Candidates) })
	group.POST("/candidates/:candidate_id/points/decisions", func(c *gin.Context) {
		machinePointRejection(c, deps.Candidates)
	})
	group.POST("/confirmations", func(c *gin.Context) { submitConfirmations(c, deps.Confirmations) })
	group.GET("/confirmations", func(c *gin.Context) { listConfirmations(c, deps.Confirmations, false) })
	group.POST("/confirmations/:confirmation_id/closure", func(c *gin.Context) {
		closeConfirmation(c, deps.Confirmations)
	})
	group.GET("/candidates/:candidate_id/preview", func(c *gin.Context) { preview(c, deps.Candidates) })
	group.POST("/candidates/:candidate_id/decisions", func(c *gin.Context) { decide(c, deps.Candidates) })
	group.POST("/candidates/:candidate_id/activations", func(c *gin.Context) { activate(c, deps.Candidates) })
	group.GET("/releases/active", func(c *gin.Context) { readRelease(c, deps.Candidates, "") })
	group.GET("/releases/:release_id", func(c *gin.Context) { readRelease(c, deps.Candidates, c.Param("release_id")) })
	group.POST("/releases/:release_id/samples", func(c *gin.Context) { submitSamples(c, deps.SpotChecks) })
	group.GET("/samples", func(c *gin.Context) { listSamples(c, deps.SpotChecks, false) })
	group.GET("/sources/:knowledge_id/attempts/:attempt/pages", func(c *gin.Context) { pages(c, deps.Sources) })
	group.POST("/releases/:release_id/retirement", func(c *gin.Context) { retire(c, deps.Candidates) })
	group.GET("/sources/:knowledge_id/pins", func(c *gin.Context) { sourcePins(c, deps.Candidates) })
	spacesPath := strings.TrimSuffix(group.BasePath(), "/")
	group.GET("/releases/:release_id/citation", func(c *gin.Context) {
		citation(c, deps.Candidates, deps.Sources, nil, spacesPath)
	})
	group.GET("/releases/:release_id/sources/:knowledge_id/attempts/:attempt/file", func(c *gin.Context) {
		citedFile(c, deps.Candidates, deps.Files)
	})
}

func requestPrincipal(c *gin.Context) (release.Principal, error) {
	ctx := c.Request.Context()
	tenantID, tenantOK := types.TenantIDFromContext(ctx)
	principal, principalOK := types.PrincipalFromContext(ctx)
	keyScope, keyOK := types.TenantAPIKeyScopeFromContext(ctx)
	ginTenant, _ := c.Get(types.TenantIDContextKey.String())
	ginPrincipal, _ := c.Get(types.PrincipalContextKey.String())
	if !tenantOK || tenantID == 0 || !principalOK || !keyOK || keyScope.KeyID == 0 ||
		ginTenant != tenantID || ginPrincipal != principal || keyScope.IsKnowledgeBaseRestricted() ||
		strings.TrimSpace(c.Param("space_id")) == "" {
		return release.Principal{}, &release.Error{
			Code:   release.ErrorReleaseAccessDenied,
			Detail: "an authenticated service with access to this scope is required",
		}
	}
	return release.Principal{TenantID: tenantID, Subject: principal.StorageID()}, nil
}

func receive(c *gin.Context, service *release.Service) {
	if service == nil {
		candidateUnavailable(c)
		return
	}
	p, err := requestPrincipal(c)
	if err != nil {
		writeError(c, err)
		return
	}
	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, release.MaxBundleBytes+1))
	if err != nil || len(raw) > release.MaxBundleBytes {
		writeError(c, &release.Error{
			Code: release.ErrorCandidateInvalid, Detail: "bundle body is unreadable or too large",
		})
		return
	}
	candidate, err := service.Receive(c.Request.Context(), p, c.Param("space_id"), raw)
	if err != nil {
		writeError(c, err)
		return
	}
	status := http.StatusCreated
	if candidate.Status == "existing" {
		status = http.StatusOK
	}
	c.JSON(status, gin.H{"success": true, "data": candidate})
}

func preview(c *gin.Context, service *release.Service) {
	if service == nil {
		candidateUnavailable(c)
		return
	}
	p, err := requestPrincipal(c)
	if err != nil {
		writeError(c, err)
		return
	}
	result, err := service.Preview(c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"))
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}

// maxControlBody bounds decision and activation requests, which carry a few short fields.
const maxControlBody = 64 << 10

func decide(c *gin.Context, service *release.Service) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	var in release.DecisionInput
	if err := decodeControlBody(c, &in); err != nil {
		writeError(c, err)
		return
	}
	decision, err := service.Decide(c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"), in)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": decision})
}

func activate(c *gin.Context, service *release.Service) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	var in struct {
		DecisionID string `json:"decision_id"`
	}
	if err := decodeControlBody(c, &in); err != nil {
		writeError(c, err)
		return
	}
	if strings.TrimSpace(in.DecisionID) == "" {
		writeError(c, &release.Error{Code: release.ErrorDecisionInvalid, Detail: "decision_id is required"})
		return
	}
	result, err := service.Activate(
		c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"), in.DecisionID,
	)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}

func publishingRequest(c *gin.Context, service *release.Service) (release.Principal, bool) {
	if service == nil {
		candidateUnavailable(c)
		return release.Principal{}, false
	}
	if p, ok := sessionReadPrincipal(c); ok {
		return p, true
	}
	p, err := requestPrincipal(c)
	if err != nil {
		writeError(c, err)
		return release.Principal{}, false
	}
	return p, true
}

// decodeControlBody reads one strict JSON object: bounded, no unknown fields, nothing after it.
func decodeControlBody(c *gin.Context, into any) error {
	invalid := &release.Error{Code: release.ErrorDecisionInvalid, Detail: "request body is not a valid JSON object"}
	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, maxControlBody+1))
	if err != nil || len(raw) > maxControlBody {
		return invalid
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(into) != nil || decoder.Decode(&struct{}{}) != io.EOF {
		return invalid
	}
	return nil
}

func candidateUnavailable(c *gin.Context) {
	c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
		"success": false, "code": "SERVICE_UNAVAILABLE", "error": "candidate service is unavailable",
	})
}

func pages(c *gin.Context, service *source.Service) {
	p, err := requestPrincipal(c)
	if err != nil {
		writeError(c, err)
		return
	}
	attempt, err := strconv.ParseInt(c.Param("attempt"), 10, 64)
	if err != nil {
		writeSourceError(c, &source.Error{Code: source.ErrorInvalidRequest, Detail: "a positive attempt is required"})
		return
	}
	result, err := service.Pages(
		c.Request.Context(), source.Scope{TenantID: p.TenantID, SpaceID: c.Param("space_id")},
		c.Param("knowledge_id"), attempt,
	)
	if err != nil {
		writeSourceError(c, err)
		return
	}
	c.JSON(http.StatusOK, result)
}

func writeSourceError(c *gin.Context, err error) {
	var failure *source.Error
	if !errors.As(err, &failure) {
		failure = &source.Error{Code: source.ErrorUnavailable, Detail: "source artifact is unavailable"}
	}
	status := http.StatusServiceUnavailable
	switch failure.Code {
	case source.ErrorInvalidRequest:
		status = http.StatusBadRequest
	case source.ErrorSourceNotFound:
		status = http.StatusNotFound
	case source.ErrorNotCaptured, source.ErrorSpanOutOfRange:
		status = http.StatusConflict
	case source.ErrorIntegrity:
		status = http.StatusInternalServerError
	}
	body := gin.H{"success": false, "code": failure.Code, "error": failure.Detail}
	if failure.Code == source.ErrorNotCaptured && failure.Reason != "" {
		body["reason"] = failure.Reason
		if failure.Reason == source.NotCapturedScannedPage && failure.Page > 0 {
			body["page_number"] = failure.Page
		}
	}
	c.AbortWithStatusJSON(status, body)
}

func writeError(c *gin.Context, err error) {
	var failure *release.Error
	if errors.As(err, &failure) {
		status := http.StatusBadRequest
		switch failure.Code {
		case release.ErrorCandidateNotFound, release.ErrorDecisionNotFound, release.ErrorReleaseNotFound,
			release.ErrorMemberNotFound, release.ErrorEvidenceNotFound, spotcheck.ErrorSampleNotFound,
			confirm.ErrorConfirmationNotFound:
			status = http.StatusNotFound
		case release.ErrorEvidenceMismatch:
			status = http.StatusConflict
		case release.ErrorEvidenceUnsupported, release.ErrorEvidenceUnverifiable:
			status = http.StatusUnprocessableEntity
		case release.ErrorReleaseAccessDenied:
			status = http.StatusForbidden
		case release.ErrorCandidateNotApproved, release.ErrorNeedsRebase, release.ErrorReleaseConflict,
			release.ErrorCandidateDecided, release.ErrorMemberDecided, release.ErrorMachineDecisionOnly:
			status = http.StatusConflict
		case release.ErrorServiceUnavailable:
			status = http.StatusServiceUnavailable
		case release.ErrorReleaseActive, release.ErrorSourceUnavailable:
			status = http.StatusConflict
		case release.ErrorRetirementInvalid, release.ErrorInvalidRequest,
			spotcheck.ErrorSampleInvalid, spotcheck.ErrorVerdictInvalid, expert.ErrorInvalid,
			confirm.ErrorConfirmationInvalid, confirm.ErrorAnswerInvalid:
			status = http.StatusBadRequest
		case expert.ErrorStale, confirm.ErrorConfirmationClosed, confirm.ErrorAnswerStale:
			status = http.StatusConflict
		}
		c.AbortWithStatusJSON(status, gin.H{"success": false, "code": failure.Code, "error": failure.Detail})
		return
	}
	// Storage and resolver diagnostics must not disclose backend details.
	c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
		"success": false, "code": "INTERNAL_ERROR", "error": "candidate operation failed",
	})
}

func retire(c *gin.Context, service *release.Service) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	var in struct {
		Reason string `json:"reason"`
	}
	if err := decodeControlBody(c, &in); err != nil {
		writeError(c, &release.Error{Code: release.ErrorRetirementInvalid, Detail: "invalid retirement request"})
		return
	}
	result, err := service.Retire(c.Request.Context(), p, c.Param("space_id"), c.Param("release_id"), in.Reason)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}

func sourcePins(c *gin.Context, service *release.Service) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	pins, err := service.SourcePins(c.Request.Context(), p, c.Param("space_id"), c.Param("knowledge_id"))
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"pins": pins}})
}
