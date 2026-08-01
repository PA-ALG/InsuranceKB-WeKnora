package handler_test

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sort"
	"strings"
	"testing"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/router"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestWikiReleaseFalsificationHandlerIsExplicitlyConstructed(t *testing.T) {
	releaseHandler := handler.NewWikiReleaseHandler(nil)
	require.NotNil(t, releaseHandler)
}

type wikiReleaseHandlerFixture struct {
	handler         *handler.WikiReleaseHandler
	service         *service.WikiReleaseService
	repository      *wikirepository.WikiReleaseRepository
	scope           types.WikiReleaseScope
	privateKey      ed25519.PrivateKey
	humanPrivateKey ed25519.PrivateKey
	now             int64
}

func newWikiReleaseHandlerFixture(t *testing.T) *wikiReleaseHandlerFixture {
	t.Helper()
	dbName := strings.NewReplacer("/", "-", " ", "-").Replace(t.Name())
	db, err := gorm.Open(sqlite.Open("file:"+dbName+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleasePreparation{},
		&types.WikiRelease{},
		&types.WikiReleaseMember{},
		&types.WikiReleaseHead{},
		&types.WikiReleaseReceipt{},
	))
	repository := wikirepository.NewWikiReleaseRepository(db)
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x58}, ed25519.SeedSize))
	humanPrivateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x59}, ed25519.SeedSize))
	id := 0
	now := int64(1_000)
	releaseService := service.NewWikiReleaseService(
		repository,
		service.NewContextWikiReleaseAccessVerifier(),
		service.NewEd25519WikiReleaseAuthorizationVerifier(map[string]ed25519.PublicKey{
			"handler-test": privateKey.Public().(ed25519.PublicKey),
		}),
		service.WikiReleaseServiceOptions{
			Now: func() time.Time { return time.Unix(now, 0).UTC() },
			HumanDecisionVerifier: service.NewEd25519HumanBatchDecisionVerifier(
				map[string]ed25519.PublicKey{
					"handler-human": humanPrivateKey.Public().(ed25519.PublicKey),
				},
			),
			NewID: func(kind string) string {
				id++
				return fmt.Sprintf("%s-%d", kind, id)
			},
		},
	)
	return &wikiReleaseHandlerFixture{
		handler:    handler.NewWikiReleaseHandler(releaseService),
		service:    releaseService,
		repository: repository,
		scope: types.WikiReleaseScope{
			TenantID: 42,
			SpaceID:  "space-1",
			RawKBID:  "raw-1",
			WikiKBID: "wiki-1",
		},
		privateKey:      privateKey,
		humanPrivateKey: humanPrivateKey,
		now:             now,
	}
}

func wikiReleaseAuthContext(scope types.WikiReleaseScope, extraKBIDs ...string) gin.HandlerFunc {
	return func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalAPITenant, ID: "handler-principal"}
		c.Set(types.TenantIDContextKey.String(), scope.TenantID)
		c.Set(types.PrincipalContextKey.String(), principal)
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, scope.TenantID)
		ctx = types.WithPrincipal(ctx, principal)
		kbIDs := append(types.StringArray{scope.RawKBID, scope.WikiKBID}, extraKBIDs...)
		ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{
			KeyID:            7,
			ScopeType:        types.APIKeyScopeTenant,
			KnowledgeBaseIDs: kbIDs,
		})
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	}
}

func registerWikiReleaseHandlerRoutes(
	engine *gin.Engine,
	releaseHandler *handler.WikiReleaseHandler,
) {
	const base = "/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id"
	access := func(endpoint gin.HandlerFunc) []gin.HandlerFunc {
		return []gin.HandlerFunc{
			setWikiReleaseKBAccess("kb_id"),
			releaseHandler.RecordWikiAccessEvidence(),
			setWikiReleaseKBAccess("raw_kb_id"),
			releaseHandler.RecordRawAccessEvidence(),
			releaseHandler.SealAccess(),
			endpoint,
		}
	}
	engine.POST(base+"/preparations", access(releaseHandler.Prepare)...)
	engine.POST(base+"/activations", access(releaseHandler.Activate)...)
	engine.GET(base+"/current", access(releaseHandler.Current)...)
	engine.GET(base+"/releases/:release_id/pages/:logical_slug", access(releaseHandler.PinnedPage)...)
	engine.GET(base+"/releases/:release_id/payloads/:logical_slug", access(releaseHandler.PinnedPayload)...)
	engine.GET(base+"/releases/:release_id/search", access(releaseHandler.MinimalSearch)...)
}

