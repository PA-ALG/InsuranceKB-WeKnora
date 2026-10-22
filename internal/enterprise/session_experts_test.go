package enterprise_test

// S9a implementer tests: the browser expert-edit route (tenant Admin, Space check, typed
// failures) and the citation of an expert revision. The publishing rules themselves are the
// expert package's acceptance tests.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
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

const expertEditsPath = "/api/v1/enterprise/spaces/demo/view/expert-edits"

var expertSourceRef = "source:v1:k-1:1:" + strings.Repeat("ab", 32)

// expertPlatform is a one-Head in-memory platform with CAS on activation.
type expertPlatform struct {
	candidates map[string]release.Candidate
	bundles    map[string]release.Bundle
	decisions  map[string]release.Decision
	releases   map[string]release.Release
	head       release.Head
}

func (p *expertPlatform) CreateCandidate(_ context.Context, c release.Candidate, b release.Bundle) (release.Candidate, error) {
	c.ID, c.Status = fmt.Sprintf("candidate-%d", len(p.candidates)+1), "created"
	p.candidates[c.ID], p.bundles[c.ID] = c, b
	return c, nil
}

func (p *expertPlatform) CandidateByID(_ context.Context, _ uint64, _, id string) (release.Candidate, error) {
	c, ok := p.candidates[id]
	if !ok {
		return release.Candidate{}, &release.Error{Code: release.ErrorCandidateNotFound}
	}
	return c, nil
}

func (p *expertPlatform) BundleOf(_ context.Context, _ uint64, _, id string) (release.Bundle, error) {
	return p.bundles[id], nil
}

func (p *expertPlatform) Head(context.Context, uint64, string) (release.Head, error) {
	return p.head, nil
}

func (p *expertPlatform) MembersOf(_ context.Context, _ uint64, _, id string) (map[string]string, error) {
	out := map[string]string{}
	for _, m := range p.releases[id].Members {
		out[m.LogicalSlug] = m.MemberDigest
	}
	return out, nil
}

func (p *expertPlatform) SaveDecision(_ context.Context, d release.Decision) (release.Decision, error) {
	d.ID = "decision-" + d.Digest[:12]
	p.decisions[d.ID] = d
	return d, nil
}

func (p *expertPlatform) DecisionByID(_ context.Context, _ uint64, _, id string) (release.Decision, error) {
	d, ok := p.decisions[id]
	if !ok {
		return release.Decision{}, &release.Error{Code: release.ErrorDecisionNotFound}
	}
	return d, nil
}

func (p *expertPlatform) ReleaseByID(_ context.Context, _ uint64, _, id string) (release.Release, error) {
	if id == "" {
		id = p.head.ReleaseID
	}
	r, ok := p.releases[id]
	if !ok {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return r, nil
}

func (p *expertPlatform) Activate(_ context.Context, w release.ActivationWrite) (release.Release, error) {
	if w.Expected != p.head {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseConflict}
	}
	r := release.Release{
		ID: fmt.Sprintf("release-%d", p.head.Epoch+1), Epoch: p.head.Epoch + 1,
		BaseReleaseID: w.Expected.ReleaseID, CandidateID: w.CandidateID, Members: w.Members,
	}
	p.releases[r.ID], p.head = r, release.Head{ReleaseID: r.ID, Epoch: r.Epoch}
	return r, nil
}

type expertRecords map[string]expert.Revision

func (m expertRecords) CreateRevision(_ context.Context, r expert.Revision) error {
	m[r.ID] = r
	return nil
}

func (m expertRecords) RevisionByID(_ context.Context, tenant uint64, space, id string) (expert.Revision, error) {
	r, ok := m[id]
	if !ok || r.TenantID != tenant || r.SpaceID != space {
		return expert.Revision{}, &release.Error{Code: release.ErrorEvidenceNotFound}
	}
	return r, nil
}

type pdfSources struct{}

func (pdfSources) Resolve(_ context.Context, ref string) (bool, error) {
	return ref == expertSourceRef, nil
}

func (pdfSources) VerifyEvidence(_ context.Context, checks []release.EvidenceCheck) error {
	for _, c := range checks {
		if c.Evidence.Locator.Kind != "PDF_TEXT_SPAN" {
			return &release.Error{Code: release.ErrorEvidenceUnsupported, Detail: c.Path}
		}
	}
	return nil
}

type expertWorld struct {
	platform *expertPlatform
	records  expertRecords
	releases *release.Service
	experts  *expert.Service
	first    release.Release
}

