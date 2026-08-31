package handler

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type entityPageGraphHTTPService830G1Spy struct {
	result       *service.EntityPageGraphRead830G1
	err          error
	currentCalls int
	pinnedCalls  int
	releaseIDs   []string
	selectors    []service.EntityPageGraphSelector830G1
}

func (s *entityPageGraphHTTPService830G1Spy) ReadCurrentEntityPage830G1(
	context.Context,
	types.WikiReleasePrincipal,
	types.WikiReleaseScope,
	service.EntityPageGraphSelector830G1,
) (*service.EntityPageGraphRead830G1, error) {
	s.currentCalls++
	return s.result, s.err
}

func (s *entityPageGraphHTTPService830G1Spy) ReadPinnedEntityPage830G1(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	releaseID string,
	selector service.EntityPageGraphSelector830G1,
) (*service.EntityPageGraphRead830G1, error) {
	s.pinnedCalls++
	s.releaseIDs = append(s.releaseIDs, releaseID)
	s.selectors = append(s.selectors, selector)
	return s.result, s.err
}

func TestEntityPageGraphHandler830G1CurrentAndPinnedAreDisjoint(t *testing.T) {
	t.Parallel()
	gin.SetMode(gin.TestMode)
	for _, test := range []struct {
		name          string
		query         string
		wantCurrent   int
		wantPinned    int
		wantReleaseID []string
	}{
		{name: "current", wantCurrent: 1},
		{name: "pinned", query: "?release_id=release-exact", wantPinned: 1, wantReleaseID: []string{"release-exact"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &entityPageGraphHTTPService830G1Spy{result: &service.EntityPageGraphRead830G1{
				Contract: "entity-page-read.830.g1.v1", ReadMode: test.name,
				ReleaseID: "release-exact", ActivationEpoch: 2,
			}}
			engine := entityPageGraphHandlerEngine830G1(spy)
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(
				http.MethodGet,
				"/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/schema/entities/entity-1/fields/field-1"+test.query,
				nil,
			)
			engine.ServeHTTP(recorder, request)
			require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
			require.Equal(t, test.wantCurrent, spy.currentCalls)
			require.Equal(t, test.wantPinned, spy.pinnedCalls)
			require.Equal(t, test.wantReleaseID, spy.releaseIDs)
		})
	}
}

func entityPageGraphHandlerEngine830G1(serviceSpy entityPageGraphHTTPService830G1) *gin.Engine {
	engine := gin.New()
	engine.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(7))
		ctx = types.WithPrincipal(ctx, principal)
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(7))
		c.Set(types.PrincipalContextKey.String(), principal)
		c.Next()
	})
	h := &EntityPageGraphHandler830G1{service: serviceSpy}
	engine.GET(
		"/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/entities/:entity_id/fields/:field_key",
		h.ReadField,
	)
	return engine
}
