package handler

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type automatedReleasePortStub struct {
	calls         int
	id            string
	first, second []byte
	principal     types.WikiReleasePrincipal
	scope         types.WikiReleaseScope
	err           error
	nilResult     bool
}

func (s *automatedReleasePortStub) CreateBatchConceptDraftTransferAutomated830G3(ctx context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope, id string, raw json.RawMessage) (*types.WikiReleasePreparation, error) {
	return s.CreateBatchConceptDraftAutomated830G3(ctx, p, scope, id, raw)
}

func (s *automatedReleasePortStub) CreateBatchConceptDraftAutomated830G3(_ context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope, id string, raw json.RawMessage) (*types.WikiReleasePreparation, error) {
	s.calls++
	s.id = id
	s.first = append([]byte(nil), raw...)
	s.principal = p
	s.scope = scope
	if s.nilResult {
		return nil, s.err
	}
	return &types.WikiReleasePreparation{ID: id, WikiReleaseScope: scope, Status: types.WikiReleasePreparationDraft, Manifest: json.RawMessage(`{"private_model_value":"unverified"}`), Members: []types.WikiReleaseMemberSnapshot{{LogicalSlug: "private-audit", Content: "private_model_value"}}}, s.err
}
func (s *automatedReleasePortStub) ReviewDraftAutomated(_ context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope, id string, raw []byte) (*types.WikiReleasePreparation, error) {
	s.calls++
	s.id = id
	s.first = append([]byte(nil), raw...)
	s.principal = p
	s.scope = scope
	if s.nilResult {
		return nil, s.err
	}
	return &types.WikiReleasePreparation{ID: id, WikiReleaseScope: scope, Status: types.WikiReleasePreparationReady, Manifest: json.RawMessage(`{"private_model_value":"unverified"}`), Members: []types.WikiReleaseMemberSnapshot{{LogicalSlug: "private-audit", Content: "private_model_value"}}}, s.err
}
func (s *automatedReleasePortStub) ActivateAutomated(_ context.Context, p types.WikiReleasePrincipal, d, a []byte) (*types.WikiReleaseReceipt, error) {
	s.calls++
	s.first = append([]byte(nil), d...)
	s.second = append([]byte(nil), a...)
	s.principal = p
	if s.nilResult {
		return nil, s.err
	}
	return &types.WikiReleaseReceipt{ReleaseID: "release-1"}, s.err
}

const automatedReleaseTestBase = "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform"

