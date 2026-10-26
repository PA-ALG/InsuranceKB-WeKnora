package enterprise_test

// RV5a acceptance (protected, written by Claude): administrators list the candidates waiting for
// a person, read one, and approve (decision + activation) or reject it through browser routes
// (Spec docs/design/slices/RV5a-人工审核队列平台.md §4). The platform is in memory; the store's
// own status derivation is proven against PostgreSQL in releasestore/review_queue_postgres_test.go.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

const reviewsPath = "/api/v1/enterprise/spaces/demo/view/candidates"

// reviewPlatform is a one-Space in-memory Store, Publisher and QueueStore with CAS activation.
type reviewPlatform struct {
	expertPlatform
	order   []string
	created map[string]time.Time
	history map[string][]string // candidate -> decision ids in the order they were saved
	clock   time.Time
}

func (p *reviewPlatform) tick() time.Time {
	p.clock = p.clock.Add(time.Second)
	return p.clock
}

func (p *reviewPlatform) CreateCandidate(
	ctx context.Context, c release.Candidate, b release.Bundle,
) (release.Candidate, error) {
	saved, err := p.expertPlatform.CreateCandidate(ctx, c, b)
	p.order, p.created[saved.ID] = append(p.order, saved.ID), p.tick()
	return saved, err
}

func (p *reviewPlatform) SaveDecision(ctx context.Context, d release.Decision) (release.Decision, error) {
	d.CreatedAt = p.tick()
	saved, err := p.expertPlatform.SaveDecision(ctx, d)
	p.history[saved.CandidateID] = append(p.history[saved.CandidateID], saved.ID)
	return saved, err
}

func (p *reviewPlatform) Queue(
	_ context.Context, tenantID uint64, spaceID, status string, limit int,
) ([]release.QueueEntry, error) {
	var out []release.QueueEntry
	for _, id := range p.order {
		c := p.candidates[id]
		if c.TenantID != tenantID || c.SpaceID != spaceID {
			continue
		}
		e := release.QueueEntry{Candidate: c, CreatedAt: p.created[id], CreatedBy: "svc-harness"}
		e.Candidate.Status = "pending"
		if ids := p.history[id]; len(ids) > 0 {
			d := p.decisions[ids[len(ids)-1]]
			e.Decision = &d
			switch d.Outcome {
			case "approve":
				e.Candidate.Status = "approved"
			case "reject":
				e.Candidate.Status = "rejected"
			}
		}
		for _, r := range p.releases {
			if r.CandidateID == id {
				e.Candidate.Status, e.ReleaseID = "released", r.ID
			}
		}
		if (status == "pending") == (e.Candidate.Status == "pending") {
			out = append(out, e)
		}
	}
	if status == "decided" {
		for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
			out[i], out[j] = out[j], out[i]
		}
		if len(out) > limit {
			out = out[:limit]
		}
	}
	return out, nil
}

type reviewWorld struct {
	platform *reviewPlatform
	releases *release.Service
	first    release.Release
	waiting  release.Candidate // changes P/waiting
	grace    release.Candidate // adds Q/grace
}

func claimMember(t *testing.T, subject, field, value string) map[string]any {
	t.Helper()
	slug := subject + "/" + field
	payload := map[string]any{
		"claim_id": slug, "logical_key": slug, "subject_ref": subject, "predicate": field,
		"state": "present", "value": value, "origin": "SOURCE_SUPPORTED", "expert_lock": false,
		"evidence": []any{map[string]any{
			"source_ref": expertSourceRef, "file_sha256": strings.Repeat("ab", 32), "quote": value,
			"access_scope": "space",
			"locator":      map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1, "start": 0, "end": len([]rune(value))},
		}},
		"maintenance": map[string]any{"revision_no": 0, "changed_by": "compile", "first_release_id": "release-0"},
	}
	canonical, err := json.Marshal(payload)
	require.NoError(t, err)
	return map[string]any{
		"kind": "claim", "logical_slug": slug, "payload": payload, "member_digest": digestOf(canonical),
		"evidence_refs": []string{expertSourceRef}, "access_scope": "space",
	}
}

func (w *reviewWorld) submit(t *testing.T, base string, members ...map[string]any) release.Candidate {
	t.Helper()
	doc := map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test", "members": members,
	}
	if base != "" {
		doc["base_release_id"] = base
	}
	raw, err := json.Marshal(doc)
	require.NoError(t, err)
	c, err := w.releases.Receive(context.Background(), release.Principal{TenantID: 7, Subject: "svc-harness"}, "demo", raw)
	require.NoError(t, err)
	return c
}