func setWikiReleaseKBAccess(param string) gin.HandlerFunc {
	return func(c *gin.Context) {
		kbID := c.Param(param)
		c.Set(middleware.KBAccessContextKey, &middleware.KBAccess{
			KnowledgeBase:     &types.KnowledgeBase{ID: kbID},
			EffectiveTenantID: 42,
			Permission:        types.OrgRoleAdmin,
		})
		c.Next()
	}
}

func performJSON(
	t *testing.T,
	engine http.Handler,
	method string,
	path string,
	body any,
) *httptest.ResponseRecorder {
	t.Helper()
	var raw []byte
	var err error
	if body != nil {
		raw, err = json.Marshal(body)
		require.NoError(t, err)
	}
	request := httptest.NewRequest(method, path, bytes.NewReader(raw))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	engine.ServeHTTP(recorder, request)
	return recorder
}

func decodeWikiReleaseData[T any](t *testing.T, recorder *httptest.ResponseRecorder) T {
	t.Helper()
	var response struct {
		Success bool            `json:"success"`
		Data    json.RawMessage `json:"data"`
	}
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	require.True(t, response.Success, recorder.Body.String())
	var data T
	require.NoError(t, json.Unmarshal(response.Data, &data))
	return data
}

func wikiReleasePreparationRequest() map[string]any {
	return map[string]any{
		"preparation_id":            "preparation-r0",
		"candidate_digest":          "candidate-r0",
		"ready_receipt_digest":      "ready-r0",
		"review_decision_digest":    "review-r0",
		"review_policy_id":          "policy-1",
		"expected_release_id":       "",
		"expected_activation_epoch": 0,
		"members":                   wikiReleaseHandlerMembers(0),
	}
}

func wikiReleaseHandlerMembers(version int) []types.WikiReleaseMemberSnapshot {
	return []types.WikiReleaseMemberSnapshot{{
		LogicalSlug: "a", RevisionID: fmt.Sprintf("a%d", version),
		MemberDigest: fmt.Sprintf("digest-a%d", version), Title: "A",
		Content: fmt.Sprintf("A%d", version),
		Payload: json.RawMessage(fmt.Sprintf(`{"slug":"a","v":%d}`, version)),
	}}
}

func wikiReleaseHash(value string) string {
	return fmt.Sprintf("%x", sha256.Sum256([]byte(value)))
}

func wikiReleaseReviewedPreparationRequest(
	t *testing.T,
	fixture *wikiReleaseHandlerFixture,
	preparationID string,
	nonce string,
	expectedReleaseID string,
	expectedEpoch uint64,
	members []types.WikiReleaseMemberSnapshot,
) (map[string]any, []byte) {
	t.Helper()
	decision := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve",
		PrincipalID: types.Principal{
			Type: types.PrincipalAPITenant, ID: "handler-principal",
		}.StorageID(),
		WikiReleaseScope: fixture.scope,
		CandidateHash:    wikiReleaseHash(preparationID + "-candidate"),
		HumanBatchHash:   wikiReleaseHash(preparationID + "-batch"),
		ReviewPolicyHash: wikiReleaseHash("handler-review-policy"),
		IssuedAt:         fixture.now, ExpiresAt: fixture.now + 1_000,
		Nonce: nonce, SignerKeyID: "handler-human",
	}
	unsigned, err := service.CanonicalHumanBatchDecisionReceiptV1(decision, false)
	require.NoError(t, err)
	decision.Signature = service.EncodeWikiReleaseSignature(
		ed25519.Sign(fixture.humanPrivateKey, unsigned),
	)
	decisionRaw, err := service.CanonicalHumanBatchDecisionReceiptV1(decision, true)
	require.NoError(t, err)
	return map[string]any{
		"preparation_id": preparationID, "candidate_digest": decision.CandidateHash,
		"ready_receipt_digest":      decision.HumanBatchHash,
		"review_decision_digest":    wikiReleaseHash(string(decisionRaw)),
		"review_policy_id":          decision.ReviewPolicyHash,
		"expected_release_id":       expectedReleaseID,
		"expected_activation_epoch": expectedEpoch,
		"members":                   members,
	}, decisionRaw
}

