package enterprise_test

// RV6d acceptance (protected, written by Claude): a full-access service key lists the review queue
// and rejects review points, so the machine route can close human-queue leftovers; it can never
// approve a point (Spec docs/design/slices/RV6d-机器通道关闭审核点.md §2). The RV6b in-memory point
// platform is reached through the real API-key authentication and route authorizer.

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	enterprise "github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

const apiCandidates = "/api/v1/spaces/demo/candidates"

func (w *pointWorld) api(key *types.TenantAPIKey) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: key}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	api := r.Group("/api/v1", gate.Middleware())
	enterprise.Mount(api.Group("/spaces/:space_id"), enterprise.Deps{Candidates: w.releases, Authorizer: gate})
	return r
}

func machineReject(reason, policy string, slugs ...string) []byte {
	raw, _ := json.Marshal(map[string]any{"slugs": slugs, "outcome": "reject", "reason": reason, "policy_ref": policy})
	return raw
}

func apiItems(t *testing.T, r http.Handler, query string) []map[string]any {
	t.Helper()
	res := request(r, http.MethodGet, apiCandidates+query, "test-key", nil)
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	var out []map[string]any
	for _, item := range data(t, res.Body.Bytes())["items"].([]any) {
		out = append(out, item.(map[string]any))
	}
	return out
}

func TestAServiceKeyListsTheReviewQueue(t *testing.T) {
	w := newPointWorld(t)
	r := w.api(machineKey())
	for _, query := range []string{"", "?status=pending"} {
		items := apiItems(t, r, query)
		require.Len(t, items, 1, query)
		require.Equal(t, w.cand.ID, items[0]["candidate_id"])
		require.EqualValues(t, 5, items[0]["point_count"])
		require.EqualValues(t, 5, items[0]["pending_points"])
		require.Equal(t, "pending", items[0]["status"])
	}
	decided := apiItems(t, r, "?status=decided")
	require.Len(t, decided, 1, "the machine-published seed")
	require.Equal(t, "released", decided[0]["status"])

	bad := request(r, http.MethodGet, apiCandidates+"?status=everything", "test-key", nil)
	require.Equal(t, http.StatusBadRequest, bad.Code, bad.Body.String())
	require.Equal(t, release.ErrorDecisionInvalid, code(t, bad.Body.Bytes()))
}

func TestAServiceKeyRejectsPointsWithItsPolicy(t *testing.T) {
	w := newPointWorld(t)
	r := w.api(machineKey())
	path := apiCandidates + "/" + w.cand.ID + "/points/decisions"
	body := machineReject("  评委拒绝：值属于其他字段  ", "rv-judge:test", "P/waiting")
	res := request(r, http.MethodPost, path, "test-key", body)
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	result := data(t, res.Body.Bytes())
	require.Equal(t, []any{map[string]any{"slug": "P/waiting", "status": "rejected"}}, result["points"])
	require.Nil(t, result["release_id"])

	saved := w.points.points[pointKey(w.cand.ID, "P/waiting")]
	require.Equal(t, "reject", saved.Outcome)
	require.Equal(t, "评委拒绝：值属于其他字段（policy_ref: rv-judge:test）", saved.Reason)
	require.NotEmpty(t, saved.Subject)
	require.False(t, strings.HasPrefix(saved.Subject, types.PrincipalWebUser), "the service key decided, not a person")
	require.Equal(t, w.first.ID, w.points.head.ReleaseID, "a rejection publishes nothing")

	again := request(r, http.MethodPost, path, "test-key", machineReject("再拒一次", "rv-judge:test", "P/waiting"))
	require.Equal(t, http.StatusConflict, again.Code, again.Body.String())
	require.Equal(t, release.ErrorMemberDecided, code(t, again.Body.Bytes()))
}

