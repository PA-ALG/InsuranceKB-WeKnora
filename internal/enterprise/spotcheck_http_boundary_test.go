package enterprise_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestSpotCheckHTTPStrictSampleJSON(t *testing.T) {
	for name, body := range map[string]string{
		"null": `null`, "array": `[]`, "scalar": `true`, "truncated": `{"samples":`,
		"trailing document": `{"samples":[]} {}`, "trailing junk": `{"samples":[]} xyz`,
		"unknown": `{"samples":[],"digest":"forged"}`,
		"unknown nested": `{"samples":[{"slug":"1828/waiting_period",` +
			`"stratum":"s","member_digest":"forged"}]}`,
		"duplicate root":         `{"samples":[],"samples":[]}`,
		"escaped duplicate root": `{"samples":[],"sampl\u0065s":[]}`,
		"duplicate nested": `{"samples":[{"slug":"1828/waiting_period",` +
			`"slug":"restricted/rule","stratum":"s"}]}`,
		"escaped duplicate nested": `{"samples":[{"slug":"1828/waiting_period",` +
			`"sl\u0075g":"restricted/rule","stratum":"s"}]}`,
		"invalid UTF8": "{\"samples\":[{\"slug\":\"1828/waiting_period\",\"stratum\":\"\xff\"}]}",
	} {
		t.Run(name, func(t *testing.T) {
			world := newHTTPSpotWorld(t)
			res := request(
				world.apiRouter(machineKey()), http.MethodPost, spotPath+"/releases/release-1/samples",
				"test-key", []byte(body),
			)
			require.Equal(t, 400, res.Code, res.Body.String())
			require.Equal(t, spotcheck.ErrorSampleInvalid, code(t, res.Body.Bytes()))
			require.Empty(t, world.store.rows)
		})
	}
}

func TestSpotCheckHTTPStrictVerdictJSON(t *testing.T) {
	for name, body := range map[string]string{
		"null": `null`, "array": `[]`, "scalar": `"correct"`, "truncated": `{"outcome":`,
		"trailing document": `{"outcome":"correct"} {}`, "trailing junk": `{"outcome":"correct"} xyz`,
		"reviewer spoof":    `{"outcome":"correct","reviewer":"admin"}`,
		"unknown":           `{"outcome":"correct","extra":true}`,
		"duplicate":         `{"outcome":"wrong","outcome":"correct"}`,
		"escaped duplicate": `{"outcome":"wrong","outc\u006fme":"correct"}`,
		"nested duplicate":  `{"outcome":"correct","note":{"x":1,"x":2}}`,
		"invalid UTF8":      "{\"outcome\":\"correct\",\"note\":\"\xff\"}",
	} {
		t.Run(name, func(t *testing.T) {
			world := newHTTPSpotWorld(t)
			samples := world.seed(t)
			res := request(
				world.sessionRouter(browser, nil), http.MethodPost,
				spotPath+"/view/samples/"+samples[0].ID+"/verdicts", "", []byte(body),
			)
			require.Equal(t, 400, res.Code, res.Body.String())
			require.Equal(t, spotcheck.ErrorVerdictInvalid, code(t, res.Body.Bytes()))
			require.Nil(t, world.store.rows[0].Verdict)
		})
	}
}

