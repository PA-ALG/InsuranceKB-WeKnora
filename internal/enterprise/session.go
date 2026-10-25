package enterprise

import (
	"net/http"
	"sort"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/Tencent/WeKnora/internal/types"
)

// SpaceDirectory lists the configured enterprise Spaces of a tenant.
type SpaceDirectory interface {
	SpaceIDs(tenantID uint64) []string
	KnowledgeBases(tenantID uint64, spaceID string) (rawKB, wikiKB string, ok bool)
}

// SessionDeps supplies collaborators for browser reads, attributed spot-check verdicts and expert edits.
type SessionDeps struct {
	Candidates *release.Service
	Sources    *source.Service
	SpotChecks *spotcheck.Service
	Experts    *expert.Service
	// Confirmations backs the "to confirm" list and answers (S5b-3a).
	Confirmations *confirm.Service
	Files         SourceFiles
	Spaces        SpaceDirectory
}

const sessionReadIdentityKey = "enterprise.session_read_identity"

type sessionReadIdentity struct {
	principal release.Principal
	caller    types.Caller
}

func sessionReadPrincipal(c *gin.Context) (release.Principal, bool) {
	v, ok := c.Get(sessionReadIdentityKey)
	identity, valid := v.(sessionReadIdentity)
	return identity.principal, ok && valid
}

// SessionTenantID returns the validated calling tenant saved before view guards.
// KB resolvers use it even when a prior guard changed the execution tenant.
func SessionTenantID(c *gin.Context) (uint64, bool) {
	p, ok := sessionReadPrincipal(c)
	return p.TenantID, ok
}

func checkSessionRead(c *gin.Context) {
	ctx := c.Request.Context()
	tenant, tenantOK := types.TenantIDFromContext(ctx)
	principal, principalOK := types.PrincipalFromContext(ctx)
	ginTenant, _ := c.Get(types.TenantIDContextKey.String())
	ginPrincipal, _ := c.Get(types.PrincipalContextKey.String())
	if !tenantOK || tenant == 0 || ginTenant != tenant || !principalOK || ginPrincipal != principal ||
		principal.Type != types.PrincipalWebUser || strings.TrimSpace(principal.ID) == "" ||
		ctx.Value(types.TenantAPIKeyScopeContextKey) != nil {
		writeError(c, &release.Error{
			Code: release.ErrorReleaseAccessDenied, Detail: "an authenticated browser session is required",
		})
		return
	}
	c.Set(sessionReadIdentityKey, sessionReadIdentity{
		principal: release.Principal{TenantID: tenant, Subject: principal.StorageID()},
		caller:    types.CallerFromContext(ctx),
	})
	c.Next()
}

// MountSessionReads registers only browser GET routes on /api/v1/enterprise.
// View guards run after identity/Space checks and before the shared read handlers.
func MountSessionReads(r gin.IRouter, deps SessionDeps, viewGuards ...gin.HandlerFunc) {
	group := r.Group("", checkSessionRead)
	service := deps.Candidates.SpaceReadView()
	group.GET("/spaces", func(c *gin.Context) {
		if deps.Spaces == nil {
			candidateUnavailable(c)
			return
		}
		tenant, _ := SessionTenantID(c)
		ids := append([]string(nil), deps.Spaces.SpaceIDs(tenant)...)
		sort.Strings(ids)
		spaces := make([]gin.H, 0, len(ids))
		for _, id := range ids {
			spaces = append(spaces, gin.H{"space_id": id})
		}
		c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"spaces": spaces}})
	})
	view := sessionSpaceRoutes(group, deps.Spaces, viewGuards...)
	view.GET("/releases/active", func(c *gin.Context) { readRelease(c, service, "") })
	samples := sessionSpotCheckRoutes(group, deps, viewGuards...)
	samples.GET("/samples", func(c *gin.Context) { listSamples(c, deps.SpotChecks.SpaceReadView(), true) })
	confirmations := sessionConfirmationRoutes(group, deps, viewGuards...)
	confirmations.GET("/confirmations", func(c *gin.Context) { listConfirmations(c, deps.Confirmations, true) })
	view.GET("/releases/:release_id", func(c *gin.Context) { readRelease(c, service, c.Param("release_id")) })
	spacesPath := strings.TrimSuffix(view.BasePath(), "/")
	view.GET("/releases/:release_id/citation", func(c *gin.Context) {
		citation(c, service, deps.Sources, deps.Experts, spacesPath)
	})
	view.GET("/releases/:release_id/sources/:knowledge_id/attempts/:attempt/file", func(c *gin.Context) {
		if id := strings.TrimSpace(c.Param("release_id")); id == "" || id == "active" {
			writeError(c, &release.Error{
				Code: release.ErrorReleaseNotFound, Detail: "an explicit release id is required",
			})
			return
		}
		citedFile(c, service, deps.Files)
	})
}
