package enterprise_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

type sessionGrantKey struct{}

type sessionPublisherProbe struct {
	*publishStore
	tenant, execution uint64
	caller            types.Caller
	grant             any
	done              <-chan struct{}
	calls             int
}

func (p *sessionPublisherProbe) ReleaseByID(
	ctx context.Context, tenant uint64, space, id string,
) (release.Release, error) {
	p.calls++
	p.tenant = tenant
	p.execution, _ = types.TenantIDFromContext(ctx)
	p.caller = types.CallerFromContext(ctx)
	p.grant = ctx.Value(sessionGrantKey{})
	p.done = ctx.Done()
	return p.publishStore.ReleaseByID(ctx, tenant, space, id)
}

func sessionBoundaryRouter(
	t *testing.T, probe *sessionPublisherProbe, mutate func(*gin.Context), guards ...gin.HandlerFunc,
) *gin.Engine {
	t.Helper()
	schema, err := os.ReadFile("../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	svc := release.NewService(probe.publishStore, nil, map[string][]byte{"candidate_bundle": schema},
		release.WithPublisher(probe))
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, browser.tenant)
		ctx = types.WithPrincipal(ctx, browser.principal)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: 7, UserID: "user-1", Role: types.TenantRoleViewer})
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), browser.tenant)
		c.Set(types.PrincipalContextKey.String(), browser.principal)
		if mutate != nil {
			mutate(c)
		}
		c.Next()
	})
	enterprise.MountSessionReads(r.Group("/api/v1/enterprise"), enterprise.SessionDeps{
		Candidates: svc, Spaces: spaceDirectory{7: {"demo"}},
	}, guards...)
	return r
}

func TestSessionReadsRejectInconsistentIdentityContexts(t *testing.T) {
	for name, mutate := range map[string]func(*gin.Context){
		"mixed tenants":      func(c *gin.Context) { c.Set(types.TenantIDContextKey.String(), uint64(8)) },
		"missing Gin tenant": func(c *gin.Context) { delete(c.Keys, types.TenantIDContextKey.String()) },
		"missing context tenant": func(c *gin.Context) {
			ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(0))
			c.Request = c.Request.WithContext(ctx)
		},
		"mixed principals": func(c *gin.Context) {
			c.Set(types.PrincipalContextKey.String(), types.Principal{Type: types.PrincipalWebUser, ID: "other"})
		},
		"malformed API key scope": func(c *gin.Context) {
			ctx := context.WithValue(c.Request.Context(), types.TenantAPIKeyScopeContextKey, "bad")
			c.Request = c.Request.WithContext(ctx)
		},
	} {
		t.Run(name, func(t *testing.T) {
			probe := &sessionPublisherProbe{publishStore: newPublishStore()}
			guardRan := false
			r := sessionBoundaryRouter(t, probe, mutate, func(c *gin.Context) { guardRan = true; c.Next() })
			w := read(r, viewPath+"/active")
			require.Equal(t, http.StatusForbidden, w.Code, w.Body.String())
			require.Equal(t, release.ErrorReleaseAccessDenied, code(t, w.Body.Bytes()))
			require.False(t, guardRan)
			require.Zero(t, probe.calls)
		})
	}
}

func TestSessionReadsKeepTheCallerAfterGuardsRewriteExecutionTenant(t *testing.T) {
	world := sessionWorld(t)
	probe := &sessionPublisherProbe{publishStore: world.store}
	first := func(c *gin.Context) {
		ctx := types.WithExecutionTenant(c.Request.Context(), 8)
		ctx = context.WithValue(ctx, sessionGrantKey{}, "read-grants")
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(8))
		c.Next()
	}
	second := func(c *gin.Context) {
		tenant, ok := enterprise.SessionTenantID(c)
		require.True(t, ok)
		require.Equal(t, uint64(7), tenant)
		execution, _ := types.TenantIDFromContext(c.Request.Context())
		require.Equal(t, uint64(8), execution)
		c.Next()
	}
	r := sessionBoundaryRouter(t, probe, nil, first, second)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, viewPath+"/active", nil).WithContext(ctx)
	r.ServeHTTP(w, req)
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Equal(t, uint64(7), probe.tenant)
	require.Equal(t, uint64(7), probe.execution)
	require.Equal(t, types.Caller{TenantID: 7, UserID: "user-1", Role: types.TenantRoleViewer}, probe.caller)
	require.Equal(t, "read-grants", probe.grant)
	require.Equal(t, ctx.Done(), probe.done)
}

func TestSessionFilteringDoesNotChangeServiceKeyReads(t *testing.T) {
	world := sessionWorld(t)
	w := read(sessionRouter(t, world, browser), viewPath+"/active")
	require.Equal(t, http.StatusOK, w.Code)
	require.Len(t, memberSlugs(t, w.Body.Bytes()), 2)
	w = get(world.router(t, machineKey()), releasePath)
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Len(t, memberSlugs(t, w.Body.Bytes()), 3)
	require.Len(t, world.store.releases["release-1"].Members, 3)
}

func TestSessionFileReadsRefuseTheActiveAliasBeforeOpening(t *testing.T) {
	world := sessionWorld(t)
	world.store.releases["active"] = world.store.releases["release-1"]
	w := read(sessionRouter(t, world, browser), viewPath+"/active/sources/k-1/attempts/2/file")
	require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
	require.Equal(t, release.ErrorReleaseNotFound, code(t, w.Body.Bytes()))
	require.Empty(t, world.opens)
}
