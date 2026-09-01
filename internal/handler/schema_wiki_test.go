package handler

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	apprepo "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	apperrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type schemaWikiScopeResolverStub struct {
	head             *types.WikiReleaseHead
	err              error
	calls            int
	preparationScope *types.WikiReleaseScope
	preparationErr   error
	preparationCalls int
}

func (s *schemaWikiScopeResolverStub) GetPreparationScopeForWikiKB(
	_ context.Context,
	_ uint64,
	_ string,
	_ string,
) (*types.WikiReleaseScope, error) {
	s.preparationCalls++
	return s.preparationScope, s.preparationErr
}

type schemaWikiHTTPServiceSpy struct {
	createCalls           int
	reviewCalls           int
	draftReadCalls        int
	currentReadCalls      int
	searchCalls           int
	reviewedReadCalls     int
	currentCitationCalls  int
	reviewedCitationCalls int
	citationErr           error
	citationBytes         []byte
	currentAuthority      *service.SchemaWikiCurrentAuthorityV1
	goldenSummaryCalls    int
	goldenPrivateCalls    int
	goldenPreviewCalls    int
	goldenSummary         *types.SchemaWikiGoldenQualitySummaryV1
	goldenPrivate         *types.SchemaWikiGoldenQualityDossierV2
	goldenPreview         *types.SchemaWikiGoldenEvidencePreviewAuthorityV1
	goldenSuccessorCalls  int
	goldenSuccessor       *types.SchemaWikiGoldenSuccessorStatusV1
	decisionCalls         int
	decisionPrincipal     types.WikiReleasePrincipal
	decisionScope         types.WikiReleaseScope
	decisionKey           apprepo.SchemaWikiFormalCandidatePreviewKey
	decisionInputs        [][]byte
	authorizationInputs   [][]byte
	decisionResult        *types.HumanBatchDecisionReceiptV1
	releaseResult         *types.WikiReleaseReceipt
	decisionErr           error
	decisionFunc          func([]byte, []byte) (*types.HumanBatchDecisionReceiptV1, *types.WikiReleaseReceipt, error)
}

func (s *schemaWikiHTTPServiceSpy) CreateEntityPageGraphDraft830G1(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	json.RawMessage,
) (*types.WikiReleasePreparation, error) {
	s.createCalls++
	return &types.WikiReleasePreparation{ID: "preparation-g1"}, nil
}

func (s *schemaWikiHTTPServiceSpy) DecideSchemaWikiFormalCandidatePreview(
	_ context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	key apprepo.SchemaWikiFormalCandidatePreviewKey,
	rawDecision []byte,
	rawAuthorization []byte,
) (*types.HumanBatchDecisionReceiptV1, *types.WikiReleaseReceipt, error) {
	s.decisionCalls++
	s.decisionPrincipal = principal
	s.decisionScope = scope
	s.decisionKey = key
	s.decisionInputs = append(s.decisionInputs, append([]byte(nil), rawDecision...))
	s.authorizationInputs = append(s.authorizationInputs, append([]byte(nil), rawAuthorization...))
	if s.decisionFunc != nil {
		return s.decisionFunc(rawDecision, rawAuthorization)
	}
	return s.decisionResult, s.releaseResult, s.decisionErr
}

