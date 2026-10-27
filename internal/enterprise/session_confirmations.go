package enterprise

import (
	"bytes"
	"net/http"
	"net/url"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

// MountSessionConfirmations exposes browser answers and original files. The caller supplies the role guard
// (an answer changes what is compiled and published, so the router requires an admin).
func MountSessionConfirmations(r gin.IRouter, deps SessionDeps, guards ...gin.HandlerFunc) {
	view := sessionConfirmationRoutes(r.Group("", checkSessionRead), deps, guards...)
	view.POST("/confirmations/:confirmation_id/answers", func(c *gin.Context) {
		answerConfirmation(c, deps.Confirmations)
	})
	view.GET("/confirmations/:confirmation_id/file", func(c *gin.Context) {
		confirmationFile(c, deps)
	})
}

func confirmationFile(c *gin.Context, deps SessionDeps) {
	p, ok := confirmationPrincipal(c, deps.Confirmations, true)
	if !ok {
		return
	}
	// The route guard may only log when RBAC is disabled. Recheck the trusted role before
	// reading an item, including on conditional requests that could reuse cached content.
	if !types.CallerFromContext(c.Request.Context()).Role.HasPermission(types.TenantRoleAdmin) {
		writeError(c, &release.Error{
			Code: release.ErrorReleaseAccessDenied, Detail: "confirmation files need an administrator",
		})
		return
	}
	space := c.Param("space_id")
	item, err := deps.Confirmations.Item(c.Request.Context(), p, space, c.Param("confirmation_id"))
	if err != nil {
		writeError(c, err)
		return
	}
	ref, valid := release.ParseSourceRef(item.SourceRef)
	if !valid {
		writeSourceError(c, &source.Error{Code: source.ErrorSourceNotFound, Detail: "source file was not found"})
		return
	}
	etag := `"` + ref.FileSHA256 + `"`
	raw, name, ok := readSourceFile(c, deps.Files,
		source.Scope{TenantID: p.TenantID, SpaceID: space}, ref.KnowledgeID, ref.FileSHA256,
		c.GetHeader("If-None-Match") == etag)
	if !ok {
		return
	}
	contentType, disposition := "application/octet-stream", "attachment"
	if bytes.HasPrefix(raw, []byte("%PDF-")) {
		contentType, disposition = "application/pdf", "inline"
	}
	c.Header("ETag", etag)
	c.Header("Cache-Control", "private, no-cache")
	c.Header("Content-Disposition", disposition+"; filename*=UTF-8''"+url.PathEscape(name))
	c.Data(http.StatusOK, contentType, raw)
}

func sessionConfirmationRoutes(group *gin.RouterGroup, deps SessionDeps, guards ...gin.HandlerFunc) *gin.RouterGroup {
	configured := group.Group("", func(c *gin.Context) {
		if _, ok := confirmationPrincipal(c, deps.Confirmations, true); ok {
			c.Next()
		}
	})
	return sessionSpaceRoutes(configured, deps.Spaces, guards...)
}
