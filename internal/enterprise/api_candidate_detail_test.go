package enterprise_test

// RV6e acceptance (protected, written by Claude): a full-access service key reads one candidate's
// review detail, the same ReviewDetail the session route returns, so the machine route can check a
// candidate's content before it closes review points (Spec
// docs/design/slices/RV6e-服务密钥读取候选明细.md §2, §5). Reading writes nothing. The RV6b
// in-memory point platform is reached through the real API-key authentication and route authorizer.

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	enterprise "github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

func apiDetail(t *testing.T, r http.Handler, id string) map[string]any {
	t.Helper()
	res := request(r, http.MethodGet, apiCandidates+"/"+id, "test-key", nil)
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	return data(t, res.Body.Bytes())
}

// browserAPI mounts the API-key routes behind an administrator's browser session: a tenant and a
// web-user principal, but no API-key scope.
func (w *pointWorld) browserAPI() *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, browser.tenant)
		ctx = types.WithPrincipal(ctx, browser.principal)
		ctx = types.WithCaller(ctx, types.Caller{
			TenantID: browser.tenant, UserID: browser.principal.ID, Role: types.TenantRoleAdmin,
		})
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), browser.tenant)
		c.Set(types.PrincipalContextKey.String(), browser.principal)
		c.Next()
	})
	gate := middleware.NewAPIKeyRouteAuthorizer()
	api := r.Group("/api/v1", gate.Middleware())
	enterprise.Mount(api.Group("/spaces/:space_id"), enterprise.Deps{Candidates: w.releases, Authorizer: gate})
	return r
}

func TestAServiceKeyReadsACandidateLikeTheSessionRoute(t *testing.T) {
	w := newPointWorld(t)
	got := apiDetail(t, w.api(machineKey()), w.cand.ID)
	require.Equal(t, w.detail(t, w.cand.ID), got, "the same ReviewDetail as the session route")
	require.Equal(t, w.cand.ID, got["candidate_id"])
	require.Equal(t, "pending", got["status"])
	require.Equal(t, w.first.ID, got["head_release_id"])
	require.Equal(t, []any{"P/old"}, got["bundle_removals"])

	stored := map[string]release.Member{}
	for _, m := range w.points.bundles[w.cand.ID].Members {
		stored[m.LogicalSlug] = m
	}
	members := got["bundle_members"].([]any)
	require.Len(t, members, len(stored))
	payloads := map[string]map[string]any{}
	for _, item := range members {
		member := item.(map[string]any)
		slug := member["logical_slug"].(string)
		want, ok := stored[slug]
		require.True(t, ok, slug)
		require.Equal(t, want.MemberDigest, member["member_digest"], slug)
		raw, err := json.Marshal(member["payload"])
		require.NoError(t, err)
		require.JSONEq(t, string(want.Payload), string(raw), slug)
		payloads[slug] = member["payload"].(map[string]any)
	}
	require.Equal(t, "180日", payloads["P/waiting"]["value"], "the proposed content, not the Head's")

	points := pointsOf(t, got)
	require.Len(t, points, 5)
	for slug, point := range points {
		require.Equal(t, "pending", point["status"], slug)
		require.Nil(t, point["decision"], slug)
	}
	require.Empty(t, w.points.points, "reading decides nothing")
	require.Equal(t, w.first.ID, w.points.head.ReleaseID)
}

func TestCandidateDetailShowsMachineRejections(t *testing.T) {
	w := newPointWorld(t)
	r := w.api(machineKey())
	res := request(r, http.MethodPost, apiCandidates+"/"+w.cand.ID+"/points/decisions", "test-key",
		machineReject("评委拒绝", "rv-judge:test", "P/waiting"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())

	got := apiDetail(t, r, w.cand.ID)
	require.Equal(t, w.detail(t, w.cand.ID), got)
	require.Equal(t, release.ErrorCandidateDecided, got["blocker"], "a point decision ends whole review")
	points := pointsOf(t, got)
	require.Equal(t, "rejected", points["P/waiting"]["status"])
	decision := points["P/waiting"]["decision"].(map[string]any)
	require.Equal(t, "reject", decision["outcome"])
	require.Equal(t, "评委拒绝（policy_ref: rv-judge:test）", decision["reason"])
	require.Equal(t, "pending", points["Q/waiting"]["status"])
}

func TestCandidateDetailStaysInItsSpace(t *testing.T) {
	w := newPointWorld(t)
	r := w.api(machineKey())
	for _, path := range []string{
		"/api/v1/spaces/other/candidates/" + w.cand.ID,
		apiCandidates + "/no-such-candidate",
	} {
		res := request(r, http.MethodGet, path, "test-key", nil)
		require.Equal(t, http.StatusNotFound, res.Code, path)
		require.Equal(t, release.ErrorCandidateNotFound, code(t, res.Body.Bytes()), path)
	}
}

func TestCandidateDetailFailsClosed(t *testing.T) {
	w := newPointWorld(t)
	path := apiCandidates + "/" + w.cand.ID
	res := request(mountRouter(nil, machineKey()), http.MethodGet, path, "test-key", nil)
	require.Equal(t, http.StatusServiceUnavailable, res.Code, res.Body.String())
	res = request(w.api(machineKey()), http.MethodGet, path, "", nil)
	require.Equal(t, http.StatusUnauthorized, res.Code, res.Body.String())
	for _, key := range []*types.TenantAPIKey{
		{ID: 1, TenantID: machineKey().TenantID, Capabilities: types.StringArray{"retrieve"}},
		{ID: 1, TenantID: machineKey().TenantID, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"restricted"}},
	} {
		res = request(w.api(key), http.MethodGet, path, "test-key", nil)
		require.Equal(t, http.StatusForbidden, res.Code, res.Body.String())
	}
	res = call(w.browserAPI(), http.MethodGet, path, nil)
	require.Equal(t, http.StatusForbidden, res.Code, res.Body.String())
	require.Equal(t, release.ErrorReleaseAccessDenied, code(t, res.Body.Bytes()))
}
