package enterprise_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

func reviewBoundaryRouter(
	service *release.Service, caller types.Caller, guards ...gin.HandlerFunc,
) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, browser.tenant)
		ctx = types.WithPrincipal(ctx, browser.principal)
		c.Request = c.Request.WithContext(types.WithCaller(ctx, caller))
		c.Set(types.TenantIDContextKey.String(), browser.tenant)
		c.Set(types.PrincipalContextKey.String(), browser.principal)
		c.Next()
	})
	enterprise.MountSessionReviews(r.Group("/api/v1/enterprise"), enterprise.SessionDeps{
		Candidates: service, Spaces: spaceDirectory{7: {"demo"}},
	}, guards...)
	return r
}

func reviewAdmin() types.Caller {
	return types.Caller{TenantID: browser.tenant, UserID: browser.principal.ID, Role: types.TenantRoleAdmin}
}

func TestReviewBoundaryKeepsCapturedIdentityAndRejectsMismatchedAdmins(t *testing.T) {
	w := newReviewWorld(t)
	for _, caller := range []types.Caller{
		{TenantID: 8, UserID: browser.principal.ID, Role: types.TenantRoleAdmin},
		{TenantID: 7, UserID: "another-user", Role: types.TenantRoleAdmin},
		{TenantID: 7, UserID: browser.principal.ID, Role: types.TenantRoleViewer},
	} {
		// An RBAC guard that only logs or rewrites execution context cannot grant the caller Admin.
		r := reviewBoundaryRouter(w.releases, caller, func(c *gin.Context) {
			c.Request = c.Request.WithContext(types.WithCaller(c.Request.Context(), reviewAdmin()))
			c.Next()
		})
		for _, route := range []struct{ method, path string }{
			{http.MethodGet, reviewsPath},
			{http.MethodGet, reviewsPath + "/" + w.waiting.ID},
			{http.MethodPost, reviewsPath + "/" + w.waiting.ID + "/decisions"},
		} {
			res := call(r, route.method, route.path, decision("approve", "checked"))
			require.Equal(t, http.StatusForbidden, res.Code, res.Body.String())
			require.Equal(t, release.ErrorReleaseAccessDenied, code(t, res.Body.Bytes()))
			require.NotContains(t, res.Body.String(), "180日")
		}
	}
	require.Len(t, w.platform.decisions, 1)
}

func TestReviewBoundaryGuardDenialPrecedesAllReadsAndWrites(t *testing.T) {
	w := newReviewWorld(t)
	r := reviewBoundaryRouter(w.releases, reviewAdmin(), func(c *gin.Context) {
		c.AbortWithStatus(http.StatusForbidden)
	})
	require.Equal(t, http.StatusForbidden, call(r, http.MethodGet, reviewsPath, nil).Code)
	require.Equal(t, http.StatusForbidden, w.decide(r, w.waiting.ID, decision("approve", "ok")).Code)
	require.Len(t, w.platform.decisions, 1)
	require.Equal(t, w.first.ID, w.platform.head.ReleaseID)
}

func TestReviewBoundaryMissingOptionalQueueFailsClosed(t *testing.T) {
	w := newReviewWorld(t)
	// Deliberately hide QueueStore behind the original Store port.
	var original release.Store = &w.platform.expertPlatform
	withoutQueue := release.NewService(original, nil, nil, release.WithPublisher(w.platform))
	for _, service := range []*release.Service{nil, withoutQueue} {
		r := reviewBoundaryRouter(service, reviewAdmin())
		for _, route := range []struct{ method, path string }{
			{http.MethodGet, reviewsPath},
			{http.MethodGet, reviewsPath + "/" + w.waiting.ID},
			{http.MethodPost, reviewsPath + "/" + w.waiting.ID + "/decisions"},
		} {
			res := call(r, route.method, route.path, decision("approve", "ok"))
			require.Equal(t, http.StatusServiceUnavailable, res.Code, res.Body.String())
			require.Equal(t, release.ErrorServiceUnavailable, code(t, res.Body.Bytes()))
		}
	}
	require.Len(t, w.platform.decisions, 1)
}