func wikiReleaseReviewedActivationBody(
	decisionRaw []byte,
	authorizationRaw []byte,
) map[string]json.RawMessage {
	return map[string]json.RawMessage{
		"human_decision":        decisionRaw,
		"publish_authorization": authorizationRaw,
	}
}

func signWikiReleaseHandlerAuthorization(
	t *testing.T,
	privateKey ed25519.PrivateKey,
	preparation types.WikiReleasePreparation,
	nonceValues ...string,
) []byte {
	t.Helper()
	nonce := "nonce-r0"
	if len(nonceValues) == 1 {
		nonce = nonceValues[0]
	}
	authorization := &types.PublishAuthorizationV0{
		Version:                 "0",
		Action:                  "activate",
		PreparationID:           preparation.ID,
		CandidateDigest:         preparation.CandidateDigest,
		ManifestDigest:          preparation.ManifestDigest,
		ReadyReceiptDigest:      preparation.ReadyReceiptDigest,
		ReviewDecisionDigest:    preparation.ReviewDecisionDigest,
		ReviewPolicyID:          preparation.ReviewPolicyID,
		TenantID:                preparation.TenantID,
		SpaceID:                 preparation.SpaceID,
		RawKBID:                 preparation.RawKBID,
		WikiKBID:                preparation.WikiKBID,
		ExpectedReleaseID:       preparation.ExpectedReleaseID,
		ExpectedActivationEpoch: preparation.ExpectedActivationEpoch,
		ExpiresAt:               2_000,
		Nonce:                   nonce,
		SignerKeyID:             "handler-test",
	}
	signingBytes, err := service.CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	authorization.Signature = service.EncodeWikiReleaseSignature(ed25519.Sign(privateKey, signingBytes))
	raw, err := service.CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	return raw
}

func TestWikiReleaseFalsificationHandlerPrepareActivateAndPinnedReads(t *testing.T) {
	gin.SetMode(gin.TestMode)
	fixture := newWikiReleaseHandlerFixture(t)
	engine := gin.New()
	engine.Use(wikiReleaseAuthContext(fixture.scope))
	registerWikiReleaseHandlerRoutes(engine, fixture.handler)

	base := "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1"
	preparationRequest, decisionRaw := wikiReleaseReviewedPreparationRequest(
		t, fixture, "preparation-r0", "nonce-r0", "", 0, wikiReleaseHandlerMembers(0),
	)
	recorder := performJSON(t, engine, http.MethodPost, base+"/preparations", preparationRequest)
	require.Equal(t, http.StatusCreated, recorder.Code, recorder.Body.String())
	preparation := decodeWikiReleaseData[types.WikiReleasePreparation](t, recorder)
	require.Equal(t, fixture.scope, preparation.WikiReleaseScope)

	rawAuthorization := signWikiReleaseHandlerAuthorization(
		t, fixture.privateKey, preparation, "nonce-r0",
	)
	recorder = performJSON(
		t, engine, http.MethodPost, base+"/activations",
		wikiReleaseReviewedActivationBody(decisionRaw, rawAuthorization),
	)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	receipt := decodeWikiReleaseData[types.WikiReleaseReceipt](t, recorder)

	recorder = performJSON(t, engine, http.MethodGet, base+"/current", nil)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	current := decodeWikiReleaseData[types.WikiReleaseCurrent](t, recorder)
	require.Equal(t, receipt.ReleaseID, current.ReleaseID)

	recorder = performJSON(
		t,
		engine,
		http.MethodGet,
		base+"/releases/"+receipt.ReleaseID+"/pages/a",
		nil,
	)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	page := decodeWikiReleaseData[types.WikiReleaseMemberSnapshot](t, recorder)
	require.Equal(t, "A0", page.Content)

	recorder = performJSON(
		t,
		engine,
		http.MethodGet,
		base+"/releases/"+receipt.ReleaseID+"/payloads/a",
		nil,
	)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	payload := decodeWikiReleaseData[json.RawMessage](t, recorder)
	require.JSONEq(t, `{"slug":"a","v":0}`, string(payload))

	recorder = performJSON(
		t,
		engine,
		http.MethodGet,
		base+"/releases/"+receipt.ReleaseID+"/search?q=A0",
		nil,
	)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	search := decodeWikiReleaseData[[]types.WikiReleaseMemberSnapshot](t, recorder)
	require.Len(t, search, 1)
	require.Equal(t, "a", search[0].LogicalSlug)
}