func (s *schemaWikiHTTPServiceSpy) ReadSchemaWikiGoldenSuccessorStatus(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
) (*types.SchemaWikiGoldenSuccessorStatusV1, error) {
	s.goldenSuccessorCalls++
	return s.goldenSuccessor, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadSchemaPreparationGoldenQualitySummary(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	string,
) (*types.SchemaWikiGoldenQualitySummaryV1, error) {
	s.goldenSummaryCalls++
	return s.goldenSummary, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadSchemaPreparationGoldenQualityDossier(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	string,
) (*types.SchemaWikiGoldenQualityDossierV2, error) {
	s.goldenPrivateCalls++
	return s.goldenPrivate, nil
}

func (s *schemaWikiHTTPServiceSpy) IssueSchemaPreparationGoldenEvidencePreview(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	string,
	string,
	string,
) (*types.SchemaWikiGoldenEvidencePreviewAuthorityV1, error) {
	s.goldenPreviewCalls++
	return s.goldenPreview, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadCurrentSchemaAuthority(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
) (*service.SchemaWikiCurrentAuthorityV1, error) {
	if s.currentAuthority != nil {
		return s.currentAuthority, nil
	}
	return &service.SchemaWikiCurrentAuthorityV1{
		ReleaseID:       "release-596-1",
		ActivationEpoch: 7,
		Entity: types.EntityIdentityV1{
			DomainID: "medical-insurance", EntityID: "ping-an-e-sheng-bao",
		},
		EntityVersion: types.EntityVersionV1{
			EntityID: "ping-an-e-sheng-bao", VersionID: "596-1", ProductVersionID: "596-1",
		},
		Root: types.SchemaRootPageV1{
			Contract: "schema-root-page.v1", EntityID: "ping-an-e-sheng-bao",
			EntityVersionID: "596-1", ProductVersionID: "596-1",
		},
	}, nil
}

func (s *schemaWikiHTTPServiceSpy) CreateSchemaDraft(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	types.KnowledgeWikiReleaseV1,
	types.Schema67CandidateEvidenceAuthorityV1,
	types.SchemaWikiReviewBundleV1,
	types.Schema67GoldenEvaluationReviewBundleV1,
	types.Schema67GoldenReviewSuccessorMetadataV1,
) (*types.WikiReleasePreparation, error) {
	s.createCalls++
	return &types.WikiReleasePreparation{ID: "preparation-596-1"}, nil
}

func (s *schemaWikiHTTPServiceSpy) ReviewSchemaDraft(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	[]byte,
) (*types.WikiReleasePreparation, error) {
	s.reviewCalls++
	return &types.WikiReleasePreparation{ID: "preparation-596-1"}, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadSchemaDraftMember(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	string,
	string,
) (*types.WikiReleaseMemberSnapshot, error) {
	s.draftReadCalls++
	return &types.WikiReleaseMemberSnapshot{LogicalSlug: "field:product_code"}, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadCurrentSchemaMember(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
) (*service.SchemaWikiMemberReadV1, error) {
	s.currentReadCalls++
	return &service.SchemaWikiMemberReadV1{ReleaseID: "release-596-1"}, nil
}

func (s *schemaWikiHTTPServiceSpy) SearchCurrentSchemaMembers(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
) ([]service.SchemaWikiMemberReadV1, error) {
	s.searchCalls++
	return []service.SchemaWikiMemberReadV1{{ReleaseID: "release-596-1"}}, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadReviewedPreparationMember(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	string,
) (*service.SchemaWikiMemberReadV1, error) {
	s.reviewedReadCalls++
	return &service.SchemaWikiMemberReadV1{PreparationID: "preparation-596-1"}, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadSchemaPreparationMember(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	string,
) (*service.SchemaWikiMemberReadV1, error) {
	s.reviewedReadCalls++
	return &service.SchemaWikiMemberReadV1{PreparationID: "preparation-596-1"}, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadReviewedPreparationRoot(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
) (*types.SchemaRootPageV1, error) {
	return &types.SchemaRootPageV1{}, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadCurrentSchemaCitation(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	string,
	string,
) ([]byte, error) {
	s.currentCitationCalls++
	return append([]byte(nil), s.citationBytes...), s.citationErr
}

func (s *schemaWikiHTTPServiceSpy) IssueCurrentSchemaCitationAuthority(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	_ string,
	_ string,
	_ string,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	s.currentCitationCalls++
	if s.citationErr != nil {
		return nil, s.citationErr
	}
	var authority types.SchemaWikiCitationContentAuthorityV1
	if len(s.citationBytes) > 0 {
		if err := json.Unmarshal(s.citationBytes, &authority); err != nil {
			return nil, err
		}
	}
	return &authority, nil
}

func (s *schemaWikiHTTPServiceSpy) IssueEntityPageGraphPreparationCitationAuthority830G1(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	_ string,
	_ string,
	_ string,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	s.reviewedCitationCalls++
	if s.citationErr != nil {
		return nil, s.citationErr
	}
	return &types.SchemaWikiCitationContentAuthorityV1{}, nil
}

func (s *schemaWikiHTTPServiceSpy) ReadSchemaCitationContent(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	_ string,
) ([]byte, error) {
	s.currentCitationCalls++
	return append([]byte(nil), s.citationBytes...), s.citationErr
}

func (s *schemaWikiHTTPServiceSpy) ReadReviewedPreparationCitation(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	string,
	string,
	string,
) ([]byte, error) {
	s.reviewedCitationCalls++
	return nil, s.citationErr
}

func (s *schemaWikiScopeResolverStub) GetHeadForWikiKB(
	_ context.Context,
	_ uint64,
	_ string,
) (*types.WikiReleaseHead, error) {
	s.calls++
	return s.head, s.err
}

func schemaWikiScopeContext(t *testing.T, params gin.Params) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest(http.MethodGet, "/", nil)
	c.Set(types.TenantIDContextKey.String(), uint64(10003))
	c.Params = params
	return c, recorder
}

func TestDecodeSchemaWikiCreateDraftRequestAcceptsOnlyMutuallyExclusiveClosedVariants(t *testing.T) {
	t.Parallel()
	old := `{"preparation_id":"old-preparation","release":{},"candidate_evidence_authority":{},"review_bundle":{},"evaluation_bundle":{},"review_successor":{}}`
	g1 := `{"preparation_id":"g1-preparation","entity_page_manifest":{"contract":"entity-page-manifest.830.g1.v1"}}`
	for _, test := range []struct {
		name        string
		body        string
		wantVariant string
		wantError   bool
	}{
		{name: "legacy schema", body: old, wantVariant: "schema-wiki"},
		{name: "g1 manifest", body: g1, wantVariant: "entity-page-graph-830-g1"},
		{name: "mixed", body: strings.TrimSuffix(g1, "}") + `,"release":{}}`, wantError: true},
		{name: "unknown member authority", body: `{"preparation_id":"g1","entity_page_manifest":{},"members":[]}`, wantError: true},
		{name: "missing preparation", body: `{"entity_page_manifest":{}}`, wantError: true},
		{name: "blank preparation", body: `{"preparation_id":" ","entity_page_manifest":{}}`, wantError: true},
		{name: "duplicate preparation", body: `{"preparation_id":"g1","preparation_id":"g2","entity_page_manifest":{}}`, wantError: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(recorder)
			c.Request = httptest.NewRequest(http.MethodPost, "/", strings.NewReader(test.body))
			var request schemaWikiCreateDraftRequest
			variant, err := decodeSchemaWikiCreateDraftRequest(c, &request)
			if test.wantError {
				require.ErrorIs(t, err, service.ErrSchemaWikiPreparationInvalid)
				require.Empty(t, variant)
				return
			}
			require.NoError(t, err)
			require.Equal(t, test.wantVariant, variant)
		})
	}
}

func TestResolveScopeParamsDerivesNonOverridableReleaseScope(t *testing.T) {
	t.Parallel()
	resolver := &schemaWikiScopeResolverStub{head: &types.WikiReleaseHead{
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003,
			SpaceID:  "space-596-1",
			RawKBID:  "raw-596-1",
			WikiKBID: "wiki-596-1",
		},
		ActiveReleaseID: "release-596-1",
		ActivationEpoch: 1,
	}}
	h := NewSchemaWikiHandler(resolver, nil)
	c, _ := schemaWikiScopeContext(t, gin.Params{{Key: "kb_id", Value: "wiki-596-1"}})

	h.ResolveScopeParams()(c)

	require.False(t, c.IsAborted())
	require.Equal(t, "space-596-1", c.Param("space_id"))
	require.Equal(t, "raw-596-1", c.Param("raw_kb_id"))
	require.Equal(t, 1, resolver.calls)
}

func TestResolvePreparationScopeParamsBootstrapsWithoutHead(t *testing.T) {
	t.Parallel()
	scope := types.WikiReleaseScope{
		TenantID: 10003, SpaceID: "space-preparation", RawKBID: "raw-preparation", WikiKBID: "wiki-preparation",
	}
	resolver := &schemaWikiScopeResolverStub{preparationScope: &scope}
	handler := NewSchemaWikiHandler(resolver, nil)
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: scope.WikiKBID},
		{Key: "preparation_id", Value: "preparation-g1"},
	})
	handler.ResolvePreparationScopeParams()(c)
	require.False(t, c.IsAborted())
	require.Equal(t, scope.SpaceID, c.Param("space_id"))
	require.Equal(t, scope.RawKBID, c.Param("raw_kb_id"))
	require.Equal(t, 1, resolver.preparationCalls)
	require.Zero(t, resolver.calls, "Candidate Preview bootstrap must not consult Head")

	handler.PreparationScope(c)
	require.Equal(t, http.StatusOK, recorder.Code)
	require.Contains(t, recorder.Body.String(), `"wiki_kb_id":"wiki-preparation"`)
}

func TestSchemaWikiScopeResponseHasExactLaneCContract(t *testing.T) {
	t.Parallel()
	h := NewSchemaWikiHandler(nil, nil)
	c, recorder := schemaWikiScopeContext(t, nil)
	c.Set(schemaWikiResolvedHeadContextKey, types.WikiReleaseHead{
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
		},
		ActiveReleaseID: "release-secret", ActivationEpoch: 9,
	})

	h.Scope(c)

	require.Equal(t, http.StatusOK, recorder.Code)
	var response struct {
		Success bool                   `json:"success"`
		Data    map[string]interface{} `json:"data"`
	}
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	require.True(t, response.Success)
	require.Len(t, response.Data, 5)
	for _, key := range []string{"version", "space_id", "raw_kb_id", "wiki_kb_id", "scope_sha256"} {
		require.Contains(t, response.Data, key)
	}
	require.NotContains(t, recorder.Body.String(), "release-secret")
	require.NotContains(t, response.Data, "tenant_id")
	require.NotContains(t, response.Data, "activation_epoch")
}

func TestSchemaWikiCurrentEntityVersionReturnsClosedActivePin(t *testing.T) {
	t.Parallel()
	h := NewSchemaWikiHandler(nil, &schemaWikiHTTPServiceSpy{})
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-596-1"},
		{Key: "entity_id", Value: "ping-an-e-sheng-bao"},
		{Key: "version_id", Value: "596-1"},
	})
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer-1"}
	c.Request = c.Request.WithContext(types.WithPrincipal(c.Request.Context(), principal))
	c.Set(types.PrincipalContextKey.String(), principal)
	c.Set(schemaWikiResolvedHeadContextKey, types.WikiReleaseHead{
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
		},
		ActiveReleaseID: "release-596-1", ActivationEpoch: 7,
	})

	h.CurrentEntityVersion(c)

	require.Equal(t, http.StatusOK, recorder.Code)
	var response struct {
		Success bool                   `json:"success"`
		Data    map[string]interface{} `json:"data"`
	}
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	require.True(t, response.Success)
	require.Len(t, response.Data, 6)
	require.Equal(t, "schema-wiki-current-entity-version.v1", response.Data["version"])
	require.Equal(t, "ping-an-e-sheng-bao", response.Data["entity_id"])
	require.Equal(t, "596-1", response.Data["entity_version_id"])
	require.Equal(t, "release-596-1", response.Data["active_release_id"])
	require.Equal(t, float64(7), response.Data["activation_epoch"])
	require.IsType(t, map[string]interface{}{}, response.Data["root"])

	for name, params := range map[string]gin.Params{
		"foreign entity": {
			{Key: "kb_id", Value: "wiki-596-1"},
			{Key: "space_id", Value: "space-596-1"},
			{Key: "raw_kb_id", Value: "raw-596-1"},
			{Key: "entity_id", Value: "foreign-product"},
			{Key: "version_id", Value: "596-1"},
		},
		"foreign version": {
			{Key: "kb_id", Value: "wiki-596-1"},
			{Key: "space_id", Value: "space-596-1"},
			{Key: "raw_kb_id", Value: "raw-596-1"},
			{Key: "entity_id", Value: "ping-an-e-sheng-bao"},
			{Key: "version_id", Value: "596-2"},
		},
	} {
		t.Run(name, func(t *testing.T) {
			attack, attackRecorder := schemaWikiScopeContext(t, params)
			attack.Request = attack.Request.WithContext(types.WithPrincipal(attack.Request.Context(), principal))
			attack.Set(types.PrincipalContextKey.String(), principal)
			attack.Set(schemaWikiResolvedHeadContextKey, types.WikiReleaseHead{
				WikiReleaseScope: types.WikiReleaseScope{
					TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
				},
				ActiveReleaseID: "release-596-1", ActivationEpoch: 7,
			})
			h.CurrentEntityVersion(attack)
			require.NotEqual(t, http.StatusOK, attackRecorder.Code)
			require.NotContains(t, attackRecorder.Body.String(), "release-596-1")
			require.NotContains(t, attackRecorder.Body.String(), "foreign-")
		})
	}

	driftSpy := &schemaWikiHTTPServiceSpy{currentAuthority: &service.SchemaWikiCurrentAuthorityV1{
		ReleaseID: "release-596-1", ActivationEpoch: 8,
		Entity: types.EntityIdentityV1{DomainID: "medical-insurance", EntityID: "ping-an-e-sheng-bao"},
		EntityVersion: types.EntityVersionV1{
			EntityID: "ping-an-e-sheng-bao", VersionID: "596-1", ProductVersionID: "596-1",
		},
		Root: types.SchemaRootPageV1{
			Contract: "schema-root-page.v1", EntityID: "ping-an-e-sheng-bao",
			EntityVersionID: "596-1", ProductVersionID: "596-1",
		},
	}}
	driftHandler := NewSchemaWikiHandler(nil, driftSpy)
	drift, driftRecorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"}, {Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-596-1"}, {Key: "entity_id", Value: "ping-an-e-sheng-bao"},
		{Key: "version_id", Value: "596-1"},
	})
	drift.Request = drift.Request.WithContext(types.WithPrincipal(drift.Request.Context(), principal))
	drift.Set(types.PrincipalContextKey.String(), principal)
	drift.Set(schemaWikiResolvedHeadContextKey, types.WikiReleaseHead{
		WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
		},
		ActiveReleaseID: "release-596-1", ActivationEpoch: 7,
	})
	driftHandler.CurrentEntityVersion(drift)
	require.NotEqual(t, http.StatusOK, driftRecorder.Code)
	require.NotContains(t, driftRecorder.Body.String(), "release-596-1")
}