func TestAServiceKeyCannotApproveAPointOrSkipItsPolicy(t *testing.T) {
	w := newPointWorld(t)
	r := w.api(machineKey())
	path := apiCandidates + "/" + w.cand.ID + "/points/decisions"
	approve, _ := json.Marshal(map[string]any{
		"slugs": []string{"Q/waiting"}, "outcome": "approve", "reason": "ok", "policy_ref": "rv-judge:test",
	})
	for name, body := range map[string]string{
		"approve":        string(approve),
		"missing policy": `{"slugs":["Q/waiting"],"outcome":"reject","reason":"ok"}`,
		"blank policy":   `{"slugs":["Q/waiting"],"outcome":"reject","reason":"ok","policy_ref":"   "}`,
		"long policy":    string(machineReject("ok", strings.Repeat("p", 201), "Q/waiting")),
		"missing reason": `{"slugs":["Q/waiting"],"outcome":"reject","policy_ref":"rv-judge:test"}`,
		"unknown key": `{"slugs":["Q/waiting"],"outcome":"reject","reason":"ok",` +
			`"policy_ref":"x","mode":"machine"}`,
		"reason over limit": string(machineReject(strings.Repeat("长", 1990), "rv-judge:test", "Q/waiting")),
		"not a point":       string(machineReject("ok", "rv-judge:test", "P/grace")),
	} {
		t.Run(name, func(t *testing.T) {
			res := request(r, http.MethodPost, path, "test-key", []byte(body))
			require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
			require.Equal(t, release.ErrorDecisionInvalid, code(t, res.Body.Bytes()))
		})
	}
	require.Empty(t, w.points.points)
	require.Equal(t, w.first.ID, w.points.head.ReleaseID)
}

func TestMachineRejectionsCloseACandidateAndStayInTheirSpace(t *testing.T) {
	w := newPointWorld(t)
	r := w.api(machineKey())
	other := request(r, http.MethodPost, "/api/v1/spaces/other/candidates/"+w.cand.ID+"/points/decisions",
		"test-key", machineReject("ok", "rv-judge:test", "P/waiting"))
	require.Equal(t, http.StatusNotFound, other.Code, other.Body.String())
	require.Equal(t, release.ErrorCandidateNotFound, code(t, other.Body.Bytes()))
	require.Empty(t, w.points.points)

	path := apiCandidates + "/" + w.cand.ID + "/points/decisions"
	res := request(r, http.MethodPost, path, "test-key",
		machineReject("评委拒绝", "rv-judge:test", "P/old", "P/waiting", "Q/grace", "Q/waiting", "entity/P"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	require.Equal(t, "rejected", data(t, res.Body.Bytes())["status"])
	require.Empty(t, apiItems(t, r, ""), "the closed candidate leaves the queue")
	var statuses []any
	for _, item := range apiItems(t, r, "?status=decided") {
		if item["candidate_id"] == w.cand.ID {
			statuses = append(statuses, item["status"])
		}
	}
	require.Equal(t, []any{"rejected"}, statuses)
}

func TestMachineReviewRoutesFailClosed(t *testing.T) {
	w := newPointWorld(t)
	routes := []struct {
		method, path string
		body         []byte
	}{
		{http.MethodGet, apiCandidates, nil},
		{
			http.MethodPost, apiCandidates + "/" + w.cand.ID + "/points/decisions",
			machineReject("ok", "rv-judge:test", "P/waiting"),
		},
	}
	restricted := []*types.TenantAPIKey{
		{ID: 1, TenantID: machineKey().TenantID, Capabilities: types.StringArray{"retrieve"}},
		{ID: 1, TenantID: machineKey().TenantID, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"restricted"}},
	}
	for _, route := range routes {
		name := fmt.Sprintf("%s %s", route.method, route.path)
		unconfigured := mountRouter(nil, machineKey())
		res := request(unconfigured, route.method, route.path, "test-key", route.body)
		require.Equal(t, http.StatusServiceUnavailable, res.Code, name)
		res = request(w.api(machineKey()), route.method, route.path, "", route.body)
		require.Equal(t, http.StatusUnauthorized, res.Code, name)
		for _, key := range restricted {
			res = request(w.api(key), route.method, route.path, "test-key", route.body)
			require.Equal(t, http.StatusForbidden, res.Code, name)
		}
	}
	require.Empty(t, w.points.points)
}
