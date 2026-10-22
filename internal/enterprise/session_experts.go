package enterprise

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// MountSessionExpertEdits exposes the browser expert edit (S9a Spec §2.5). The caller supplies
// the tenant Admin and Wiki KB editor guards; the handler checks the tenant role again so the
// write stays closed when route RBAC only logs.
func MountSessionExpertEdits(r gin.IRouter, deps SessionDeps, guards ...gin.HandlerFunc) {
	view := sessionSpaceRoutes(r.Group("", checkSessionRead), deps.Spaces, guards...)
	view.POST("/expert-edits", func(c *gin.Context) { expertEdit(c, deps.Experts) })
}

func expertEdit(c *gin.Context, service *expert.Service) {
	p, ok := sessionReadPrincipal(c)
	if !ok {
		writeError(c, &release.Error{Code: release.ErrorReleaseAccessDenied, Detail: "a browser session is required"})
		return
	}
	role := types.CallerFromContext(c.Request.Context()).Role
	if !role.HasPermission(types.TenantRoleAdmin) {
		writeError(c, &release.Error{Code: release.ErrorReleaseAccessDenied, Detail: "expert edits need an administrator"})
		return
	}
	if service == nil {
		candidateUnavailable(c)
		return
	}
	var in expert.EditInput
	err := decodeSpotCheckBody(c, &in, maxControlBody, expert.ErrorInvalid,
		"base_release_id", "member_slug", "base_member_digest", "state", "value", "reason")
	if err != nil {
		writeError(c, err)
		return
	}
	result, err := service.Edit(c.Request.Context(), p, string(role), c.Param("space_id"), in)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": gin.H{
		"release_id": result.Release.ID, "epoch": result.Release.Epoch,
		"revision_record_id": result.Revision.ID,
	}})
}

// expertCitation answers a citation of an expert revision with the record itself; no file is
// opened (S9a Spec §2.4).
func expertCitation(c *gin.Context, experts *expert.Service, p release.Principal, at release.EvidenceAt) {
	record, err := experts.Citation(c.Request.Context(), p, c.Param("space_id"), at.Evidence)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{
		"release_id": at.ReleaseID, "member": at.Slug, "evidence_index": at.Index, "origin": at.Origin,
		"kind": "expert_revision", "quote": at.Evidence.Quote, "revision_record_id": record.ID,
		"actor": record.Actor, "role": record.Role, "recorded_at": record.RecordedAt,
		"before": record.Before, "after": record.After, "reason": record.Reason,
	}})
}