func TestReviewBoundaryStrictTypesSizeAndUnicodeReasons(t *testing.T) {
	w := newReviewWorld(t)
	for name, raw := range map[string]string{
		"empty": "", "null": `null`, "reason null": `{"outcome":"approve","reason":null}`,
		"reason number": `{"outcome":"approve","reason":1}`, "outcome boolean": `{"outcome":true,"reason":"ok"}`,
		"nested":               `{"outcome":"approve","reason":{"reason":"ok"}}`,
		"duplicate escaped":    `{"outcome":"approve","reason":"ok","\u0072eason":"no"}`,
		"trailing":             `{"outcome":"approve","reason":"ok"}{}`,
		"oversized whitespace": string(decision("approve", "ok")) + strings.Repeat(" ", 64<<10),
		"invalid UTF8":         "{\"outcome\":\"approve\",\"reason\":\"\xff\"}",
	} {
		t.Run(name, func(t *testing.T) {
			res := w.decide(w.admin(), w.waiting.ID, []byte(raw))
			require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
			require.Equal(t, release.ErrorDecisionInvalid, code(t, res.Body.Bytes()))
		})
	}
	for _, query := range []string{"?status=", "?status=pending&status=decided"} {
		res := call(w.admin(), http.MethodGet, reviewsPath+query, nil)
		require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
	}
	require.Len(t, w.platform.decisions, 1)
	reason := strings.Repeat("核", 2000)
	res := w.decide(w.admin(), w.waiting.ID, decision("reject", "\u3000"+reason+"\u3000"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	id := dataOf(t, res)["decision_id"].(string)
	require.Equal(t, reason, w.platform.decisions[id].Reason)
}

func TestReviewBoundaryOldDecidedCandidateIsStillAddressable(t *testing.T) {
	w := newReviewWorld(t)
	require.Equal(t, http.StatusCreated, w.decide(w.admin(), w.waiting.ID, decision("reject", "no")).Code)
	for i := 0; i < 101; i++ {
		c := w.submit(t, w.first.ID, claimMember(t, fmt.Sprint("new-", i), "waiting", "90日"))
		res := w.decide(w.admin(), c.ID, decision("reject", "no"))
		require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	}
	items := w.items(t, "decided")
	require.Len(t, items, 100)
	for _, item := range items {
		require.NotEqual(t, w.waiting.ID, item["candidate_id"])
	}
	res := call(w.admin(), http.MethodGet, reviewsPath+"/"+w.waiting.ID, nil)
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	require.Equal(t, "rejected", dataOf(t, res)["status"])
	before := len(w.platform.decisions)
	res = w.decide(w.admin(), w.waiting.ID, decision("approve", "no"))
	require.Equal(t, http.StatusConflict, res.Code)
	require.Len(t, w.platform.decisions, before)
}

type reviewFaultPublisher struct {
	*reviewPlatform
	decisionErr error
	activateErr error
	activations int
	afterSave   func()
}

func (p *reviewFaultPublisher) SaveDecision(ctx context.Context, d release.Decision) (release.Decision, error) {
	if p.decisionErr != nil {
		return release.Decision{}, p.decisionErr
	}
	saved, err := p.reviewPlatform.SaveDecision(ctx, d)
	if err == nil && p.afterSave != nil {
		callback := p.afterSave
		p.afterSave = nil
		callback()
	}
	return saved, err
}

func (p *reviewFaultPublisher) Activate(ctx context.Context, write release.ActivationWrite) (release.Release, error) {
	p.activations++
	if p.activateErr != nil {
		return release.Release{}, p.activateErr
	}
	return p.reviewPlatform.Activate(ctx, write)
}

func TestReviewBoundaryErrorsPreserveApprovalAndRetryWithoutAnotherDecision(t *testing.T) {
	w := newReviewWorld(t)
	publisher := &reviewFaultPublisher{reviewPlatform: w.platform, decisionErr: errors.New("private backend detail")}
	w.releases = release.NewService(w.platform, nil, nil, release.WithPublisher(publisher))
	res := w.decide(w.admin(), w.waiting.ID, decision("approve", "ok"))
	require.Equal(t, http.StatusInternalServerError, res.Code)
	require.NotContains(t, res.Body.String(), "private")
	require.Zero(t, publisher.activations)
	require.Len(t, w.platform.decisions, 1)
	publisher.decisionErr = nil
	publisher.activateErr = &release.Error{Code: release.ErrorReleaseConflict}
	res = w.decide(w.admin(), w.waiting.ID, decision("approve", "ok"))
	require.Equal(t, http.StatusConflict, res.Code)
	require.Len(t, w.platform.decisions, 2)
	approvedID := w.platform.history[w.waiting.ID][0]
	publisher.activateErr = nil
	res = w.decide(w.admin(), w.waiting.ID, decision("approve", "new reason must not replace the approval"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	require.Equal(t, approvedID, dataOf(t, res)["decision_id"])
	require.Len(t, w.platform.decisions, 2)
	before := publisher.activations
	res = w.decide(w.admin(), w.waiting.ID, decision("approve", "again"))
	require.Equal(t, http.StatusConflict, res.Code)
	require.Equal(t, before, publisher.activations)
	require.Len(t, w.platform.decisions, 2)
}

func TestReviewBoundaryScopedLookupHidesForeignCandidateAndSortsSubjects(t *testing.T) {
	w := newReviewWorld(t)
	foreign := w.platform.candidates[w.waiting.ID]
	foreign.TenantID = 8
	w.platform.candidates[w.waiting.ID] = foreign
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		path := reviewsPath + "/" + w.waiting.ID
		if method == http.MethodPost {
			path += "/decisions"
		}
		res := call(w.admin(), method, path, decision("approve", "ok"))
		require.Equal(t, http.StatusNotFound, res.Code)
		require.Equal(t, release.ErrorCandidateNotFound, code(t, res.Body.Bytes()))
		require.NotContains(t, res.Body.String(), "180日")
	}
	c := w.submit(t, w.first.ID, claimMember(t, "Z", "one", "1"),
		claimMember(t, "A", "one", "2"), claimMember(t, "A", "two", "3"))
	res := call(w.admin(), http.MethodGet, reviewsPath+"/"+c.ID, nil)
	require.Equal(t, http.StatusOK, res.Code)
	require.Equal(t, []any{"A", "Z"}, dataOf(t, res)["subjects"])
	require.Len(t, w.platform.decisions, 1)
}

func TestReviewBoundaryRealRBACRejectionHasTypedCode(t *testing.T) {
	w := newReviewWorld(t)
	for _, enabled := range []bool{false, true} {
		cfg := &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}
		caller := reviewAdmin()
		caller.Role = types.TenantRoleViewer
		r := reviewBoundaryRouter(w.releases, caller, middleware.RequireRole(types.TenantRoleAdmin, cfg))
		res := call(r, http.MethodGet, reviewsPath, nil)
		require.Equal(t, http.StatusForbidden, res.Code)
		require.Equal(t, release.ErrorReleaseAccessDenied, code(t, res.Body.Bytes()), res.Body.String())
	}
}

func TestReviewBoundaryOpaqueClaimPayloadCannotBlockOtherCandidates(t *testing.T) {
	w := newReviewWorld(t)
	payload := map[string]any{"subject_ref": 123}
	raw, err := json.Marshal(payload)
	require.NoError(t, err)
	c := w.submit(t, w.first.ID, map[string]any{
		"kind": "claim", "logical_slug": "opaque/claim", "payload": payload,
		"member_digest": digestOf(raw), "access_scope": "space",
	})
	items := w.items(t, "pending")
	require.Len(t, items, 3)
	res := call(w.admin(), http.MethodGet, reviewsPath+"/"+c.ID, nil)
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	data := dataOf(t, res)
	require.Empty(t, data["subjects"])
	member := data["bundle_members"].([]any)[0].(map[string]any)
	require.EqualValues(t, 123, member["payload"].(map[string]any)["subject_ref"])
}

// The existing Receive accepts an absent removal, while Activate rejects it with 400.
// RV5a requires 400 to leave decisions untouched; preserve this counterexample for review.
func TestReviewActivationInvalidDoesNotRecordDecision(t *testing.T) {
	w := newReviewWorld(t)
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
		"base_release_id": w.first.ID, "removals": []string{"absent"},
		"members": []any{claimMember(t, "Q", "grace", "60日")},
	})
	require.NoError(t, err)
	c, err := w.releases.Receive(context.Background(),
		release.Principal{TenantID: 7, Subject: "svc-harness"}, "demo", raw)
	require.NoError(t, err)
	detail := call(w.admin(), http.MethodGet, reviewsPath+"/"+c.ID, nil)
	require.Equal(t, release.ErrorCandidateInvalid, dataOf(t, detail)["blocker"])
	before := len(w.platform.decisions)
	res := w.decide(w.admin(), c.ID, decision("approve", "checked"))
	require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
	require.Equal(t, release.ErrorCandidateInvalid, code(t, res.Body.Bytes()))
	t.Logf("response=%d decisions_before=%d decisions_after=%d", res.Code, before, len(w.platform.decisions))
	require.Len(t, w.platform.decisions, before, "a 400 response must not record a new decision")
	detail = call(w.admin(), http.MethodGet, reviewsPath+"/"+c.ID, nil)
	require.Equal(t, "pending", dataOf(t, detail)["status"])
	res = w.decide(w.admin(), c.ID, decision("reject", "invalid removal"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	require.Len(t, w.platform.decisions, before+1)
}