func newExpertWorld(t *testing.T) *expertWorld {
	t.Helper()
	schemas := map[string][]byte{}
	for _, name := range []string{"candidate_bundle", "evidence", "locator"} {
		raw, err := os.ReadFile("../../contracts/" + name + ".schema.json")
		require.NoError(t, err)
		schemas[name] = raw
	}
	w := &expertWorld{
		platform: &expertPlatform{
			candidates: map[string]release.Candidate{}, bundles: map[string]release.Bundle{},
			decisions: map[string]release.Decision{}, releases: map[string]release.Release{},
		},
		records: expertRecords{},
	}
	w.releases = release.NewService(w.platform, expert.NewResolver(w.records, pdfSources{}), schemas,
		release.WithPublisher(w.platform), release.WithEvidenceVerifier(expert.NewVerifier(w.records, pdfSources{})))
	w.experts = expert.NewService(w.releases, w.records,
		expert.WithClock(func() time.Time { return time.Date(2026, 10, 22, 9, 0, 0, 0, time.UTC) }),
		expert.WithIDs(func() string { return fmt.Sprintf("rev-%d", len(w.records)+1) }))
	payload := map[string]any{
		"claim_id": "P/waiting", "logical_key": "P/waiting", "subject_ref": "P", "predicate": "waiting",
		"state": "present", "value": "90日", "origin": "SOURCE_SUPPORTED", "expert_lock": false,
		"evidence": []any{map[string]any{
			"source_ref": expertSourceRef, "file_sha256": strings.Repeat("ab", 32), "quote": "90日",
			"access_scope": "space", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1, "start": 0, "end": 3},
		}},
		"maintenance": map[string]any{"revision_no": 0, "changed_by": "compile", "first_release_id": "release-0"},
	}
	canonical, err := json.Marshal(payload)
	require.NoError(t, err)
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
		"members": []any{map[string]any{
			"kind": "claim", "logical_slug": "P/waiting", "payload": payload, "member_digest": digestOf(canonical),
			"evidence_refs": []string{expertSourceRef}, "access_scope": "space",
		}},
	})
	require.NoError(t, err)
	ctx, harness := context.Background(), release.Principal{TenantID: 7, Subject: "svc-harness"}
	c, err := w.releases.Receive(ctx, harness, "demo", raw)
	require.NoError(t, err)
	d, err := w.releases.Decide(ctx, harness, "demo", c.ID, release.DecisionInput{Outcome: "approve", Mode: "human"})
	require.NoError(t, err)
	w.first, err = w.releases.Activate(ctx, harness, "demo", c.ID, d.ID)
	require.NoError(t, err)
	return w
}

func (w *expertWorld) router(who identity, role types.TenantRole, experts *expert.Service) *gin.Engine {
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
	deps := enterprise.SessionDeps{
		Candidates: w.releases, Experts: experts, Spaces: spaceDirectory{7: {"demo"}, 8: {"other"}},
	}
	group := r.Group("/api/v1/enterprise")
	enterprise.MountSessionReads(group, deps)
	enterprise.MountSessionExpertEdits(group, deps)
	return r
}

func (w *expertWorld) body(t *testing.T, change map[string]any) []byte {
	t.Helper()
	in := map[string]any{
		"base_release_id": w.first.ID, "member_slug": "P/waiting",
		"base_member_digest": w.first.Members[0].MemberDigest,
		"state":              "present", "value": "180日", "reason": "备案条款第五条",
	}
	for key, value := range change {
		if value == nil {
			delete(in, key)
			continue
		}
		in[key] = value
	}
	raw, err := json.Marshal(in)
	require.NoError(t, err)
	return raw
}

func post(r http.Handler, path string, body []byte) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, path, bytes.NewReader(body)))
	return w
}

func (w *expertWorld) requireNothingWritten(t *testing.T) {
	t.Helper()
	require.Empty(t, w.records)
	require.Equal(t, release.Head{ReleaseID: w.first.ID, Epoch: w.first.Epoch}, w.platform.head)
}

func TestAnAdministratorEditPublishesAndItsCitationShowsTheRecord(t *testing.T) {
	w := newExpertWorld(t)
	r := w.router(browser, types.TenantRoleAdmin, w.experts)
	resp := post(r, expertEditsPath, w.body(t, nil))
	require.Equal(t, http.StatusCreated, resp.Code, resp.Body.String())
	got := data(t, resp.Body.Bytes())
	require.Equal(t, "release-2", got["release_id"])
	require.EqualValues(t, 2, got["epoch"])
	require.Equal(t, "rev-1", got["revision_record_id"])
	record := w.records["rev-1"]
	require.Equal(t, "web_user:user-1", record.Actor)
	require.Equal(t, string(types.TenantRoleAdmin), record.Role)

	cite := "/api/v1/enterprise/spaces/demo/view/releases/release-2/citation?" +
		url.Values{"member": {"P/waiting"}, "evidence": {"0"}}.Encode()
	resp = read(r, cite)
	require.Equal(t, http.StatusOK, resp.Code, resp.Body.String())
	got = data(t, resp.Body.Bytes())
	require.Equal(t, "expert_revision", got["kind"])
	require.Equal(t, "EXPERT_REVISION", got["origin"])
	require.Equal(t, "rev-1", got["revision_record_id"])
	require.Equal(t, "180日", got["quote"])
	require.Equal(t, record.Actor, got["actor"])
	require.Equal(t, "备案条款第五条", got["reason"])
	require.Equal(t, map[string]any{"state": "present", "value": "90日"}, got["before"])
	require.Equal(t, map[string]any{"state": "present", "value": "180日"}, got["after"])
	require.NotContains(t, got, "file", "an expert citation opens no file")

	// A record that no longer matches the published citation is never shown as its source.
	tampered := w.records["rev-1"]
	tampered.After.Value = "365日"
	w.records["rev-1"] = tampered
	resp = read(r, cite)
	require.Equal(t, http.StatusConflict, resp.Code, resp.Body.String())
	require.Equal(t, release.ErrorEvidenceMismatch, code(t, resp.Body.Bytes()))
}

