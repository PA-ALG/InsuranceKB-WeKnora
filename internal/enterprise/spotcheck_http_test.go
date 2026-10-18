package enterprise_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

const spotPath = "/api/v1/enterprise/spaces/demo"

type httpSpotRow struct {
	tenant uint64
	spotcheck.Sample
}

type httpSpotStore struct {
	rows              []httpSpotRow
	fail              error
	tenant, execution uint64
	caller            types.Caller
	grant             any
	done              <-chan struct{}
	calls             int
}

func (s *httpSpotStore) observe(ctx context.Context, tenant uint64) {
	s.calls++
	s.tenant = tenant
	s.execution, _ = types.TenantIDFromContext(ctx)
	s.caller, s.grant, s.done = types.CallerFromContext(ctx), ctx.Value(sessionGrantKey{}), ctx.Done()
}

func (s *httpSpotStore) InsertSamples(
	_ context.Context, tenant uint64, in []spotcheck.Sample,
) ([]spotcheck.Sample, error) {
	if s.fail != nil {
		return nil, s.fail
	}
	out := make([]spotcheck.Sample, 0, len(in))
	for _, v := range in {
		kept := v
		found := false
		for _, row := range s.rows {
			if row.tenant == tenant && row.SpaceID == v.SpaceID &&
				row.ReleaseID == v.ReleaseID && row.LogicalSlug == v.LogicalSlug {
				kept, found = row.Sample, true
				break
			}
		}
		if !found {
			s.rows = append(s.rows, httpSpotRow{tenant, v})
		}
		out = append(out, kept)
	}
	return out, nil
}

func (s *httpSpotStore) ListSamples(
	ctx context.Context, tenant uint64, space string, f spotcheck.Filter,
) ([]spotcheck.Sample, error) {
	s.observe(ctx, tenant)
	if s.fail != nil {
		return nil, s.fail
	}
	var out []spotcheck.Sample
	for _, row := range s.rows {
		if row.tenant != tenant || row.SpaceID != space || (f.ReleaseID != "" && row.ReleaseID != f.ReleaseID) {
			continue
		}
		if (f.Status == "pending" && row.Verdict != nil) || (f.Status == "decided" && row.Verdict == nil) {
			continue
		}
		out = append(out, row.Sample)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].CreatedAt.Equal(out[j].CreatedAt) {
			return out[i].ID < out[j].ID
		}
		return out[i].CreatedAt.Before(out[j].CreatedAt)
	})
	return out, nil
}

func (s *httpSpotStore) SampleByID(
	ctx context.Context, tenant uint64, space, id string,
) (spotcheck.Sample, bool, error) {
	s.observe(ctx, tenant)
	if s.fail != nil {
		return spotcheck.Sample{}, false, s.fail
	}
	for _, row := range s.rows {
		if row.tenant == tenant && row.SpaceID == space && row.ID == id {
			return row.Sample, true, nil
		}
	}
	return spotcheck.Sample{}, false, nil
}

func (s *httpSpotStore) AppendVerdict(ctx context.Context, tenant uint64, space string, v spotcheck.Verdict) error {
	s.observe(ctx, tenant)
	if s.fail != nil {
		return s.fail
	}
	for i, row := range s.rows {
		if row.tenant == tenant && row.SpaceID == space && row.ID == v.SampleID {
			s.rows[i].Verdict = &v
			return nil
		}
	}
	return errors.New("unscoped sample")
}

type httpSpotWorld struct {
	store      *httpSpotStore
	service    *spotcheck.Service
	releases   *publishStore
	candidates *release.Service
	spaces     enterprise.SpaceDirectory
}