func newReviewWorld(t *testing.T) *reviewWorld {
	t.Helper()
	schemas := map[string][]byte{}
	for _, name := range []string{"candidate_bundle", "evidence", "locator"} {
		raw, err := os.ReadFile("../../contracts/" + name + ".schema.json")
		require.NoError(t, err)
		schemas[name] = raw
	}
	platform := &reviewPlatform{
		expertPlatform: expertPlatform{
			candidates: map[string]release.Candidate{}, bundles: map[string]release.Bundle{},
			decisions: map[string]release.Decision{}, releases: map[string]release.Release{},
		},
		created: map[string]time.Time{}, history: map[string][]string{},
		clock: time.Date(2026, 10, 26, 8, 0, 0, 0, time.UTC),
	}
	records := expertRecords{}
	w := &reviewWorld{platform: platform}
	w.releases = release.NewService(platform, expert.NewResolver(records, pdfSources{}), schemas,
		release.WithPublisher(platform), release.WithEvidenceVerifier(expert.NewVerifier(records, pdfSources{})))
	ctx, harness := context.Background(), release.Principal{TenantID: 7, Subject: "svc-harness"}
	seed := w.submit(t, "", claimMember(t, "P", "waiting", "90日"))
	d, err := w.releases.Decide(ctx, harness, "demo", seed.ID, release.DecisionInput{
		Outcome: "approve", Mode: "machine", PolicyRef: "review-policy@2",
	})
	require.NoError(t, err)
	w.first, err = w.releases.Activate(ctx, harness, "demo", seed.ID, d.ID)
	require.NoError(t, err)
	w.waiting = w.submit(t, w.first.ID, claimMember(t, "P", "waiting", "180日"))
	w.grace = w.submit(t, w.first.ID, claimMember(t, "Q", "grace", "60日"))
	return w
}

func (w *reviewWorld) router(who identity, role types.TenantRole) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, who.tenant)
		ctx = types.WithPrincipal(ctx, who.principal)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: who.tenant, UserID: who.principal.ID, Role: role})
		if who.apiKey {
			ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 3, FullAccess: true})
		}
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), who.tenant)
		c.Set(types.PrincipalContextKey.String(), who.principal)
		c.Next()
	})
	deps := enterprise.SessionDeps{Candidates: w.releases, Spaces: spaceDirectory{7: {"demo"}, 8: {"other"}}}
	enterprise.MountSessionReviews(r.Group("/api/v1/enterprise"), deps)
	return r
}

func (w *reviewWorld) admin() *gin.Engine { return w.router(browser, types.TenantRoleAdmin) }

func call(r http.Handler, method, path string, body []byte) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	res := httptest.NewRecorder()
	r.ServeHTTP(res, req)
	return res
}

func dataOf(t *testing.T, res *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var body struct {
		Success bool           `json:"success"`
		Data    map[string]any `json:"data"`
	}
	require.NoError(t, json.Unmarshal(res.Body.Bytes(), &body), res.Body.String())
	require.True(t, body.Success, res.Body.String())
	return body.Data
}

func (w *reviewWorld) items(t *testing.T, status string) []map[string]any {
	t.Helper()
	res := call(w.admin(), http.MethodGet, reviewsPath+"?status="+status, nil)
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	var out []map[string]any
	for _, item := range dataOf(t, res)["items"].([]any) {
		out = append(out, item.(map[string]any))
	}
	return out
}

func decision(outcome, reason string) []byte {
	raw, _ := json.Marshal(map[string]string{"outcome": outcome, "reason": reason})
	return raw
}

func (w *reviewWorld) decide(r http.Handler, id string, body []byte) *httptest.ResponseRecorder {
	return call(r, http.MethodPost, reviewsPath+"/"+id+"/decisions", body)
}

func TestReviewQueueListsPendingCandidatesForAnAdministrator(t *testing.T) {
	w := newReviewWorld(t)
	items := w.items(t, "pending")
	require.Len(t, items, 2)
	require.Equal(t, w.waiting.ID, items[0]["candidate_id"], "oldest first")
	require.Equal(t, w.grace.ID, items[1]["candidate_id"])
	first := items[0]
	require.Equal(t, "pending", first["status"])
	require.Equal(t, []any{"P"}, first["subjects"])
	require.EqualValues(t, 1, first["members"])
	require.EqualValues(t, 0, first["removals"])
	require.Nil(t, first["decision"])
	require.Nil(t, first["release_id"])
	require.Equal(t, "svc-harness", first["created_by"])
	require.Equal(t, w.first.ID, first["base_release_id"])
	_, err := time.Parse(time.RFC3339, first["created_at"].(string))
	require.NoError(t, err)

	res := call(w.admin(), http.MethodGet, reviewsPath, nil)
	require.Equal(t, http.StatusOK, res.Code)
	require.Len(t, dataOf(t, res)["items"], 2, "pending is the default")
	decided := w.items(t, "decided")
	require.Len(t, decided, 1, "the machine-published seed is already released")
	require.Equal(t, "released", decided[0]["status"])
	require.Equal(t, w.first.ID, decided[0]["release_id"])
}

