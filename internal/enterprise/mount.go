// Package enterprise mounts the project's generic platform endpoints.
package enterprise

import (
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

// Deps contains the explicitly supplied service and shared API authorization.
type Deps struct {
	Candidates *release.Service
	// Authorizer is the SAME registry attached to the authenticated API group.
	Authorizer *middleware.APIKeyRouteAuthorizer
}

// Mount registers relative candidate routes on a group carrying :space_id.
// The parent must run middleware.Auth; this package only consumes its trusted
// identity and reuses its API-key authorizer, never authenticates raw headers.
func Mount(r gin.IRouter, deps Deps) {
	group := r.Group("")
	group.Use(func(c *gin.Context) {
		if _, err := requestPrincipal(c); err != nil {
			writeError(c, err)
			return
		}
		if deps.Authorizer == nil || deps.Candidates == nil {
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
				"success": false, "code": "SERVICE_UNAVAILABLE", "error": "candidate service is unavailable",
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
		deps.Authorizer.Register(http.MethodGet, prefix+"/candidates/:candidate_id/preview", policy)
		group.Use(deps.Authorizer.Middleware())
	}
	group.POST("/candidates", func(c *gin.Context) { receive(c, deps.Candidates) })
	group.GET("/candidates/:candidate_id/preview", func(c *gin.Context) { preview(c, deps.Candidates) })
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

func writeError(c *gin.Context, err error) {
	var failure *release.Error
	if errors.As(err, &failure) {
		status := http.StatusBadRequest
		switch failure.Code {
		case release.ErrorCandidateNotFound:
			status = http.StatusNotFound
		case release.ErrorReleaseAccessDenied:
			status = http.StatusForbidden
		}
		c.AbortWithStatusJSON(status, gin.H{"success": false, "code": failure.Code, "error": failure.Detail})
		return
	}
	// Storage and resolver diagnostics must not disclose backend details.
	c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
		"success": false, "code": "INTERNAL_ERROR", "error": "candidate operation failed",
	})
}