func TestSchemaWikiLifecycleScopeBindersFailClosed(t *testing.T) {
	t.Parallel()
	exact := types.WikiReleaseScope{
		TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
	}

	t.Run("active exact path", func(t *testing.T) {
		resolver := &schemaWikiScopeResolverStub{head: &types.WikiReleaseHead{
			WikiReleaseScope: exact, ActiveReleaseID: "release-596-1", ActivationEpoch: 1,
		}}
		h := NewSchemaWikiHandler(resolver, nil)
		c, _ := schemaWikiScopeContext(t, gin.Params{
			{Key: "kb_id", Value: exact.WikiKBID}, {Key: "space_id", Value: exact.SpaceID},
			{Key: "raw_kb_id", Value: exact.RawKBID},
		})
		h.RequireScopeParams()(c)
		require.False(t, c.IsAborted())
	})

	t.Run("active foreign raw", func(t *testing.T) {
		resolver := &schemaWikiScopeResolverStub{head: &types.WikiReleaseHead{
			WikiReleaseScope: exact, ActiveReleaseID: "release-596-1", ActivationEpoch: 1,
		}}
		h := NewSchemaWikiHandler(resolver, nil)
		c, recorder := schemaWikiScopeContext(t, gin.Params{
			{Key: "kb_id", Value: exact.WikiKBID}, {Key: "space_id", Value: exact.SpaceID},
			{Key: "raw_kb_id", Value: "raw-foreign"},
		})
		h.RequireScopeParams()(c)
		require.True(t, c.IsAborted())
		require.Equal(t, http.StatusForbidden, recorder.Code)
		require.NotContains(t, recorder.Body.String(), "raw-foreign")
	})

	t.Run("initial no head", func(t *testing.T) {
		resolver := &schemaWikiScopeResolverStub{err: apprepo.ErrWikiReleaseNotFound}
		h := NewSchemaWikiHandler(resolver, nil)
		c, _ := schemaWikiScopeContext(t, gin.Params{
			{Key: "kb_id", Value: exact.WikiKBID}, {Key: "space_id", Value: exact.SpaceID},
			{Key: "raw_kb_id", Value: exact.RawKBID},
		})
		h.BindCreateScopeParams()(c)
		require.False(t, c.IsAborted())
	})

	t.Run("preparation-derived scope", func(t *testing.T) {
		resolver := &schemaWikiScopeResolverStub{preparationScope: &exact}
		h := NewSchemaWikiHandler(resolver, nil)
		c, _ := schemaWikiScopeContext(t, gin.Params{
			{Key: "kb_id", Value: exact.WikiKBID}, {Key: "space_id", Value: exact.SpaceID},
			{Key: "raw_kb_id", Value: exact.RawKBID},
			{Key: "preparation_id", Value: "preparation-596-1"},
		})
		h.RequirePreparationScopeParams()(c)
		require.False(t, c.IsAborted())
		require.Equal(t, 1, resolver.preparationCalls)
	})
}