func automatedReleaseWire(t *testing.T) ([]byte, []byte) {
	t.Helper()
	d := &service.SystemPolicyDecisionReceiptV1{Version: "1", Decision: "approve", Mode: service.SystemPolicyIsolatedMode, PrincipalID: "api_tenant:42", APIKeyID: 9, WikiReleaseScope: types.WikiReleaseScope{TenantID: 42, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"}, PolicyID: "test", PolicyVersion: "1", PolicyDigest: strings.Repeat("a", 64), Capabilities: []string{"activate", "create-draft", "review"}, PreparationID: "draft-1", DraftPreparationDigest: strings.Repeat("b", 64), CandidateDigest: strings.Repeat("c", 64), ManifestDigest: strings.Repeat("d", 64), ReadyReceiptDigest: strings.Repeat("e", 64), InnerReviewPolicyID: strings.Repeat("f", 64), ExpectedReleaseID: "parent-1", ExpectedActivationEpoch: 9, IssuedAt: 1000, ExpiresAt: 2000, Nonce: "nonce-1", SignerKeyID: "system-key", Signature: "opaque-system-signature"}
	decision, err := service.CanonicalSystemPolicyDecisionReceiptV1(d, true)
	require.NoError(t, err)
	a := &types.PublishAuthorizationV0{Version: "0", Action: "activate", PreparationID: d.PreparationID, CandidateDigest: d.CandidateDigest, ManifestDigest: d.ManifestDigest, ReadyReceiptDigest: d.ReadyReceiptDigest, ReviewDecisionDigest: strings.Repeat("0", 64), ReviewPolicyID: d.InnerReviewPolicyID, TenantID: 42, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1", ExpectedReleaseID: "parent-1", ExpectedActivationEpoch: 9, ExpiresAt: 2000, Nonce: d.Nonce, SignerKeyID: "publish-key", Signature: "opaque-publish-signature"}
	auth, err := service.CanonicalPublishAuthorizationV0(a, true)
	require.NoError(t, err)
	return decision, auth
}

func automatedReleaseEngine(stub *automatedReleasePortStub, change func(context.Context) context.Context, seal bool) *gin.Engine {
	gin.SetMode(gin.TestMode)
	h := NewG3PlatformReleaseHandler(NewWikiReleaseHandler(nil), stub, stub)
	engine := gin.New()
	engine.Use(func(c *gin.Context) {
		terminal := types.Principal{Type: types.PrincipalAPITenant, ID: "42"}
		scope := types.WikiReleaseScope{TenantID: 42, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(42))
		ctx = types.WithPrincipal(ctx, terminal)
		ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 9, KnowledgeBaseIDs: types.StringArray{"raw-1", "wiki-1"}})
		if change != nil {
			ctx = change(ctx)
		}
		terminal, _ = types.PrincipalFromContext(ctx)
		key, _ := types.TenantAPIKeyScopeFromContext(ctx)
		if seal {
			ctx = service.SealWikiReleaseAccess(ctx, types.WikiReleasePrincipal{ID: terminal.StorageID(), TenantID: 42, SpaceID: "space-1", APIKeyKnowledgeBaseIDs: append([]string(nil), key.KnowledgeBaseIDs...)}, scope)
		}
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(42))
		c.Set(types.PrincipalContextKey.String(), terminal)
		c.Next()
	})
	base := "/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform"
	engine.POST(base+"/preparations", h.CreatePreparation)
	engine.POST(base+"/preparations/:preparation_id/review", h.ReviewPreparation)
	engine.POST(base+"/activate", h.Activate)
	return engine
}
func releaseRequest(e *gin.Engine, path, body string) *httptest.ResponseRecorder {
	r := httptest.NewRecorder()
	q := httptest.NewRequest(http.MethodPost, automatedReleaseTestBase+path, strings.NewReader(body))
	q.Header.Set("Content-Type", "application/json")
	e.ServeHTTP(r, q)
	return r
}

func TestG3PlatformReleaseHandlerPreservesSignedWireAndScope(t *testing.T) {
	s := &automatedReleasePortStub{}
	e := automatedReleaseEngine(s, nil, true)
	bundle := `{"contract":"fixture","payload":{"quote":"原文\\n第二行"}}`
	r := releaseRequest(e, "/preparations", `{"preparation_id":"draft-1","bundle":`+bundle+`}`)
	require.Equal(t, http.StatusCreated, r.Code, r.Body.String())
	require.Equal(t, []byte(bundle), s.first)
	require.Equal(t, "draft-1", s.id)
	require.Equal(t, "api_tenant:42", s.principal.ID)
	require.Equal(t, "raw-1", s.scope.RawKBID)
	d, a := automatedReleaseWire(t)
	r = releaseRequest(e, "/preparations/draft-1/review", string(d))
	require.Equal(t, http.StatusOK, r.Code, r.Body.String())
	require.Equal(t, d, s.first)
	r = releaseRequest(e, "/activate", `{"decision":`+string(d)+`,"authorization":`+string(a)+`}`)
	require.Equal(t, http.StatusOK, r.Code, r.Body.String())
	require.Equal(t, d, s.first)
	require.Equal(t, a, s.second)
	require.Equal(t, 3, s.calls)
}

