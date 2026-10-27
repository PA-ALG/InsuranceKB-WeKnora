package enterprise_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

type referencePublisher struct {
	*publishStore
	references, members     int
	referenceErr, memberErr error
}

func (p *referencePublisher) ReleaseReference(_ context.Context, _ uint64, _, id string) (release.Reference, error) {
	p.references++
	if p.referenceErr != nil {
		return release.Reference{}, p.referenceErr
	}
	if id == "" {
		id = p.head.ReleaseID
	}
	r, ok := p.releases[id]
	if !ok {
		return release.Reference{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return release.Reference{ID: r.ID, Retired: r.RetiredAt != nil}, nil
}

func (p *referencePublisher) ReleaseByID(
	ctx context.Context, tenant uint64, space, id string,
) (release.Release, error) {
	p.members++
	if p.memberErr != nil {
		return release.Release{}, p.memberErr
	}
	return p.publishStore.ReleaseByID(ctx, tenant, space, id)
}

func conditionalGET(r http.Handler, path, tag string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, path, nil)
	req.Header.Set("X-API-Key", "test-key")
	if tag != "" {
		req.Header.Set("If-None-Match", tag)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func referenceRouter(t testing.TB, p *referencePublisher, session bool, allowed *bool) (http.Handler, string) {
	t.Helper()
	svc := release.NewService(p, nil, nil, release.WithPublisher(p))
	if !session {
		return mountRouter(svc, machineKey()), spacePath + "/releases/"
	}
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, browser.tenant)
		ctx = types.WithPrincipal(ctx, browser.principal)
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), browser.tenant)
		c.Set(types.PrincipalContextKey.String(), browser.principal)
		c.Next()
	})
	enterprise.MountSessionReads(r.Group("/api/v1/enterprise"), enterprise.SessionDeps{
		Candidates: svc, Spaces: spaceDirectory{7: {"demo"}},
	}, func(c *gin.Context) {
		if !*allowed {
			c.AbortWithStatus(http.StatusForbidden)
			return
		}
		c.Next()
	})
	return r, "/api/v1/enterprise/spaces/demo/view/releases/"
}

func newReferencePublisher() *referencePublisher {
	p := &referencePublisher{publishStore: newPublishStore()}
	p.releases["r1"] = release.Release{ID: "r1", Members: []release.Member{
		{LogicalSlug: "visible", AccessScope: "space", Payload: []byte(`{"value":1}`)},
		{LogicalSlug: "hidden", AccessScope: "private", Payload: []byte(`{"value":2}`)},
	}}
	p.releases["r2"] = release.Release{ID: "r2"}
	p.head = release.Head{ReleaseID: "r1"}
	return p
}

func TestReleaseConditionalReadsKeepHeadersFreshWithoutLoadingMembers(t *testing.T) {
	for _, session := range []bool{false, true} {
		t.Run(map[bool]string{false: "service", true: "session"}[session], func(t *testing.T) {
			p, allowed := newReferencePublisher(), true
			r, path := referenceRouter(t, p, session, &allowed)
			w := conditionalGET(r, path+"r1", "")
			require.Equal(t, http.StatusOK, w.Code, w.Body.String())
			require.Equal(t, `"r1"`, w.Header().Get("ETag"))
			require.Equal(t, "private, no-cache", w.Header().Get("Cache-Control"))
			require.Contains(t, w.Header().Get("Vary"), "Authorization")
			if session {
				require.NotContains(t, w.Body.String(), "hidden")
			}
			require.Equal(t, 1, p.members)
			for _, tag := range []string{`"r1"`, `W/"r1"`, `"other", W/"r1"`, "*"} {
				w = conditionalGET(r, path+"r1", tag)
				require.Equal(t, http.StatusNotModified, w.Code)
				require.Empty(t, w.Body.Bytes())
				require.Equal(t, `"r1"`, w.Header().Get("ETag"))
				require.Equal(t, "private, no-cache", w.Header().Get("Cache-Control"))
			}
			require.Equal(t, 1, p.members, "304 must not load or encode the member body")
			require.Equal(t, 4, p.references)
			now := time.Now()
			retired := p.releases["r1"]
			retired.RetiredAt = &now
			p.releases["r1"] = retired
			w = conditionalGET(r, path+"r1", `"r1"`)
			require.Equal(t, http.StatusOK, w.Code)
			require.Equal(t, `"r1;retired"`, w.Header().Get("ETag"))
			require.Equal(t, 2, p.members)
			require.Equal(t, http.StatusNotModified, conditionalGET(r, path+"r1", `"r1;retired"`).Code)
			require.Equal(t, 2, p.members)
		})
	}
}