func TestResolveScopeParamsRejectsConflictAndMissingOrForeignHead(t *testing.T) {
	t.Parallel()

	for _, param := range []gin.Param{
		{Key: "raw_kb_id", Value: "attacker-raw"},
		{Key: "space_id", Value: "attacker-space"},
	} {
		t.Run("caller supplied "+param.Key, func(t *testing.T) {
			resolver := &schemaWikiScopeResolverStub{}
			h := NewSchemaWikiHandler(resolver, nil)
			c, recorder := schemaWikiScopeContext(t, gin.Params{
				{Key: "kb_id", Value: "wiki-596-1"},
				param,
			})
			h.ResolveScopeParams()(c)
			require.True(t, c.IsAborted())
			require.Equal(t, http.StatusForbidden, recorder.Code)
			require.JSONEq(t, `{"success":false,"error":{"message":"wiki release access denied"}}`, recorder.Body.String())
			require.NotContains(t, recorder.Body.String(), "attacker-")
			require.Zero(t, resolver.calls)
		})
	}

	for name, resolver := range map[string]*schemaWikiScopeResolverStub{
		"zero head":     {err: apprepo.ErrWikiReleaseNotFound},
		"multiple head": {err: apprepo.ErrWikiReleaseConflict},
		"cross tenant": {head: &types.WikiReleaseHead{WikiReleaseScope: types.WikiReleaseScope{
			TenantID: 99999, SpaceID: "space-foreign", RawKBID: "raw-foreign", WikiKBID: "wiki-596-1",
		}}},
	} {
		t.Run(name, func(t *testing.T) {
			h := NewSchemaWikiHandler(resolver, nil)
			c, recorder := schemaWikiScopeContext(t, gin.Params{{Key: "kb_id", Value: "wiki-596-1"}})
			h.ResolveScopeParams()(c)
			require.True(t, c.IsAborted())
			require.Equal(t, http.StatusForbidden, recorder.Code)
			require.JSONEq(t, `{"success":false,"error":{"message":"wiki release access denied"}}`, recorder.Body.String())
			body := recorder.Body.String()
			for _, secretScope := range []string{"space-foreign", "raw-foreign", "release-596-1"} {
				require.False(t, strings.Contains(body, secretScope), "body=%s", body)
			}
		})
	}
}