func TestReviewDetailCarriesTheBundleAndWhetherItCanGoLive(t *testing.T) {
	w := newReviewWorld(t)
	res := call(w.admin(), http.MethodGet, reviewsPath+"/"+w.waiting.ID, nil)
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	data := dataOf(t, res)
	require.Equal(t, w.waiting.ID, data["candidate_id"])
	require.Equal(t, "pending", data["status"])
	require.Equal(t, w.first.ID, data["head_release_id"])
	require.Equal(t, "", data["blocker"])
	members := data["bundle_members"].([]any)
	require.Len(t, members, 1)
	member := members[0].(map[string]any)
	require.Equal(t, "P/waiting", member["logical_slug"])
	require.Equal(t, "180日", member["payload"].(map[string]any)["value"])
	require.Equal(t, []any{expertSourceRef}, member["evidence_refs"])
	require.Empty(t, data["bundle_removals"])
}

func TestApprovingActivatesAndMovesTheCandidateToDecided(t *testing.T) {
	w := newReviewWorld(t)
	res := w.decide(w.admin(), w.waiting.ID, decision("approve", "  核对无误  "))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	data := dataOf(t, res)
	require.Equal(t, "released", data["status"])
	require.Equal(t, w.platform.head.ReleaseID, data["release_id"])
	require.EqualValues(t, 2, data["epoch"])
	saved := w.platform.decisions[data["decision_id"].(string)]
	require.Equal(t, "approve", saved.Outcome)
	require.Equal(t, "human", saved.Mode)
	require.Equal(t, "核对无误", saved.Reason)
	require.Equal(t, browser.principal.StorageID(), saved.Subject)

	pending := w.items(t, "pending")
	require.Len(t, pending, 1)
	require.Equal(t, w.grace.ID, pending[0]["candidate_id"])
	decided := w.items(t, "decided")
	require.Len(t, decided, 2, "the approved candidate and the machine-published seed")
	require.Equal(t, w.waiting.ID, decided[0]["candidate_id"], "newest first")
	require.Equal(t, "released", decided[0]["status"])
	require.Equal(t, data["release_id"], decided[0]["release_id"])
	require.Equal(t, "approve", decided[0]["decision"].(map[string]any)["outcome"])
}