func TestSpotCheckHTTPBodyByteLimits(t *testing.T) {
	for _, delta := range []int{0, 1} {
		t.Run("samples "+string(rune('0'+delta)), func(t *testing.T) {
			world := newHTTPSpotWorld(t)
			body := `{"samples":[{"slug":"1828/waiting_period","stratum":"s"}]}`
			body += strings.Repeat(" ", (256<<10)+delta-len(body))
			res := request(
				world.apiRouter(machineKey()), http.MethodPost, spotPath+"/releases/release-1/samples",
				"test-key", []byte(body),
			)
			if delta == 0 {
				require.Equal(t, 201, res.Code, res.Body.String())
			} else {
				require.Equal(t, 400, res.Code, res.Body.String())
				require.Equal(t, spotcheck.ErrorSampleInvalid, code(t, res.Body.Bytes()))
				require.Empty(t, world.store.rows)
			}
		})
		t.Run("verdict "+string(rune('0'+delta)), func(t *testing.T) {
			world := newHTTPSpotWorld(t)
			samples := world.seed(t)
			body := `{"outcome":"correct"}`
			body += strings.Repeat(" ", (64<<10)+delta-len(body))
			res := request(
				world.sessionRouter(browser, nil), http.MethodPost,
				spotPath+"/view/samples/"+samples[0].ID+"/verdicts", "", []byte(body),
			)
			if delta == 0 {
				require.Equal(t, 201, res.Code, res.Body.String())
			} else {
				require.Equal(t, 400, res.Code, res.Body.String())
				require.Equal(t, spotcheck.ErrorVerdictInvalid, code(t, res.Body.Bytes()))
				require.Nil(t, world.store.rows[0].Verdict)
			}
		})
	}
}

func TestSpotCheckHTTPRequiresFullServiceKeys(t *testing.T) {
	for name, key := range map[string]*types.TenantAPIKey{
		"readonly": {ID: 1, TenantID: machineKey().TenantID, Capabilities: types.StringArray{"retrieve"}},
		"KB restricted": {
			ID: 1, TenantID: machineKey().TenantID, FullAccess: true,
			KnowledgeBaseIDs: types.StringArray{"wiki-demo"},
		},
	} {
		t.Run(name, func(t *testing.T) {
			world := newHTTPSpotWorld(t)
			router := world.apiRouter(key)
			for _, route := range []struct{ method, path, body string }{
				{http.MethodGet, spotPath + "/samples", ""},
				{
					http.MethodPost, spotPath + "/releases/release-1/samples",
					`{"samples":[{"slug":"1828/waiting_period","stratum":"s"}]}`,
				},
			} {
				res := request(router, route.method, route.path, "test-key", []byte(route.body))
				require.Equal(t, 403, res.Code, res.Body.String())
			}
			require.Empty(t, world.store.rows)
			require.Zero(t, world.store.calls)
		})
	}
	world := newHTTPSpotWorld(t)
	for _, apiKey := range []string{"", "invalid"} {
		res := request(world.apiRouter(machineKey()), http.MethodGet, spotPath+"/samples", apiKey, nil)
		require.Equal(t, 401, res.Code, res.Body.String())
	}
}

func TestSpotCheckHTTPKeyAndSessionRoutesStaySeparate(t *testing.T) {
	world := newHTTPSpotWorld(t)
	samples := world.seed(t)
	for _, who := range []identity{
		{tenant: 7, principal: types.Principal{Type: types.PrincipalAPITenant, ID: "7"}, apiKey: true},
		{tenant: 7, principal: browser.principal, apiKey: true},
		{tenant: 7, principal: types.Principal{Type: types.PrincipalEmbedVisitor, ID: "guest"}},
	} {
		router := world.sessionRouter(who, nil)
		res := request(router, http.MethodGet, spotPath+"/view/samples", "", nil)
		require.Equal(t, 403, res.Code, res.Body.String())
		res = request(
			router, http.MethodPost, spotPath+"/view/samples/"+samples[0].ID+"/verdicts", "",
			[]byte(`{"outcome":"correct"}`),
		)
		require.Equal(t, 403, res.Code, res.Body.String())
	}
	res := request(world.sessionRouter(browser, nil), http.MethodGet, spotPath+"/samples", "", nil)
	require.Equal(t, 403, res.Code, res.Body.String())
}