func TestSchemaWikiCitationPreviewUsesOnlyPathIdentitiesAndFailsClosed(t *testing.T) {
	t.Parallel()
	spy := &schemaWikiHTTPServiceSpy{citationErr: service.ErrSchemaWikiCitationUnavailable}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-596-1"},
		{Key: "release_id", Value: "release-596-1"},
		{Key: "field_id", Value: "product_code"},
		{Key: "citation_id", Value: "citation-secret"},
	})
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "reviewer"}
	ctx := types.WithPrincipal(c.Request.Context(), principal)
	c.Request = c.Request.WithContext(ctx)
	c.Set(types.PrincipalContextKey.String(), principal)

	h.PreviewCurrentCitation(c)

	require.Equal(t, http.StatusServiceUnavailable, recorder.Code)
	require.JSONEq(t, `{"success":false,"error":{"message":"schema wiki citation unavailable"}}`, recorder.Body.String())
	require.NotContains(t, recorder.Body.String(), "citation-secret")
	require.Equal(t, 1, spy.currentCitationCalls)
}

func TestSchemaWikiCitationPreviewReturnsStablePageUnavailableCode(t *testing.T) {
	t.Parallel()
	spy := &schemaWikiHTTPServiceSpy{citationErr: service.ErrSchemaWikiCitationPageUnavailable}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-596-1"},
		{Key: "release_id", Value: "release-596-1"},
		{Key: "field_id", Value: "product_code"},
		{Key: "citation_id", Value: "citation-secret"},
	})
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
	ctx := types.WithPrincipal(c.Request.Context(), principal)
	c.Request = c.Request.WithContext(ctx)
	c.Set(types.PrincipalContextKey.String(), principal)

	h.PreviewCurrentCitation(c)

	require.Equal(t, http.StatusUnprocessableEntity, recorder.Code)
	require.JSONEq(t,
		`{"success":false,"error":{"code":"PAGE_UNAVAILABLE","message":"schema wiki citation page unavailable"}}`,
		recorder.Body.String(),
	)
	require.NotContains(t, recorder.Body.String(), "citation-secret")
	require.NotContains(t, recorder.Body.String(), "opaque_token")
	require.Equal(t, 1, spy.currentCitationCalls)
}

func TestSchemaWikiCitationPreviewReturnsClosedAuthorityJSONNotPDFBytes(t *testing.T) {
	t.Parallel()
	authority := `{"contract":"schema-wiki-citation-content-authority.v1"}`
	spy := &schemaWikiHTTPServiceSpy{citationBytes: []byte(authority)}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-596-1"},
		{Key: "release_id", Value: "release-596-1"},
		{Key: "field_id", Value: "product_code"},
		{Key: "citation_id", Value: "citation-product-code"},
	})
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
	ctx := types.WithPrincipal(c.Request.Context(), principal)
	c.Request = c.Request.WithContext(ctx)
	c.Set(types.PrincipalContextKey.String(), principal)

	h.PreviewCurrentCitation(c)

	require.Equal(t, http.StatusOK, recorder.Code)
	require.Equal(t, "application/json; charset=utf-8", recorder.Header().Get("Content-Type"))
	var response struct {
		Success bool `json:"success"`
		Data    struct {
			Contract string `json:"contract"`
		} `json:"data"`
	}
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	require.True(t, response.Success)
	require.Equal(t, "schema-wiki-citation-content-authority.v1", response.Data.Contract)
	require.NotContains(t, recorder.Body.String(), "%PDF")
	require.Equal(t, 1, spy.currentCitationCalls)
}

type schemaWikiFormalCandidatePreviewReaderStub struct {
	record       apprepo.SchemaWikiFormalCandidatePreviewRecord
	content      apprepo.SchemaWikiFormalCandidatePreviewContent
	readErr      error
	contentErr   error
	readCalls    int
	contentCalls int
}

func (s *schemaWikiFormalCandidatePreviewReaderStub) ReadExact(
	_ uint64,
	_ apprepo.SchemaWikiFormalCandidatePreviewKey,
) (apprepo.SchemaWikiFormalCandidatePreviewRecord, error) {
	s.readCalls++
	return s.record, s.readErr
}

func (s *schemaWikiFormalCandidatePreviewReaderStub) ReadContentExact(
	_ uint64,
	_ apprepo.SchemaWikiFormalCandidatePreviewKey,
	_ apprepo.SchemaWikiFormalCandidatePreviewContentRequest,
) (apprepo.SchemaWikiFormalCandidatePreviewContent, error) {
	s.contentCalls++
	return s.content, s.contentErr
}