func TestWikiReleasePR2HandlerRejectsLegacyActivationWithoutHumanReceipt(t *testing.T) {
	gin.SetMode(gin.TestMode)
	fixture := newWikiReleaseHandlerFixture(t)
	engine := gin.New()
	engine.Use(wikiReleaseAuthContext(fixture.scope))
	registerWikiReleaseHandlerRoutes(engine, fixture.handler)
	base := "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1"
	preparationRequest, _ := wikiReleaseReviewedPreparationRequest(
		t, fixture, "preparation-legacy", "nonce-legacy", "", 0, wikiReleaseHandlerMembers(0),
	)
	recorder := performJSON(t, engine, http.MethodPost, base+"/preparations", preparationRequest)
	require.Equal(t, http.StatusCreated, recorder.Code, recorder.Body.String())
	preparation := decodeWikiReleaseData[types.WikiReleasePreparation](t, recorder)
	before, err := fixture.repository.CountState(context.Background())
	require.NoError(t, err)

	rawAuthorization := signWikiReleaseHandlerAuthorization(
		t, fixture.privateKey, preparation, "nonce-legacy",
	)
	for _, testCase := range []struct {
		name string
		body []byte
	}{
		{name: "legacy raw authorization", body: rawAuthorization},
		{name: "missing human receipt", body: mustMarshalWikiReleaseHandler(t, map[string]any{
			"publish_authorization": json.RawMessage(rawAuthorization),
		})},
		{name: "self-reported review digest", body: mustMarshalWikiReleaseHandler(t, map[string]any{
			"human_decision":        json.RawMessage(`{"review_decision_digest":"self-reported"}`),
			"publish_authorization": json.RawMessage(rawAuthorization),
		})},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			request := httptest.NewRequest(
				http.MethodPost, base+"/activations", bytes.NewReader(testCase.body),
			)
			request.Header.Set("Content-Type", "application/json")
			recorder = httptest.NewRecorder()
			engine.ServeHTTP(recorder, request)
			require.Equal(t, http.StatusBadRequest, recorder.Code, recorder.Body.String())
			after, err := fixture.repository.CountState(context.Background())
			require.NoError(t, err)
			require.Equal(t, before, after)
		})
	}
}

func mustMarshalWikiReleaseHandler(t *testing.T, value any) []byte {
	t.Helper()
	raw, err := json.Marshal(value)
	require.NoError(t, err)
	return raw
}

func TestWikiReleasePR2HandlerCannotSelectHistoricalRelease(t *testing.T) {
	gin.SetMode(gin.TestMode)
	fixture := newWikiReleaseHandlerFixture(t)
	engine := gin.New()
	engine.Use(wikiReleaseAuthContext(fixture.scope))
	registerWikiReleaseHandlerRoutes(engine, fixture.handler)
	base := "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1"

	activate := func(
		preparationID string,
		nonce string,
		expectedReleaseID string,
		expectedEpoch uint64,
		version int,
	) *types.WikiReleaseReceipt {
		t.Helper()
		preparationRequest, decisionRaw := wikiReleaseReviewedPreparationRequest(
			t, fixture, preparationID, nonce, expectedReleaseID, expectedEpoch,
			wikiReleaseHandlerMembers(version),
		)
		recorder := performJSON(
			t, engine, http.MethodPost, base+"/preparations", preparationRequest,
		)
		require.Equal(t, http.StatusCreated, recorder.Code, recorder.Body.String())
		preparation := decodeWikiReleaseData[types.WikiReleasePreparation](t, recorder)
		authorization := signWikiReleaseHandlerAuthorization(t, fixture.privateKey, preparation, nonce)
		recorder = performJSON(
			t, engine, http.MethodPost, base+"/activations",
			wikiReleaseReviewedActivationBody(decisionRaw, authorization),
		)
		require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
		receipt := decodeWikiReleaseData[types.WikiReleaseReceipt](t, recorder)
		return &receipt
	}
	r0 := activate("preparation-r0", "nonce-r0", "", 0, 0)
	_ = activate("preparation-r1", "nonce-r1", r0.ReleaseID, r0.ActivationEpoch, 1)

	for _, suffix := range []string{"/pages/a", "/payloads/a", "/search?q=A0"} {
		recorder := performJSON(
			t, engine, http.MethodGet, base+"/releases/"+r0.ReleaseID+suffix, nil,
		)
		require.Equal(t, http.StatusConflict, recorder.Code, recorder.Body.String())
		require.NotContains(t, recorder.Body.String(), "A0")
	}
}