func newHTTPSpotWorld(t *testing.T) *httpSpotWorld {
	t.Helper()
	releases := sessionWorld(t).store
	candidates := publishService(t, releases)
	store, next := &httpSpotStore{}, 0
	service := spotcheck.NewService(store, candidates, spotcheck.WithIDs(func() string {
		next++
		return fmt.Sprintf("sample-%03d", next)
	}))
	return &httpSpotWorld{
		store: store, service: service, releases: releases, candidates: candidates,
		spaces: spaceDirectory{7: {"demo"}},
	}
}

func (w *httpSpotWorld) seed(t *testing.T) []spotcheck.Sample {
	t.Helper()
	got, err := w.service.Submit(
		context.Background(), release.Principal{TenantID: 7, Subject: "service"}, "demo", "release-1",
		[]spotcheck.SampleInput{
			{Slug: "1828/waiting_period", Stratum: "visible"}, {Slug: "restricted/rule", Stratum: "hidden"},
		},
	)
	require.NoError(t, err)
	return got
}

func (w *httpSpotWorld) apiRouter(key *types.TenantAPIKey) *gin.Engine {
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: key}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	group := r.Group("/api/v1/enterprise", gate.Middleware())
	enterprise.Mount(group.Group("/spaces/:space_id"), enterprise.Deps{Authorizer: gate, SpotChecks: w.service})
	deps := enterprise.SessionDeps{Candidates: w.candidates, SpotChecks: w.service, Spaces: w.spaces}
	enterprise.MountSessionReads(group, deps)
	enterprise.MountSessionSpotChecks(group, deps)
	return r
}

func (w *httpSpotWorld) sessionRouter(who identity, mutate func(*gin.Context), guards ...gin.HandlerFunc) *gin.Engine {
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, who.tenant)
		ctx = types.WithPrincipal(ctx, who.principal)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: who.tenant, UserID: "user-1", Role: types.TenantRoleViewer})
		if who.apiKey {
			ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 3, FullAccess: true})
		}
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), who.tenant)
		c.Set(types.PrincipalContextKey.String(), who.principal)
		if mutate != nil {
			mutate(c)
		}
		c.Next()
	})
	group := r.Group("/api/v1/enterprise")
	gate := middleware.NewAPIKeyRouteAuthorizer()
	enterprise.Mount(group.Group("/spaces/:space_id"), enterprise.Deps{Authorizer: gate, SpotChecks: w.service})
	deps := enterprise.SessionDeps{Candidates: w.candidates, SpotChecks: w.service, Spaces: w.spaces}
	enterprise.MountSessionReads(group, deps, guards...)
	enterprise.MountSessionSpotChecks(group, deps, guards...)
	return r
}

func spotSamples(t *testing.T, body []byte) []spotcheck.Sample {
	t.Helper()
	got := data(t, body)
	encoded, err := json.Marshal(got["samples"])
	require.NoError(t, err)
	require.NotEqual(t, "null", string(encoded), "an empty list must be []")
	var samples []spotcheck.Sample
	require.NoError(t, json.Unmarshal(encoded, &samples))
	return samples
}