func TestRejectingRecordsOnlyADecisionAndADecidedCandidateStaysDecided(t *testing.T) {
	w := newReviewWorld(t)
	res := w.decide(w.admin(), w.grace.ID, decision("reject", "取值与条款不符"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	data := dataOf(t, res)
	require.Equal(t, "rejected", data["status"])
	require.Nil(t, data["release_id"])
	require.Nil(t, data["epoch"])
	require.Equal(t, w.first.ID, w.platform.head.ReleaseID, "a rejection publishes nothing")

	before := len(w.platform.decisions)
	for _, outcome := range []string{"approve", "reject"} {
		again := w.decide(w.admin(), w.grace.ID, decision(outcome, "再看一次"))
		require.Equal(t, http.StatusConflict, again.Code, again.Body.String())
		require.Equal(t, "CANDIDATE_DECIDED", code(t, again.Body.Bytes()))
	}
	require.Len(t, w.platform.decisions, before, "a refused decision is not recorded")
	detail := dataOf(t, call(w.admin(), http.MethodGet, reviewsPath+"/"+w.grace.ID, nil))
	require.Equal(t, "rejected", detail["status"])
	require.Equal(t, "CANDIDATE_DECIDED", detail["blocker"])
}

func TestAStaleCandidateIsBlockedAndKeepsItsApproval(t *testing.T) {
	w := newReviewWorld(t)
	stale := w.submit(t, w.first.ID, claimMember(t, "P", "waiting", "365日"))
	require.Equal(t, http.StatusCreated, w.decide(w.admin(), w.waiting.ID, decision("approve", "ok")).Code)

	detail := dataOf(t, call(w.admin(), http.MethodGet, reviewsPath+"/"+stale.ID, nil))
	require.Equal(t, "NEEDS_REBASE", detail["blocker"], "the Head changed the member this candidate changes")

	before := len(w.platform.decisions)
	res := w.decide(w.admin(), stale.ID, decision("approve", "ok"))
	require.Equal(t, http.StatusConflict, res.Code, res.Body.String())
	require.Equal(t, release.ErrorNeedsRebase, code(t, res.Body.Bytes()))
	require.Len(t, w.platform.decisions, before+1, "the approval is kept for a later retry")
	var status string
	for _, item := range w.items(t, "decided") {
		if item["candidate_id"] == stale.ID {
			status = item["status"].(string)
		}
	}
	require.Equal(t, "approved", status)
	refused := w.decide(w.admin(), stale.ID, decision("reject", "no"))
	require.Equal(t, http.StatusConflict, refused.Code)
	require.Equal(t, "CANDIDATE_DECIDED", code(t, refused.Body.Bytes()))

	// Unrelated to the Head's change, the other candidate still goes live.
	require.Equal(t, http.StatusCreated, w.decide(w.admin(), w.grace.ID, decision("approve", "ok")).Code)
}

func TestReviewRoutesNeedAnAdministratorBrowserSessionInTheirSpace(t *testing.T) {
	w := newReviewWorld(t)
	denied, missing := release.ErrorReleaseAccessDenied, release.ErrorReleaseNotFound
	serviceKey := identity{tenant: 7, principal: browser.principal, apiKey: true}
	otherTenant := identity{tenant: 8, principal: browser.principal}
	routes := []struct{ method, path string }{
		{http.MethodGet, reviewsPath},
		{http.MethodGet, reviewsPath + "/" + w.waiting.ID},
		{http.MethodPost, reviewsPath + "/" + w.waiting.ID + "/decisions"},
	}
	for name, probe := range map[string]struct {
		who    identity
		role   types.TenantRole
		space  string
		status int
		code   string
	}{
		"contributor role": {browser, types.TenantRoleContributor, "demo", http.StatusForbidden, denied},
		"service key":      {serviceKey, types.TenantRoleOwner, "demo", http.StatusForbidden, denied},
		"unknown Space":    {browser, types.TenantRoleAdmin, "nope", http.StatusNotFound, missing},
		"another tenant":   {browser, types.TenantRoleAdmin, "other", http.StatusNotFound, missing},
		"tenant 8 caller":  {otherTenant, types.TenantRoleOwner, "demo", http.StatusNotFound, missing},
	} {
		for _, route := range routes {
			t.Run(name+" "+route.method+" "+route.path, func(t *testing.T) {
				path := strings.Replace(route.path, "/demo/", "/"+probe.space+"/", 1)
				res := call(w.router(probe.who, probe.role), route.method, path, decision("approve", "ok"))
				require.Equal(t, probe.status, res.Code, res.Body.String())
				require.Equal(t, probe.code, code(t, res.Body.Bytes()))
				require.NotContains(t, res.Body.String(), "180日")
			})
		}
	}
	require.Len(t, w.platform.decisions, 1, "only the seed's machine decision exists")
	require.Equal(t, w.first.ID, w.platform.head.ReleaseID)
}

func TestReviewRequestsAreStrictAndWriteNothing(t *testing.T) {
	w := newReviewWorld(t)
	res := call(w.admin(), http.MethodGet, reviewsPath+"?status=everything", nil)
	require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
	require.Equal(t, release.ErrorDecisionInvalid, code(t, res.Body.Bytes()))

	missing := call(w.admin(), http.MethodGet, reviewsPath+"/cand_unknown", nil)
	require.Equal(t, http.StatusNotFound, missing.Code)
	require.Equal(t, release.ErrorCandidateNotFound, code(t, missing.Body.Bytes()))
	unknown := w.decide(w.admin(), "cand_unknown", decision("approve", "ok"))
	require.Equal(t, http.StatusNotFound, unknown.Code)
	require.Equal(t, release.ErrorCandidateNotFound, code(t, unknown.Body.Bytes()))

	for name, body := range map[string]string{
		"unknown key":    `{"outcome":"approve","reason":"ok","mode":"machine"}`,
		"duplicate key":  `{"outcome":"approve","outcome":"reject","reason":"ok"}`,
		"manual outcome": `{"outcome":"manual","reason":"ok"}`,
		"missing reason": `{"outcome":"approve"}`,
		"blank reason":   `{"outcome":"reject","reason":"   "}`,
		"long reason":    fmt.Sprintf(`{"outcome":"reject","reason":%q}`, strings.Repeat("长", 2001)),
		"not an object":  `["approve"]`,
	} {
		t.Run(name, func(t *testing.T) {
			res := w.decide(w.admin(), w.waiting.ID, []byte(body))
			require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
			require.Equal(t, release.ErrorDecisionInvalid, code(t, res.Body.Bytes()))
		})
	}
	require.Len(t, w.platform.decisions, 1)
	require.Len(t, w.items(t, "pending"), 2)
}