func TestG3PlatformReleaseHandlerAcceptsTransferExclusively(t *testing.T) {
	s := &automatedReleasePortStub{}
	e := automatedReleaseEngine(s, nil, true)
	transfer := `{"contract":"g3-platform-candidate-transfer.830.v1","payload":"exact"}`
	r := releaseRequest(e, "/preparations", `{"preparation_id":"draft-1","transfer":`+transfer+`}`)
	require.Equal(t, http.StatusCreated, r.Code, r.Body.String())
	require.Equal(t, []byte(transfer), s.first)
	r = releaseRequest(e, "/preparations", `{"preparation_id":"draft-1","bundle":{},"transfer":`+transfer+`}`)
	require.Equal(t, http.StatusBadRequest, r.Code)
	require.Equal(t, 1, s.calls)
}

func TestG3PlatformReleaseHandlerRejectsAmbiguousBodiesBeforePort(t *testing.T) {
	d, a := automatedReleaseWire(t)
	activation := `{"decision":` + string(d) + `,"authorization":` + string(a) + `}`
	cases := map[string]struct{ path, body string }{
		"nested duplicate":          {"/preparations", `{"preparation_id":"a","bundle":{"nested":{"value":1,"value":2}}}`},
		"duplicate envelope":        {"/preparations", `{"preparation_id":"a","preparation_id":"b","bundle":{}}`},
		"unknown envelope":          {"/preparations", `{"preparation_id":"a","bundle":{},"metadata":{}}`},
		"missing bundle":            {"/preparations", `{"preparation_id":"a"}`},
		"null bundle":               {"/preparations", `{"preparation_id":"a","bundle":null}`},
		"array bundle":              {"/preparations", `{"preparation_id":"a","bundle":[]}`},
		"trailing":                  {"/preparations", `{"preparation_id":"a","bundle":{}} {}`},
		"empty id":                  {"/preparations", `{"preparation_id":" ","bundle":{}}`},
		"review duplicate":          {"/preparations/draft-1/review", strings.Replace(string(d), "{", `{"version":"1",`, 1)},
		"review unknown":            {"/preparations/draft-1/review", strings.Replace(string(d), "{", `{"unexpected":1,`, 1)},
		"review whitespace":         {"/preparations/draft-1/review", " " + string(d)},
		"review route mismatch":     {"/preparations/other/review", string(d)},
		"review scope mismatch":     {"/preparations/draft-1/review", strings.Replace(string(d), "wiki-1", "wiki-2", 1)},
		"activate duplicate":        {"/activate", strings.Replace(activation, "{", `{"authorization":{},`, 1)},
		"activate unknown":          {"/activate", strings.Replace(activation, "{", `{"candidate":{},`, 1)},
		"activate null":             {"/activate", `{"decision":null,"authorization":` + string(a) + `}`},
		"activate wrong auth scope": {"/activate", strings.Replace(activation, `"space_id":"space-1"}`, `"space_id":"other"}`, 1)},
	}
	// The final occurrence belongs to authorization; changing it must fail at the URL boundary.
	badAuth := strings.Replace(string(a), `"space_id":"space-1"`, `"space_id":"other"`, 1)
	cases["activate wrong auth scope"] = struct{ path, body string }{"/activate", `{"decision":` + string(d) + `,"authorization":` + badAuth + `}`}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			s := &automatedReleasePortStub{}
			r := releaseRequest(automatedReleaseEngine(s, nil, true), tc.path, tc.body)
			require.Equal(t, http.StatusBadRequest, r.Code, r.Body.String())
			require.Zero(t, s.calls)
		})
	}
}