func TestReleaseConditionalActiveFollowsHeadAndAuthorization(t *testing.T) {
	p, allowed := newReferencePublisher(), true
	r, path := referenceRouter(t, p, true, &allowed)
	require.Equal(t, http.StatusNotModified, conditionalGET(r, path+"active", `"r1"`).Code)
	require.Zero(t, p.members)
	p.head.ReleaseID = "r2"
	w := conditionalGET(r, path+"active", `"r1"`)
	require.Equal(t, http.StatusOK, w.Code)
	require.Equal(t, `"r2"`, w.Header().Get("ETag"))
	require.Equal(t, "r2", data(t, w.Body.Bytes())["id"])
	allowed = false
	refs, members := p.references, p.members
	for _, id := range []string{"r2", "active"} {
		w = conditionalGET(r, path+id, `"r2"`)
		require.Equal(t, http.StatusForbidden, w.Code)
		require.Empty(t, w.Header().Get("ETag"))
		require.Empty(t, w.Header().Get("Cache-Control"))
	}
	require.Equal(t, refs, p.references, "authorization precedes even the header query")
	require.Equal(t, members, p.members)
}

func TestReleaseConditionalErrorsHaveNoValidators(t *testing.T) {
	p, allowed := newReferencePublisher(), true
	r, path := referenceRouter(t, p, true, &allowed)
	for _, tag := range []string{"", "*", `"missing"`} {
		w := conditionalGET(r, path+"missing", tag)
		require.Equal(t, http.StatusNotFound, w.Code)
		require.Empty(t, w.Header().Get("ETag"))
		require.Empty(t, w.Header().Get("Cache-Control"))
	}
	p.referenceErr = errors.New("header unavailable")
	w := conditionalGET(r, path+"r1", `"r1"`)
	require.GreaterOrEqual(t, w.Code, 500)
	require.Empty(t, w.Header().Get("ETag"))
	p.referenceErr, p.memberErr = nil, errors.New("members unavailable")
	w = conditionalGET(r, path+"r1", `"old"`)
	require.GreaterOrEqual(t, w.Code, 500)
	require.Empty(t, w.Header().Get("ETag"))
	require.Empty(t, w.Header().Get("Cache-Control"))
}

func TestCitedFileCacheHeadersOnlyAfterSuccess(t *testing.T) {
	for _, path := range []string{
		filePath, releasePath + "/sources/k-1/attempts/3/file", releasePath + "/sources/unknown/attempts/2/file",
	} {
		w := get(newCitationWorld(t).router(t, machineKey()), path)
		if path == filePath {
			require.Equal(t, http.StatusOK, w.Code)
			require.Equal(t, "private, no-cache", w.Header().Get("Cache-Control"))
		} else {
			require.GreaterOrEqual(t, w.Code, 400)
			require.Empty(t, w.Header().Get("Cache-Control"))
			require.Empty(t, w.Header().Get("ETag"))
		}
	}
}

// Offline comparison isolates response encoding and transfer bytes; it does not
// claim to measure PostgreSQL, browser rendering, compression or production latency.
func BenchmarkReleaseConditionalResponse(b *testing.B) {
	for _, condition := range []string{"", `"r1"`} {
		name := "full"
		if condition != "" {
			name = "not_modified"
		}
		b.Run(name, func(b *testing.B) {
			p, allowed := newReferencePublisher(), true
			r1 := p.releases["r1"]
			r1.Members[0].Payload = []byte(`{"text":"` + strings.Repeat("a", 10<<20) + `"}`)
			p.releases["r1"] = r1
			r, path := referenceRouter(b, p, true, &allowed)
			b.ReportAllocs()
			b.ResetTimer()
			var bodyBytes int
			for i := 0; i < b.N; i++ {
				w := conditionalGET(r, path+"r1", condition)
				bodyBytes = w.Body.Len()
			}
			b.ReportMetric(float64(bodyBytes), "body_bytes/op")
			b.ReportMetric(float64(p.members)/float64(b.N), "member_loads/op")
		})
	}
}