func TestWikiReleaseFalsificationHandlerFailsClosedWithoutExactProof(t *testing.T) {
	gin.SetMode(gin.TestMode)
	fixture := newWikiReleaseHandlerFixture(t)
	base := "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1"

	t.Run("missing proof", func(t *testing.T) {
		engine := gin.New()
		engine.Use(wikiReleaseAuthContext(fixture.scope))
		engine.GET(
			"/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/current",
			fixture.handler.Current,
		)
		recorder := performJSON(t, engine, http.MethodGet, base+"/current", nil)
		require.Equal(t, http.StatusForbidden, recorder.Code, recorder.Body.String())
	})

	t.Run("raw path outside authenticated API key scope", func(t *testing.T) {
		engine := gin.New()
		engine.Use(wikiReleaseAuthContext(fixture.scope))
		registerWikiReleaseHandlerRoutes(engine, fixture.handler)
		recorder := performJSON(
			t,
			engine,
			http.MethodGet,
			"/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-2/current",
			nil,
		)
		require.Equal(t, http.StatusForbidden, recorder.Code, recorder.Body.String())
	})
}

func TestWikiReleaseFalsificationManagedMutationGuard(t *testing.T) {
	gin.SetMode(gin.TestMode)
	fixture := newWikiReleaseHandlerFixture(t)
	releaseEngine := gin.New()
	releaseEngine.Use(wikiReleaseAuthContext(fixture.scope, "wiki-2"))
	registerWikiReleaseHandlerRoutes(releaseEngine, fixture.handler)
	base := "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1"

	preparationRequest, decisionRaw := wikiReleaseReviewedPreparationRequest(
		t, fixture, "preparation-managed", "nonce-managed", "", 0,
		wikiReleaseHandlerMembers(0),
	)
	recorder := performJSON(
		t, releaseEngine, http.MethodPost, base+"/preparations", preparationRequest,
	)
	require.Equal(t, http.StatusCreated, recorder.Code, recorder.Body.String())
	preparation := decodeWikiReleaseData[types.WikiReleasePreparation](t, recorder)
	rawAuthorization := signWikiReleaseHandlerAuthorization(
		t, fixture.privateKey, preparation, "nonce-managed",
	)
	recorder = performJSON(
		t, releaseEngine, http.MethodPost, base+"/activations",
		wikiReleaseReviewedActivationBody(decisionRaw, rawAuthorization),
	)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())

	mutationEngine := gin.New()
	mutationEngine.Use(wikiReleaseAuthContext(fixture.scope, "wiki-2"))
	legacyCalls := 0
	legacy := func(c *gin.Context) {
		legacyCalls++
		c.Status(http.StatusNoContent)
	}
	mutationEngine.PUT(
		"/knowledgebase/:kb_id/wiki/pages/*slug",
		fixture.handler.RejectManagedWikiWrite(),
		legacy,
	)
	mutationEngine.DELETE(
		"/knowledgebase/:kb_id/wiki/pages/*slug",
		fixture.handler.RejectManagedWikiWrite(),
		legacy,
	)

	for _, method := range []string{http.MethodPut, http.MethodDelete} {
		recorder = performJSON(t, mutationEngine, method, "/knowledgebase/wiki-1/wiki/pages/a", nil)
		require.Equal(t, http.StatusConflict, recorder.Code, recorder.Body.String())
	}
	require.Zero(t, legacyCalls)

	for _, method := range []string{http.MethodPut, http.MethodDelete} {
		recorder = performJSON(t, mutationEngine, method, "/knowledgebase/wiki-2/wiki/pages/a", nil)
		require.Equal(t, http.StatusNoContent, recorder.Code, recorder.Body.String())
	}
	require.Equal(t, 2, legacyCalls)
}

func TestWikiReleaseFalsificationProductionRouterInventoryAndAuth(t *testing.T) {
	gin.SetMode(gin.TestMode)
	engine := router.NewRouter(router.RouterParams{
		Config:             &config.Config{},
		WikiReleaseHandler: handler.NewWikiReleaseHandler(nil),
	})

	got := make([]string, 0)
	for _, route := range engine.Routes() {
		if strings.Contains(route.Path, "/wiki/release-scopes/") {
			got = append(got, route.Method+" "+route.Path)
		}
	}
	sort.Strings(got)
	require.Equal(t, []string{
		"GET /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/current",
		"GET /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/releases/:release_id/pages/:logical_slug",
		"GET /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/releases/:release_id/payloads/:logical_slug",
		"GET /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/releases/:release_id/search",
		"POST /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/activations",
		"POST /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/preparations",
	}, got)

	recorder := performJSON(
		t,
		engine,
		http.MethodGet,
		"/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/current",
		nil,
	)
	require.Equal(t, http.StatusUnauthorized, recorder.Code, recorder.Body.String())
	require.NotEqual(t, http.StatusNotFound, recorder.Code)
}