func TestSpotCheckHTTPRejectsUntrustedContexts(t *testing.T) {
	for name, mutate := range map[string]func(*gin.Context){
		"tenant disagreement": func(c *gin.Context) { c.Set(types.TenantIDContextKey.String(), uint64(8)) },
		"missing Gin tenant":  func(c *gin.Context) { delete(c.Keys, types.TenantIDContextKey.String()) },
		"principal disagreement": func(c *gin.Context) {
			c.Set(types.PrincipalContextKey.String(), types.Principal{Type: types.PrincipalWebUser, ID: "other"})
		},
		"malformed key context": func(c *gin.Context) {
			c.Request = c.Request.WithContext(context.WithValue(
				c.Request.Context(), types.TenantAPIKeyScopeContextKey, "invalid",
			))
		},
	} {
		t.Run(name, func(t *testing.T) {
			world := newHTTPSpotWorld(t)
			world.seed(t)
			for _, route := range []struct{ method, path string }{
				{http.MethodGet, spotPath + "/view/samples"},
				{http.MethodPost, spotPath + "/view/samples/sample-001/verdicts"},
			} {
				res := request(
					world.sessionRouter(browser, mutate), route.method, route.path, "", []byte(`{"outcome":"correct"}`),
				)
				require.Equal(t, 403, res.Code, res.Body.String())
				require.Equal(t, release.ErrorReleaseAccessDenied, code(t, res.Body.Bytes()))
			}
			keyIdentity := identity{
				tenant: 7, principal: types.Principal{Type: types.PrincipalAPITenant, ID: "7"}, apiKey: true,
			}
			for _, route := range []struct{ method, path string }{
				{http.MethodGet, spotPath + "/samples"}, {http.MethodPost, spotPath + "/releases/release-1/samples"},
			} {
				res := request(
					world.sessionRouter(keyIdentity, mutate), route.method, route.path, "",
					[]byte(`{"samples":[{"slug":"1828/waiting_period","stratum":"s"}]}`),
				)
				require.Equal(t, 403, res.Code, res.Body.String())
				require.Equal(t, release.ErrorReleaseAccessDenied, code(t, res.Body.Bytes()))
			}
			require.Zero(t, world.store.calls)
		})
	}
}

func TestSpotCheckHTTPSessionPreservesOriginalCallerAndGuardContext(t *testing.T) {
	world := newHTTPSpotWorld(t)
	samples := world.seed(t)
	guard := func(c *gin.Context) {
		ctx := types.WithExecutionTenant(c.Request.Context(), 8)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: 8, UserID: "foreign"})
		ctx = context.WithValue(ctx, sessionGrantKey{}, "granted")
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(8))
		c.Next()
	}
	router := world.sessionRouter(browser, nil, guard)
	for _, route := range []struct{ method, path string }{
		{http.MethodGet, spotPath + "/view/samples"},
		{http.MethodPost, spotPath + "/view/samples/" + samples[0].ID + "/verdicts"},
	} {
		ctx, cancel := context.WithCancel(context.Background())
		req := httptest.NewRequest(
			route.method, route.path, strings.NewReader(`{"outcome":"correct"}`),
		).WithContext(ctx)
		res := httptest.NewRecorder()
		router.ServeHTTP(res, req)
		require.Contains(t, []int{200, 201}, res.Code, res.Body.String())
		require.Equal(t, uint64(7), world.store.tenant)
		require.Equal(t, uint64(7), world.store.execution)
		require.Equal(t, types.Caller{TenantID: 7, UserID: "user-1", Role: types.TenantRoleViewer}, world.store.caller)
		require.Equal(t, "granted", world.store.grant)
		require.Equal(t, ctx.Done(), world.store.done)
		cancel()
	}
	require.Equal(t, browser.principal.StorageID(), world.store.rows[0].Verdict.Reviewer)
}