func schemaWikiFormalCandidatePreviewHandlerFixture() (*SchemaWikiHandler, *schemaWikiFormalCandidatePreviewReaderStub) {
	contentBytes := []byte("%PDF-1.7 exact")
	contentSum := sha256.Sum256(contentBytes)
	reader := &schemaWikiFormalCandidatePreviewReaderStub{
		record: apprepo.SchemaWikiFormalCandidatePreviewRecord{
			TenantID: 10003, KBID: "wiki-596-1",
			ExperimentID:   "2a92f197-4b33-41de-a6af-c60252d6347d",
			ManifestSHA256: strings.Repeat("a", 64), CandidateSHA256: strings.Repeat("b", 64),
			CompanionSHA256: strings.Repeat("c", 64), TerminalSHA256: strings.Repeat("d", 64),
			RevisionSetSHA256: strings.Repeat("e", 64), PreviewSHA256: strings.Repeat("f", 64),
			Preview: json.RawMessage(`{"contract":"schema-wiki-formal-candidate-preview.815.v1","preview_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}`),
		},
		content: apprepo.SchemaWikiFormalCandidatePreviewContent{
			Bytes: contentBytes, OriginalFileSHA256: hex.EncodeToString(contentSum[:]),
		},
	}
	service := service.NewSchemaWikiServiceWithFormalCandidatePreview(reader)
	return NewSchemaWikiHandler(nil, service), reader
}

func schemaWikiFormalCandidatePreviewContext(t *testing.T, path string, params gin.Params) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest(http.MethodGet, path, nil)
	c.Set(types.TenantIDContextKey.String(), uint64(10003))
	c.Params = params
	return c, recorder
}

func TestSchemaWikiFormalCandidatePreviewHandlerReturnsClosedWireAndExactPDF(t *testing.T) {
	h, reader := schemaWikiFormalCandidatePreviewHandlerFixture()
	baseParams := gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "experiment_id", Value: "2a92f197-4b33-41de-a6af-c60252d6347d"},
		{Key: "version_identity", Value: strings.Repeat("a", 64)},
	}
	c, recorder := schemaWikiFormalCandidatePreviewContext(t, "/", baseParams)
	h.ReadFormalCandidatePreview(c)
	require.Equal(t, http.StatusOK, recorder.Code)
	var response map[string]any
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	require.Equal(t, true, response["success"])
	require.Len(t, response["data"].(map[string]any), 13)
	require.Equal(t, 1, reader.readCalls)

	contentParams := append(gin.Params(nil), baseParams...)
	contentParams = append(contentParams,
		gin.Param{Key: "field_id", Value: "field-01"},
		gin.Param{Key: "selection_id", Value: "selection-01"},
	)
	contentContext, contentRecorder := schemaWikiFormalCandidatePreviewContext(t, "/", contentParams)
	h.ReadFormalCandidatePreviewContent(contentContext)
	require.Equal(t, http.StatusOK, contentRecorder.Code)
	require.Equal(t, "application/pdf", contentRecorder.Header().Get("Content-Type"))
	require.Equal(t, reader.content.Bytes, contentRecorder.Body.Bytes())
	require.Equal(t, 1, reader.contentCalls)
}

func TestSchemaWikiFormalCandidatePreviewHandlerRejectsQueryBodyAndWrongIdentity(t *testing.T) {
	for name, path := range map[string]string{
		"current query": "/?current=true", "latest query": "/?latest=1", "page query": "/?page=1",
	} {
		t.Run(name, func(t *testing.T) {
			h, reader := schemaWikiFormalCandidatePreviewHandlerFixture()
			c, recorder := schemaWikiFormalCandidatePreviewContext(t, path, gin.Params{
				{Key: "kb_id", Value: "wiki-596-1"},
				{Key: "experiment_id", Value: "2a92f197-4b33-41de-a6af-c60252d6347d"},
				{Key: "version_identity", Value: strings.Repeat("a", 64)},
			})
			h.ReadFormalCandidatePreview(c)
			require.Equal(t, http.StatusBadRequest, recorder.Code)
			require.Zero(t, reader.readCalls)
		})
	}
	t.Run("body", func(t *testing.T) {
		h, reader := schemaWikiFormalCandidatePreviewHandlerFixture()
		c, recorder := schemaWikiFormalCandidatePreviewContext(t, "/", gin.Params{
			{Key: "kb_id", Value: "wiki-596-1"},
			{Key: "experiment_id", Value: "2a92f197-4b33-41de-a6af-c60252d6347d"},
			{Key: "version_identity", Value: strings.Repeat("a", 64)},
		})
		c.Request = httptest.NewRequest(http.MethodGet, "/", strings.NewReader(`{"latest":true}`))
		h.ReadFormalCandidatePreview(c)
		require.Equal(t, http.StatusBadRequest, recorder.Code)
		require.Zero(t, reader.readCalls)
	})

	h, reader := schemaWikiFormalCandidatePreviewHandlerFixture()
	reader.contentErr = apprepo.ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	c, recorder := schemaWikiFormalCandidatePreviewContext(t, "/", gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "experiment_id", Value: "2a92f197-4b33-41de-a6af-c60252d6347d"},
		{Key: "version_identity", Value: strings.Repeat("a", 64)},
		{Key: "field_id", Value: "field-foreign"},
		{Key: "selection_id", Value: "selection-foreign"},
	})
	h.ReadFormalCandidatePreviewContent(c)
	require.Equal(t, http.StatusConflict, recorder.Code)
	require.NotContains(t, recorder.Body.String(), "field-foreign")
	require.NotContains(t, recorder.Body.String(), "selection-foreign")
}

