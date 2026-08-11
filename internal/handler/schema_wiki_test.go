package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	apprepo "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
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