func TestExpertEditsNeedAnAdministratorBrowserSessionInTheirSpace(t *testing.T) {
	w := newExpertWorld(t)
	for name, probe := range map[string]struct {
		who    identity
		role   types.TenantRole
		path   string
		status int
		code   string
	}{
		"contributor role": {browser, types.TenantRoleContributor, expertEditsPath, http.StatusForbidden, release.ErrorReleaseAccessDenied},
		"service key":      {identity{tenant: 7, principal: browser.principal, apiKey: true}, types.TenantRoleOwner, expertEditsPath, http.StatusForbidden, release.ErrorReleaseAccessDenied},
		"unknown Space":    {browser, types.TenantRoleAdmin, strings.Replace(expertEditsPath, "demo", "nope", 1), http.StatusNotFound, release.ErrorReleaseNotFound},
		"another tenant":   {browser, types.TenantRoleAdmin, strings.Replace(expertEditsPath, "demo", "other", 1), http.StatusNotFound, release.ErrorReleaseNotFound},
		"tenant 8 caller":  {identity{tenant: 8, principal: browser.principal}, types.TenantRoleOwner, expertEditsPath, http.StatusNotFound, release.ErrorReleaseNotFound},
	} {
		t.Run(name, func(t *testing.T) {
			resp := post(w.router(probe.who, probe.role, w.experts), probe.path, w.body(t, nil))
			require.Equal(t, probe.status, resp.Code, resp.Body.String())
			require.Equal(t, probe.code, code(t, resp.Body.Bytes()))
			w.requireNothingWritten(t)
		})
	}
}

func TestExpertEditFailuresAreTypedAndWriteNothing(t *testing.T) {
	w := newExpertWorld(t)
	r := w.router(browser, types.TenantRoleOwner, w.experts)
	for name, probe := range map[string]struct {
		body   []byte
		status int
		code   string
	}{
		"moved release":   {w.body(t, map[string]any{"base_release_id": "release-0"}), http.StatusConflict, expert.ErrorStale},
		"changed claim":   {w.body(t, map[string]any{"base_member_digest": strings.Repeat("0", 64)}), http.StatusConflict, expert.ErrorStale},
		"no reason":       {w.body(t, map[string]any{"reason": "  "}), http.StatusBadRequest, expert.ErrorInvalid},
		"unknown state":   {w.body(t, map[string]any{"state": "maybe"}), http.StatusBadRequest, expert.ErrorInvalid},
		"no change":       {w.body(t, map[string]any{"value": "90日"}), http.StatusBadRequest, expert.ErrorInvalid},
		"unknown member":  {w.body(t, map[string]any{"member_slug": "P/none"}), http.StatusNotFound, release.ErrorMemberNotFound},
		"unknown field":   {w.body(t, map[string]any{"origin": "SOURCE_SUPPORTED"}), http.StatusBadRequest, expert.ErrorInvalid},
		"case alias":      {w.body(t, map[string]any{"Reason": "x"}), http.StatusBadRequest, expert.ErrorInvalid},
		"not JSON object": {[]byte(`["edit"]`), http.StatusBadRequest, expert.ErrorInvalid},
	} {
		t.Run(name, func(t *testing.T) {
			resp := post(r, expertEditsPath, probe.body)
			require.Equal(t, probe.status, resp.Code, resp.Body.String())
			require.Equal(t, probe.code, code(t, resp.Body.Bytes()))
			w.requireNothingWritten(t)
		})
	}
}

func TestExpertEditsAreUnavailableWithoutTheService(t *testing.T) {
	w := newExpertWorld(t)
	resp := post(w.router(browser, types.TenantRoleOwner, nil), expertEditsPath, w.body(t, nil))
	require.Equal(t, http.StatusServiceUnavailable, resp.Code, resp.Body.String())
	w.requireNothingWritten(t)
}
