package enterprise

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// MountSessionReviews exposes unpublished candidates only to browser administrators.
// The caller supplies Admin and Wiki editor guards, as for confirmation answers.
func MountSessionReviews(r gin.IRouter, deps SessionDeps, guards ...gin.HandlerFunc) {
	// Preserve the enterprise typed denial even when upstream RBAC enforces before
	// the handler. Keep the handler check too; RBAC may be configured to only log.
	checks := append([]gin.HandlerFunc{checkReviewAdmin}, guards...)
	view := sessionSpaceRoutes(r.Group("", checkSessionRead), deps.Spaces, checks...)
	view.Use(checkReviewAdmin)
	view.Use(func(c *gin.Context) {
		if deps.Candidates == nil {
			candidateUnavailable(c)
			return
		}
		c.Next()
	})
	view.GET("/candidates", func(c *gin.Context) { reviewQueue(c, deps.Candidates) })
	view.GET("/candidates/:candidate_id", func(c *gin.Context) { reviewCandidate(c, deps.Candidates) })
	view.POST("/candidates/:candidate_id/points/decisions", func(c *gin.Context) {
		reviewPointDecision(c, deps.Candidates)
	})
	view.POST("/candidates/:candidate_id/decisions", func(c *gin.Context) { reviewDecision(c, deps.Candidates) })
}

func checkReviewAdmin(c *gin.Context) {
	v, _ := c.Get(sessionReadIdentityKey)
	identity, ok := v.(sessionReadIdentity)
	caller := identity.caller
	web := types.Principal{Type: types.PrincipalWebUser, ID: caller.UserID}
	if !ok || caller.TenantID != identity.principal.TenantID || web.StorageID() != identity.principal.Subject ||
		!caller.Role.HasPermission(types.TenantRoleAdmin) {
		writeError(c, &release.Error{
			Code: release.ErrorReleaseAccessDenied, Detail: "candidate review needs an administrator",
		})
		return
	}
	c.Next()
}

func reviewQueue(c *gin.Context, service *release.Service) {
	p, _ := sessionReadPrincipal(c)
	status := "pending"
	if values, exists := c.Request.URL.Query()["status"]; exists {
		if len(values) != 1 || values[0] == "" {
			writeError(c, &release.Error{Code: release.ErrorDecisionInvalid, Detail: "one queue status is required"})
			return
		}
		status = values[0]
	}
	items, err := service.ReviewQueue(c.Request.Context(), p, c.Param("space_id"), status)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"items": items}})
}

func reviewCandidate(c *gin.Context, service *release.Service) {
	p, _ := sessionReadPrincipal(c)
	item, err := service.ReviewCandidate(c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"))
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": item})
}

func reviewDecision(c *gin.Context, service *release.Service) {
	var input struct {
		Outcome string `json:"outcome"`
		Reason  string `json:"reason"`
	}
	err := decodeSpotCheckBody(c, &input, maxControlBody, release.ErrorDecisionInvalid, "outcome", "reason")
	if err != nil {
		writeError(c, err)
		return
	}
	p, _ := sessionReadPrincipal(c)
	result, err := service.Review(c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"),
		input.Outcome, input.Reason)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": result})
}

func reviewPointDecision(c *gin.Context, service *release.Service) {
	var input struct {
		Slugs   []string `json:"slugs"`
		Outcome string   `json:"outcome"`
		Reason  string   `json:"reason"`
	}
	err := decodeSpotCheckBody(c, &input, maxControlBody, release.ErrorDecisionInvalid, "slugs", "outcome", "reason")
	if err != nil {
		writeError(c, err)
		return
	}
	p, _ := sessionReadPrincipal(c)
	result, err := service.ReviewPoints(c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"),
		input.Slugs, input.Outcome, input.Reason)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": result})
}
