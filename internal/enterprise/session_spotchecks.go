package enterprise

import (
	"context"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// MountSessionSpotChecks exposes only browser verdict writes. The caller supplies
// the Wiki KB editor guard; service-side visibility still pins each sample's Release.
func MountSessionSpotChecks(r gin.IRouter, deps SessionDeps, guards ...gin.HandlerFunc) {
	view := sessionSpotCheckRoutes(r.Group("", checkSessionRead), deps, guards...)
	service := deps.SpotChecks.SpaceReadView()
	view.POST("/samples/:sample_id/verdicts", func(c *gin.Context) { decideSample(c, service) })
}

func sessionSpotCheckRoutes(group *gin.RouterGroup, deps SessionDeps, guards ...gin.HandlerFunc) *gin.RouterGroup {
	configured := group.Group("", func(c *gin.Context) {
		if _, ok := spotCheckPrincipal(c, deps.SpotChecks, true); ok {
			c.Next()
		}
	})
	return sessionSpaceRoutes(configured, deps.Spaces, guards...)
}

// Both view surfaces use the same identity/Space ordering. Guards may change the
// execution tenant for a shared KB; keep their grants and restore the original caller.
func sessionSpaceRoutes(group *gin.RouterGroup, spaces SpaceDirectory, guards ...gin.HandlerFunc) *gin.RouterGroup {
	view := group.Group("/spaces/:space_id/view", func(c *gin.Context) {
		if spaces == nil {
			candidateUnavailable(c)
			return
		}
		tenant, _ := SessionTenantID(c)
		for _, id := range spaces.SpaceIDs(tenant) {
			if id == c.Param("space_id") {
				c.Next()
				return
			}
		}
		writeError(c, &release.Error{Code: release.ErrorReleaseNotFound, Detail: "Space was not found"})
	})
	view.Use(guards...)
	view.Use(func(c *gin.Context) {
		v, _ := c.Get(sessionReadIdentityKey)
		identity := v.(sessionReadIdentity)
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, identity.principal.TenantID)
		c.Request = c.Request.WithContext(types.WithCaller(ctx, identity.caller))
		c.Next()
	})
	return view
}