const (
	schemaWikiC6SpaceID      = "a8751a40-83ce-55c8-a160-079b283483ca"
	schemaWikiC6RawKBID      = "b1f1764c-443d-46b8-98e3-d5aa5e55eb42"
	schemaWikiC6WikiKBID     = "8d5695de-f255-42d5-9a41-042ba86e97b9"
	schemaWikiC6ExperimentID = "5655e43c-1adb-4282-95f7-305e58441512"
)

type schemaWikiC6DecisionHTTPEndpoint interface {
	DecideFormalCandidatePreview(*gin.Context)
}

func invokeSchemaWikiC6DecisionEndpoint(
	t *testing.T,
	h *SchemaWikiHandler,
	c *gin.Context,
) {
	t.Helper()
	endpoint, ok := any(h).(schemaWikiC6DecisionHTTPEndpoint)
	require.True(t, ok, "bounded C6 decision handler is absent")
	endpoint.DecideFormalCandidatePreview(c)
}

func schemaWikiC6DecisionContext(
	t *testing.T,
	body string,
	requestTarget string,
	mutateParams ...func(*gin.Params),
) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "reviewer-815"}
	request := httptest.NewRequest(http.MethodPost, requestTarget, strings.NewReader(body))
	ctx := types.WithPrincipal(request.Context(), principal)
	ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleAdmin)
	c.Request = request.WithContext(ctx)
	c.Set(types.TenantIDContextKey.String(), uint64(10003))
	c.Set(types.PrincipalContextKey.String(), principal)
	c.Params = gin.Params{
		{Key: "kb_id", Value: schemaWikiC6WikiKBID},
		{Key: "space_id", Value: schemaWikiC6SpaceID},
		{Key: "raw_kb_id", Value: schemaWikiC6RawKBID},
		{Key: "experiment_id", Value: schemaWikiC6ExperimentID},
		{Key: "version_identity", Value: strings.Repeat("a", 64)},
	}
	for _, mutate := range mutateParams {
		mutate(&c.Params)
	}
	return c, recorder
}

func setSchemaWikiC6Param(params *gin.Params, name string, value string) {
	for index := range *params {
		if (*params)[index].Key == name {
			(*params)[index].Value = value
			return
		}
	}
}

func TestSchemaWikiC6DecisionHandlerAcceptsOnlyClosedActivationEnvelope(t *testing.T) {
	t.Run("reject and approve existing response envelopes", func(t *testing.T) {
		for _, test := range []struct {
			name     string
			body     string
			decision *types.HumanBatchDecisionReceiptV1
			release  *types.WikiReleaseReceipt
			want     string
		}{
			{
				name: "reject", body: `{"human_decision":{"nonce":"reject-815"},"publish_authorization":null}`,
				decision: &types.HumanBatchDecisionReceiptV1{Version: "1", Decision: "reject", Nonce: "reject-815"},
				want:     `{"success":true,"data":{"version":"1","decision":"reject","principal_id":"","tenant_id":0,"space_id":"","raw_kb_id":"","wiki_kb_id":"","candidate_hash":"","human_batch_hash":"","review_policy_hash":"","issued_at":0,"expires_at":0,"nonce":"reject-815","signer_key_id":"","signature":""}}`,
			},
			{
				name: "approve", body: `{"human_decision":{"nonce":"approve-815"},"publish_authorization":{"nonce":"approve-815"}}`,
				decision: &types.HumanBatchDecisionReceiptV1{Version: "1", Decision: "approve", Nonce: "approve-815"},
				release:  &types.WikiReleaseReceipt{ID: "receipt-815", ReleaseID: "release-r1-815", ActivationEpoch: 1},
				want:     `{"success":true,"data":{"receipt_id":"receipt-815","tenant_id":0,"space_id":"","raw_kb_id":"","wiki_kb_id":"","nonce":"","authorization_digest":"","previous_release_id":"","release_id":"release-r1-815","activation_epoch":1,"activated_by":"","created_at":"0001-01-01T00:00:00Z"}}`,
			},
		} {
			t.Run(test.name, func(t *testing.T) {
				spy := &schemaWikiHTTPServiceSpy{decisionResult: test.decision, releaseResult: test.release}
				h := NewSchemaWikiHandler(nil, spy)
				c, recorder := schemaWikiC6DecisionContext(t, test.body, "/")
				invokeSchemaWikiC6DecisionEndpoint(t, h, c)
				require.Equal(t, http.StatusOK, recorder.Code)
				require.JSONEq(t, test.want, recorder.Body.String())
				require.Equal(t, 1, spy.decisionCalls)
			})
		}
	})

	validBody := `{"human_decision":{"nonce":"closed-815"},"publish_authorization":null}`
	for _, test := range []struct {
		name   string
		body   string
		target string
		mutate func(*gin.Params)
	}{
		{name: "missing authorization", body: `{"human_decision":{}}`, target: "/"},
		{name: "extra key", body: `{"human_decision":{},"publish_authorization":null,"candidate":{}}`, target: "/"},
		{name: "duplicate key", body: `{"human_decision":{},"publish_authorization":null,"publish_authorization":null}`, target: "/"},
		{name: "trailing json", body: validBody + `{}`, target: "/"},
		{name: "query", body: validBody, target: "/?latest=1"},
		{name: "noncanonical experiment", body: validBody, target: "/", mutate: func(params *gin.Params) {
			setSchemaWikiC6Param(params, "experiment_id", strings.ToUpper(schemaWikiC6ExperimentID))
		}},
		{name: "noncanonical version", body: validBody, target: "/", mutate: func(params *gin.Params) {
			setSchemaWikiC6Param(params, "version_identity", strings.Repeat("A", 64))
		}},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &schemaWikiHTTPServiceSpy{}
			h := NewSchemaWikiHandler(nil, spy)
			var mutations []func(*gin.Params)
			if test.mutate != nil {
				mutations = append(mutations, test.mutate)
			}
			c, recorder := schemaWikiC6DecisionContext(t, test.body, test.target, mutations...)
			invokeSchemaWikiC6DecisionEndpoint(t, h, c)
			require.Equal(t, http.StatusBadRequest, recorder.Code)
			require.Contains(t, recorder.Body.String(), "SCHEMA_WIKI_FORMAL_CANDIDATE_PREVIEW_REQUEST_INVALID")
			require.Zero(t, spy.decisionCalls)
		})
	}
}

