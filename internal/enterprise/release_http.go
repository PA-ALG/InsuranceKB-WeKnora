package enterprise

import (
	"net/http"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/gin-gonic/gin"
)

func releaseETag(id string, retired bool) string {
	if retired {
		id += ";retired"
	}
	return `"` + id + `"`
}

// GET uses weak comparison, including lists and the existence wildcard.
func matchesReleaseETag(value, tag string) bool {
	for _, candidate := range strings.Split(value, ",") {
		candidate = strings.TrimSpace(candidate)
		if candidate == "*" || strings.TrimPrefix(candidate, "W/") == tag {
			return true
		}
	}
	return false
}

func releaseCacheHeaders(c *gin.Context, tag string) {
	c.Header("ETag", tag)
	c.Header("Cache-Control", "private, no-cache")
	c.Writer.Header().Add("Vary", "Authorization, X-Tenant-ID")
}

func readRelease(c *gin.Context, service *release.Service, releaseID string) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	ctx, space := c.Request.Context(), c.Param("space_id")
	if condition := c.GetHeader("If-None-Match"); condition != "" {
		ref, err := service.ReleaseReference(ctx, p, space, releaseID)
		if err != nil {
			writeError(c, err)
			return
		}
		if ref != nil {
			tag := releaseETag(ref.ID, ref.Retired)
			if matchesReleaseETag(condition, tag) {
				releaseCacheHeaders(c, tag)
				c.Status(http.StatusNotModified)
				return
			}
			// Pin the Active resolved above, so a concurrent Head advance cannot
			// pair one version's validator with another version's body.
			releaseID = ref.ID
		}
	}
	result, err := service.Release(ctx, p, space, releaseID)
	if err != nil {
		writeError(c, err)
		return
	}
	releaseCacheHeaders(c, releaseETag(result.ID, result.RetiredAt != nil))
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}