func TestG3PlatformReleaseHandlerRejectsMissingSealAndNonMachine(t *testing.T) {
	cases := map[string]func(context.Context) context.Context{
		"human": func(c context.Context) context.Context {
			return types.WithPrincipal(c, types.Principal{Type: types.PrincipalWebUser, ID: "42"})
		},
		"full": func(c context.Context) context.Context {
			return types.WithTenantAPIKeyScope(c, types.TenantAPIKeyScope{KeyID: 9, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"raw-1", "wiki-1"}})
		},
		"unrestricted": func(c context.Context) context.Context {
			return types.WithTenantAPIKeyScope(c, types.TenantAPIKeyScope{KeyID: 9})
		},
		"third KB": func(c context.Context) context.Context {
			return types.WithTenantAPIKeyScope(c, types.TenantAPIKeyScope{KeyID: 9, KnowledgeBaseIDs: types.StringArray{"raw-1", "wiki-1", "extra"}})
		},
		"missing key": func(c context.Context) context.Context {
			return types.WithTenantAPIKeyScope(c, types.TenantAPIKeyScope{KnowledgeBaseIDs: types.StringArray{"raw-1", "wiki-1"}})
		},
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			s := &automatedReleasePortStub{}
			r := releaseRequest(automatedReleaseEngine(s, change, true), "/preparations", `{"preparation_id":"a","bundle":{}}`)
			require.Equal(t, http.StatusForbidden, r.Code, r.Body.String())
			require.Zero(t, s.calls)
		})
	}
	s := &automatedReleasePortStub{}
	r := releaseRequest(automatedReleaseEngine(s, nil, false), "/preparations", `{"preparation_id":"a","bundle":{}}`)
	require.Equal(t, http.StatusForbidden, r.Code)
	require.Zero(t, s.calls)
}

func TestG3PlatformReleaseHandlerBoundsBodyAndSanitizesErrors(t *testing.T) {
	s := &automatedReleasePortStub{}
	e := automatedReleaseEngine(s, nil, true)
	q := httptest.NewRequest(http.MethodPost, automatedReleaseTestBase+"/preparations", strings.NewReader(`{}`))
	q.ContentLength = maxSchemaWikiRequestBytes + 1
	r := httptest.NewRecorder()
	e.ServeHTTP(r, q)
	require.Equal(t, http.StatusRequestEntityTooLarge, r.Code)
	require.Zero(t, s.calls)
	s.err = errors.New("private-key=secret /private/private-material.pdf")
	r = releaseRequest(e, "/preparations", `{"preparation_id":"a","bundle":{}}`)
	require.Equal(t, http.StatusInternalServerError, r.Code)
	require.NotContains(t, r.Body.String(), "private-key")
	require.NotContains(t, r.Body.String(), "private-material")
	s.err = nil
	s.nilResult = true
	r = releaseRequest(e, "/preparations", `{"preparation_id":"a","bundle":{}}`)
	require.Equal(t, http.StatusServiceUnavailable, r.Code)
}

func TestG3PlatformReleaseHandlerReturnsOnlyPreparationMetadata(t *testing.T) {
	d, _ := automatedReleaseWire(t)
	for _, tc := range []struct {
		path, body string
		status     int
	}{
		{"/preparations", `{"preparation_id":"draft-1","bundle":{}}`, http.StatusCreated},
		{"/preparations/draft-1/review", string(d), http.StatusOK},
	} {
		t.Run(tc.path, func(t *testing.T) {
			s := &automatedReleasePortStub{}
			r := releaseRequest(automatedReleaseEngine(s, nil, true), tc.path, tc.body)
			require.Equal(t, tc.status, r.Code, r.Body.String())
			var wire struct {
				Data map[string]json.RawMessage `json:"data"`
			}
			require.NoError(t, json.Unmarshal(r.Body.Bytes(), &wire))
			require.NotContains(t, wire.Data, "manifest")
			require.NotContains(t, wire.Data, "members")
			require.NotContains(t, r.Body.String(), "private_model_value")
			for _, name := range []string{"preparation_id", "status", "tenant_id", "space_id", "raw_kb_id", "wiki_kb_id", "preparation_digest", "candidate_digest", "manifest_digest", "ready_receipt_digest", "review_decision_digest", "review_policy_id", "expected_release_id", "expected_activation_epoch", "created_at"} {
				require.Contains(t, wire.Data, name)
			}
			require.Len(t, wire.Data, 15)
		})
	}
}