func TestSchemaWikiC6DecisionHandlerBindsRawKBExperimentAndVersionIdentity(t *testing.T) {
	spy := &schemaWikiHTTPServiceSpy{
		decisionResult: &types.HumanBatchDecisionReceiptV1{Version: "1", Decision: "reject"},
	}
	h := NewSchemaWikiHandler(nil, spy)
	decision := []byte(`{"nonce":"raw-preserved", "decision":"reject"}`)
	authorization := []byte(`null`)
	body := `{"human_decision":` + string(decision) + `,"publish_authorization":` + string(authorization) + `}`
	c, recorder := schemaWikiC6DecisionContext(t, body, "/")
	invokeSchemaWikiC6DecisionEndpoint(t, h, c)
	require.Equal(t, http.StatusOK, recorder.Code)
	require.Equal(t, types.WikiReleaseScope{
		TenantID: 10003, SpaceID: schemaWikiC6SpaceID,
		RawKBID: schemaWikiC6RawKBID, WikiKBID: schemaWikiC6WikiKBID,
	}, spy.decisionScope)
	require.Equal(t, apprepo.SchemaWikiFormalCandidatePreviewKey{
		KBID: schemaWikiC6RawKBID, ExperimentID: schemaWikiC6ExperimentID,
		VersionIdentity: strings.Repeat("a", 64),
	}, spy.decisionKey)
	require.Equal(t, "web_user:reviewer-815", spy.decisionPrincipal.ID)
	require.Equal(t, decision, spy.decisionInputs[0])
	require.Equal(t, authorization, spy.authorizationInputs[0])
}

func TestSchemaWikiC6DecisionHandlerReusesPreviewAndReleaseErrorSurface(t *testing.T) {
	for _, test := range []struct {
		name   string
		err    error
		status int
	}{
		{name: "request", err: service.ErrSchemaWikiFormalCandidatePreviewRequestInvalid, status: http.StatusBadRequest},
		{name: "access", err: service.ErrWikiReleaseAccessDenied, status: http.StatusForbidden},
		{name: "not found", err: service.ErrSchemaWikiFormalCandidatePreviewNotFound, status: http.StatusNotFound},
		{name: "binding", err: service.ErrSchemaWikiFormalCandidatePreviewBindingMismatch, status: http.StatusConflict},
		{name: "nonce conflict", err: service.ErrWikiReleaseConflict, status: http.StatusConflict},
		{name: "authorization", err: service.ErrWikiReleaseInvalidAuthorization, status: http.StatusBadRequest},
		{name: "storage unavailable", err: apperrors.NewServiceUnavailableError("storage unavailable"), status: http.StatusServiceUnavailable},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &schemaWikiHTTPServiceSpy{decisionErr: test.err}
			h := NewSchemaWikiHandler(nil, spy)
			c, recorder := schemaWikiC6DecisionContext(
				t, `{"human_decision":{"nonce":"error-815"},"publish_authorization":null}`, "/",
			)
			invokeSchemaWikiC6DecisionEndpoint(t, h, c)
			require.Equal(t, test.status, recorder.Code)
		})
	}
}

func TestSchemaWikiC6DecisionHandlerPreservesCanonicalBytesAndExactRetryReceipt(t *testing.T) {
	decision := []byte(`{"nonce":"same-815", "decision":"approve"}`)
	authorization := []byte(`{"nonce":"same-815", "action":"activate"}`)
	receipt := &types.WikiReleaseReceipt{ID: "receipt-815", ReleaseID: "release-r1-815", ActivationEpoch: 1}
	spy := &schemaWikiHTTPServiceSpy{}
	spy.decisionFunc = func(rawDecision, rawAuthorization []byte) (
		*types.HumanBatchDecisionReceiptV1, *types.WikiReleaseReceipt, error,
	) {
		if !bytes.Equal(rawDecision, decision) || !bytes.Equal(rawAuthorization, authorization) {
			return nil, nil, service.ErrWikiReleaseConflict
		}
		return &types.HumanBatchDecisionReceiptV1{Version: "1", Decision: "approve"}, receipt, nil
	}
	h := NewSchemaWikiHandler(nil, spy)
	body := `{"human_decision":` + string(decision) + `,"publish_authorization":` + string(authorization) + `}`
	for range 2 {
		c, recorder := schemaWikiC6DecisionContext(t, body, "/")
		invokeSchemaWikiC6DecisionEndpoint(t, h, c)
		require.Equal(t, http.StatusOK, recorder.Code)
		require.Contains(t, recorder.Body.String(), `"receipt_id":"receipt-815"`)
	}
	changed := strings.Replace(body, "same-815", "drift-815", 1)
	c, recorder := schemaWikiC6DecisionContext(t, changed, "/")
	invokeSchemaWikiC6DecisionEndpoint(t, h, c)
	require.Equal(t, http.StatusConflict, recorder.Code)
	require.Equal(t, 3, spy.decisionCalls)
	require.Equal(t, decision, spy.decisionInputs[0])
	require.Equal(t, authorization, spy.authorizationInputs[0])
}