func TestSpotCheckHTTPTypedAndUnknownErrors(t *testing.T) {
	world := newHTTPSpotWorld(t)
	samples := world.seed(t)
	for _, route := range []struct {
		method, path, body, code string
		status                   int
	}{
		{http.MethodGet, spotPath + "/samples?status=invalid", "", spotcheck.ErrorSampleInvalid, 400},
		{
			http.MethodPost, spotPath + "/releases/active/samples",
			`{"samples":[{"slug":"1828/waiting_period","stratum":"s"}]}`, release.ErrorReleaseNotFound, 404,
		},
		{
			http.MethodPost, spotPath + "/releases/release-1/samples",
			`{"samples":[{"slug":"missing","stratum":"s"}]}`, release.ErrorMemberNotFound, 404,
		},
	} {
		res := request(world.apiRouter(machineKey()), route.method, route.path, "test-key", []byte(route.body))
		require.Equal(t, route.status, res.Code, res.Body.String())
		require.Equal(t, route.code, code(t, res.Body.Bytes()))
	}
	for _, route := range []struct {
		path, body, code string
		status           int
	}{
		{
			spotPath + "/view/samples/" + samples[0].ID + "/verdicts",
			`{"outcome":"invalid"}`, spotcheck.ErrorVerdictInvalid, 400,
		},
		{spotPath + "/view/samples/missing/verdicts", `{"outcome":"correct"}`, spotcheck.ErrorSampleNotFound, 404},
		{
			strings.Replace(spotPath, "demo", "foreign", 1) + "/view/samples/" + samples[0].ID + "/verdicts",
			`{"outcome":"correct"}`, release.ErrorReleaseNotFound, 404,
		},
	} {
		res := request(world.sessionRouter(browser, nil), http.MethodPost, route.path, "", []byte(route.body))
		require.Equal(t, route.status, res.Code, res.Body.String())
		require.Equal(t, route.code, code(t, res.Body.Bytes()))
	}
	world.store.fail = errors.New("postgres private-address secret detail")
	for _, route := range []struct{ method, path, key, body string }{
		{http.MethodGet, spotPath + "/samples", "test-key", ""},
		{
			http.MethodPost, spotPath + "/releases/release-1/samples", "test-key",
			`{"samples":[{"slug":"1828/waiting_period","stratum":"s"}]}`,
		},
		{http.MethodGet, spotPath + "/view/samples", "", ""},
		{http.MethodPost, spotPath + "/view/samples/" + samples[0].ID + "/verdicts", "", `{"outcome":"correct"}`},
	} {
		router := world.sessionRouter(browser, nil)
		if route.key != "" {
			router = world.apiRouter(machineKey())
		}
		res := request(router, route.method, route.path, route.key, []byte(route.body))
		require.Equal(t, 500, res.Code, res.Body.String())
		require.Equal(t, "INTERNAL_ERROR", code(t, res.Body.Bytes()))
		require.NotContains(t, res.Body.String(), "private-address")
		require.NotContains(t, res.Body.String(), "secret")
	}
}

func TestSpotCheckHTTPKeepsSameNamedSpacesInDifferentTenantsApart(t *testing.T) {
	world := newHTTPSpotWorld(t)
	samples := world.seed(t)
	world.spaces = spaceDirectory{7: {"demo"}, 8: {"demo"}}
	other := identity{tenant: 8, principal: types.Principal{Type: types.PrincipalWebUser, ID: "user-2"}}
	res := request(world.sessionRouter(other, nil), http.MethodGet, spotPath+"/view/samples", "", nil)
	require.Equal(t, 200, res.Code, res.Body.String())
	require.Empty(t, spotSamples(t, res.Body.Bytes()))
	res = request(
		world.sessionRouter(other, nil), http.MethodPost,
		spotPath+"/view/samples/"+samples[0].ID+"/verdicts", "", []byte(`{"outcome":"correct"}`),
	)
	require.Equal(t, 404, res.Code, res.Body.String())
	require.Equal(t, spotcheck.ErrorSampleNotFound, code(t, res.Body.Bytes()))
	tenant := uint64(8)
	res = request(
		world.apiRouter(&types.TenantAPIKey{ID: 1, TenantID: &tenant, FullAccess: true}),
		http.MethodGet, spotPath+"/samples", "test-key", nil,
	)
	require.Equal(t, 200, res.Code, res.Body.String())
	require.Empty(t, spotSamples(t, res.Body.Bytes()))
	require.Nil(t, world.store.rows[0].Verdict)
}