type wikiReleaseKBServiceStub struct {
	interfaces.KnowledgeBaseService
	knowledgeBases map[string]*types.KnowledgeBase
}

func (s *wikiReleaseKBServiceStub) GetKnowledgeBaseByID(
	_ context.Context,
	id string,
) (*types.KnowledgeBase, error) {
	return s.knowledgeBases[id], nil
}

type wikiReleaseTenantServiceStub struct {
	interfaces.TenantService
}

func (wikiReleaseTenantServiceStub) GetTenantByID(
	_ context.Context,
	id uint64,
) (*types.Tenant, error) {
	return &types.Tenant{ID: id, Name: "tenant"}, nil
}

type wikiReleaseUserServiceStub struct {
	interfaces.UserService
}

func (wikiReleaseUserServiceStub) GetUserByTenantID(
	_ context.Context,
	tenantID uint64,
) (*types.User, error) {
	return &types.User{
		ID:       "api-user",
		TenantID: tenantID,
		IsActive: true,
	}, nil
}

type wikiReleaseAPIKeyServiceStub struct {
	interfaces.TenantAPIKeyService
	tenantID uint64
}

func (s wikiReleaseAPIKeyServiceStub) AuthenticateAPIKey(
	_ context.Context,
	_ string,
) (*types.TenantAPIKey, error) {
	return &types.TenantAPIKey{
		ID:               7,
		TenantID:         &s.tenantID,
		ScopeType:        types.APIKeyScopeTenant,
		FullAccess:       true,
		KnowledgeBaseIDs: types.StringArray{"raw-1", "wiki-1", "wiki-2"},
	}, nil
}

type wikiReleaseWikiPageServiceStub struct {
	interfaces.WikiPageService
	moveCalls   int
	folderCalls int
}

func (s *wikiReleaseWikiPageServiceStub) MovePage(
	_ context.Context,
	kbID string,
	slug string,
	folderID string,
) (*types.WikiPage, error) {
	s.moveCalls++
	return &types.WikiPage{
		KnowledgeBaseID: kbID,
		Slug:            slug,
		FolderID:        folderID,
	}, nil
}

func (s *wikiReleaseWikiPageServiceStub) RenameOrMoveFolder(
	_ context.Context,
	kbID string,
	id string,
	newName string,
	_ string,
	_ bool,
) (*types.WikiFolder, error) {
	s.folderCalls++
	return &types.WikiFolder{
		ID:              id,
		KnowledgeBaseID: kbID,
		Name:            newName,
	}, nil
}

func newWikiReleaseProductionRouter(
	releaseHandler *handler.WikiReleaseHandler,
	kbService *wikiReleaseKBServiceStub,
	wikiService *wikiReleaseWikiPageServiceStub,
) *gin.Engine {
	rbacOff := false
	tenantID := uint64(42)
	return router.NewRouter(router.RouterParams{
		Config: &config.Config{
			Tenant: &config.TenantConfig{EnableRBAC: &rbacOff},
		},
		UserService:         wikiReleaseUserServiceStub{},
		KBService:           kbService,
		TenantService:       wikiReleaseTenantServiceStub{},
		TenantAPIKeyService: wikiReleaseAPIKeyServiceStub{tenantID: tenantID},
		WikiPageHandler: handler.NewWikiPageHandler(
			wikiService,
			kbService,
			nil,
			nil,
		),
		WikiReleaseHandler: releaseHandler,
	})
}

func performAPIKeyJSON(
	t *testing.T,
	engine http.Handler,
	method string,
	path string,
	body any,
) *httptest.ResponseRecorder {
	t.Helper()
	var raw []byte
	var err error
	if body != nil {
		raw, err = json.Marshal(body)
		require.NoError(t, err)
	}
	request := httptest.NewRequest(method, path, bytes.NewReader(raw))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-API-Key", "test-key")
	recorder := httptest.NewRecorder()
	engine.ServeHTTP(recorder, request)
	return recorder
}