func TestSpotCheckHTTPFourEndpointsAndPinnedVisibility(t *testing.T) {
	w := newHTTPSpotWorld(t)
	api := w.apiRouter(machineKey())
	res := request(api, http.MethodGet, spotPath+"/samples", "test-key", nil)
	require.Equal(t, 200, res.Code, res.Body.String())
	require.Empty(t, spotSamples(t, res.Body.Bytes()))
	res = request(w.sessionRouter(browser, nil), http.MethodGet, spotPath+"/view/samples", "", nil)
	require.Equal(t, 200, res.Code, res.Body.String())
	require.Empty(t, spotSamples(t, res.Body.Bytes()))
	body := []byte(`{"samples":[{"slug":"1828/waiting_period","stratum":"visible"},` +
		`{"slug":"restricted/rule","stratum":"hidden"}]}`)
	res = request(api, http.MethodPost, spotPath+"/releases/release-1/samples", "test-key", body)
	require.Equal(t, 201, res.Code, res.Body.String())
	samples := spotSamples(t, res.Body.Bytes())
	require.Len(t, samples, 2)
	require.Equal(t, "release-1", samples[0].ReleaseID)
	require.Equal(t, w.releases.releases["release-1"].Members[0].MemberDigest, samples[0].MemberDigest)
	w.releases.head.ReleaseID = "release-2"
	w.releases.releases["release-2"] = release.Release{
		ID: "release-2", Members: []release.Member{{LogicalSlug: "restricted/rule", AccessScope: "space"}},
	}
	session := w.sessionRouter(browser, nil)
	res = request(session, http.MethodGet, spotPath+"/view/samples", "", nil)
	require.Equal(t, 200, res.Code, res.Body.String())
	visible := spotSamples(t, res.Body.Bytes())
	require.Len(t, visible, 1)
	require.Equal(t, samples[0].ID, visible[0].ID)
	res = request(
		session, http.MethodPost, spotPath+"/view/samples/"+samples[0].ID+"/verdicts", "",
		[]byte(`{"outcome":"correct","note":" checked "}`),
	)
	require.Equal(t, 201, res.Code, res.Body.String())
	verdict := data(t, res.Body.Bytes())["verdict"].(map[string]any)
	require.Equal(t, browser.principal.StorageID(), verdict["reviewer"])
	require.Equal(t, "checked", verdict["note"])
	res = request(
		session, http.MethodPost, spotPath+"/view/samples/"+samples[1].ID+"/verdicts", "",
		[]byte(`{"outcome":"correct"}`),
	)
	require.Equal(t, 404, res.Code, res.Body.String())
	require.Equal(t, spotcheck.ErrorSampleNotFound, code(t, res.Body.Bytes()))
	res = request(api, http.MethodGet, spotPath+"/samples?status=decided&release=release-1", "test-key", nil)
	require.Equal(t, 200, res.Code, res.Body.String())
	require.Len(t, spotSamples(t, res.Body.Bytes()), 1)
	res = request(api, http.MethodGet, spotPath+"/samples", "test-key", nil)
	require.Len(t, spotSamples(t, res.Body.Bytes()), 2, "session filtering must not mutate API service")
}

func TestSpotCheckRoutesReturn503WhenUnconfigured(t *testing.T) {
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: machineKey()}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	enterprise.Mount(r.Group("/api/v1/spaces/:space_id", gate.Middleware()), enterprise.Deps{
		Authorizer: gate, SpotChecks: nil,
	})
	w := request(r, http.MethodGet, spacePath+"/samples", "test-key", nil)
	require.Equal(t, http.StatusServiceUnavailable, w.Code, w.Body.String())
	w = request(r, http.MethodPost, spacePath+"/releases/release-1/samples", "test-key", []byte(`{"samples":[]}`))
	require.Equal(t, http.StatusServiceUnavailable, w.Code, w.Body.String())
}

func TestSpotCheckSessionRoutesReturn503BeforeSpaceLookupWhenUnconfigured(t *testing.T) {
	for _, directory := range []enterprise.SpaceDirectory{nil, spaceDirectory{}, spaceDirectory{7: {"demo"}}} {
		world := newHTTPSpotWorld(t)
		world.service, world.spaces = nil, directory
		guardRan := false
		router := world.sessionRouter(browser, nil, func(c *gin.Context) { guardRan = true; c.Next() })
		for _, route := range []struct{ method, path string }{
			{http.MethodGet, spotPath + "/view/samples"},
			{http.MethodPost, spotPath + "/view/samples/sample-1/verdicts"},
		} {
			res := request(router, route.method, route.path, "", []byte(`{"outcome":"correct"}`))
			require.Equal(t, http.StatusServiceUnavailable, res.Code, res.Body.String())
			require.Equal(t, "SERVICE_UNAVAILABLE", code(t, res.Body.Bytes()))
		}
		require.False(t, guardRan)
	}
}