func TestWikiReleaseFalsificationSealRequiresBothSuccessfulKBACLs(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, test := range []struct {
		name       string
		wikiTenant uint64
		rawTenant  uint64
	}{
		{name: "missing raw ACL evidence", wikiTenant: 42, rawTenant: 99},
		{name: "missing wiki ACL evidence", wikiTenant: 99, rawTenant: 42},
	} {
		t.Run(test.name, func(t *testing.T) {
			fixture := newWikiReleaseHandlerFixture(t)
			kbService := &wikiReleaseKBServiceStub{
				knowledgeBases: map[string]*types.KnowledgeBase{
					"wiki-1": {
						ID:               "wiki-1",
						TenantID:         test.wikiTenant,
						IndexingStrategy: types.IndexingStrategy{WikiEnabled: true},
					},
					"raw-1": {ID: "raw-1", TenantID: test.rawTenant},
				},
			}
			engine := newWikiReleaseProductionRouter(
				fixture.handler,
				kbService,
				&wikiReleaseWikiPageServiceStub{},
			)
			recorder := performAPIKeyJSON(
				t,
				engine,
				http.MethodPost,
				"/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/preparations",
				wikiReleasePreparationRequest(),
			)
			require.Equal(t, http.StatusForbidden, recorder.Code, recorder.Body.String())
		})
	}
}

func TestWikiReleaseFalsificationProductionManagedMutationCoverage(t *testing.T) {
	gin.SetMode(gin.TestMode)
	fixture := newWikiReleaseHandlerFixture(t)
	releaseEngine := gin.New()
	releaseEngine.Use(wikiReleaseAuthContext(fixture.scope))
	registerWikiReleaseHandlerRoutes(releaseEngine, fixture.handler)
	base := "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1"
	preparationRequest, decisionRaw := wikiReleaseReviewedPreparationRequest(
		t, fixture, "preparation-production", "nonce-production", "", 0,
		wikiReleaseHandlerMembers(0),
	)
	recorder := performJSON(
		t, releaseEngine, http.MethodPost, base+"/preparations", preparationRequest,
	)
	require.Equal(t, http.StatusCreated, recorder.Code, recorder.Body.String())
	preparation := decodeWikiReleaseData[types.WikiReleasePreparation](t, recorder)
	rawAuthorization := signWikiReleaseHandlerAuthorization(
		t, fixture.privateKey, preparation, "nonce-production",
	)
	recorder = performJSON(
		t, releaseEngine, http.MethodPost, base+"/activations",
		wikiReleaseReviewedActivationBody(decisionRaw, rawAuthorization),
	)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())

	kbService := &wikiReleaseKBServiceStub{
		knowledgeBases: map[string]*types.KnowledgeBase{
			"wiki-1": {
				ID:               "wiki-1",
				TenantID:         42,
				IndexingStrategy: types.IndexingStrategy{WikiEnabled: true},
			},
			"wiki-2": {
				ID:               "wiki-2",
				TenantID:         42,
				IndexingStrategy: types.IndexingStrategy{WikiEnabled: true},
			},
		},
	}
	wikiService := &wikiReleaseWikiPageServiceStub{}
	engine := newWikiReleaseProductionRouter(fixture.handler, kbService, wikiService)

	recorder = performAPIKeyJSON(
		t,
		engine,
		http.MethodPut,
		"/api/v1/knowledgebase/wiki-1/wiki/move-page",
		types.WikiPageMoveRequest{Slug: "a", FolderID: "folder-1"},
	)
	require.Equal(t, http.StatusConflict, recorder.Code, recorder.Body.String())
	require.Zero(t, wikiService.moveCalls)

	recorder = performAPIKeyJSON(
		t,
		engine,
		http.MethodPut,
		"/api/v1/knowledgebase/wiki-1/wiki/folders/folder-1",
		types.WikiFolderUpdateRequest{Name: "Renamed"},
	)
	require.Equal(t, http.StatusConflict, recorder.Code, recorder.Body.String())
	require.Zero(t, wikiService.folderCalls)

	recorder = performAPIKeyJSON(
		t,
		engine,
		http.MethodPut,
		"/api/v1/knowledgebase/wiki-2/wiki/move-page",
		types.WikiPageMoveRequest{Slug: "a", FolderID: "folder-1"},
	)
	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	require.Equal(t, 1, wikiService.moveCalls)

}
