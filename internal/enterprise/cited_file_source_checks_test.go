package enterprise_test

// Issue #375 R1 acceptance (protected, written by Claude): before a 304, the cited file route runs
// the same live source check the full response runs (releasestore.SourceFiles: the knowledge
// exists, is not deleted, still belongs to this tenant's and Space's RAW KB; lookup errors fail
// closed). A withdrawn source is refused with or without If-None-Match. A valid 304 closes the
// opened file without reading it.

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

// liveSources is the knowledge lookup and file store behind the real SourceFiles check.
type liveSources struct {
	knowledge            map[string]*types.Knowledge
	lookupErr            error
	opens, reads, closes int
	lookups              int
}

func newLiveSources() *liveSources {
	return &liveSources{knowledge: map[string]*types.Knowledge{
		"k-1": {ID: "k-1", TenantID: 7, KnowledgeBaseID: "raw-1"},
	}}
}

func (s *liveSources) GetKnowledgeByID(_ context.Context, _ uint64, id string) (*types.Knowledge, error) {
	s.lookups++
	if s.lookupErr != nil {
		return nil, s.lookupErr
	}
	k, ok := s.knowledge[id]
	if !ok {
		return nil, repository.ErrKnowledgeNotFound
	}
	return k, nil
}

func (s *liveSources) GetKnowledgeFile(_ context.Context, _ string) (io.ReadCloser, string, error) {
	s.opens++
	return &countedFile{sources: s, data: pdfBytes}, "保险条款.pdf", nil
}

type countedFile struct {
	sources *liveSources
	data    []byte
}

func (f *countedFile) Read(p []byte) (int, error) {
	f.sources.reads++
	if len(f.data) == 0 {
		return 0, io.EOF
	}
	n := copy(p, f.data)
	f.data = f.data[n:]
	return n, nil
}

func (f *countedFile) Close() error {
	f.sources.closes++
	return nil
}

func (s *liveSources) files(t *testing.T) enterprise.SourceFiles {
	t.Helper()
	spaces, err := releasestore.ParseSpaces(
		`[{"tenant_id":7,"space_id":"demo","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"}]`)
	require.NoError(t, err)
	return releasestore.SourceFiles(spaces, s, s)
}

func liveService(t *testing.T, world *citationWorld) *release.Service {
	t.Helper()
	schema, err := os.ReadFile("../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	return release.NewService(world.store, nil, map[string][]byte{"candidate_bundle": schema},
		release.WithPublisher(world.store))
}

// liveKeyRouter is the API key Mount of citationWorld.router with the real source check.
func liveKeyRouter(t *testing.T, world *citationWorld, live *liveSources) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: machineKey()}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	api := r.Group("/api/v1", gate.Middleware())
	enterprise.Mount(api.Group("/enterprise/spaces/:space_id"), enterprise.Deps{
		Candidates: liveService(t, world), Sources: source.NewService(world.pages), Authorizer: gate,
		Files: live.files(t),
	})
	return r
}

// liveSessionRouter is MountSessionReads of sessionRouter with the real source check.
func liveSessionRouter(t *testing.T, world *citationWorld, live *liveSources) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, browser.tenant)
		c.Set(types.TenantIDContextKey.String(), browser.tenant)
		c.Set(types.PrincipalContextKey.String(), browser.principal)
		c.Request = c.Request.WithContext(types.WithPrincipal(ctx, browser.principal))
		c.Next()
	})
	enterprise.MountSessionReads(r.Group("/api/v1/enterprise"), enterprise.SessionDeps{
		Candidates: liveService(t, world), Sources: source.NewService(world.pages),
		Spaces: spaceDirectory{7: {"demo"}}, Files: live.files(t),
	})
	return r
}

type liveRoute struct {
	name   string
	router func(*testing.T, *citationWorld, *liveSources) *gin.Engine
	path   string
	key    string
}

var liveRoutes = []liveRoute{
	{"api key", liveKeyRouter, filePath, "test-key"},
	{"session", liveSessionRouter, viewPath + "/release-1/sources/k-1/attempts/2/file", ""},
}

func liveGET(r http.Handler, route liveRoute, tag string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, route.path, nil)
	if route.key != "" {
		req.Header.Set("X-API-Key", route.key)
	}
	if tag != "" {
		req.Header.Set("If-None-Match", tag)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

// refusal is how a changed source is refused, identically with and without a validator.
type refusal struct {
	change func(*liveSources)
	status int
	code   string
}

func TestAWithdrawnSourceIsRefusedWithOrWithoutAValidator(t *testing.T) {
	notFound := func(change func(*liveSources)) refusal {
		return refusal{change, http.StatusNotFound, "SOURCE_NOT_FOUND"}
	}
	cases := map[string]refusal{
		"soft-deleted": notFound(func(s *liveSources) {
			s.knowledge["k-1"].DeletedAt = gorm.DeletedAt{Time: time.Unix(1, 0), Valid: true}
		}),
		"missing":        notFound(func(s *liveSources) { delete(s.knowledge, "k-1") }),
		"another RAW KB": notFound(func(s *liveSources) { s.knowledge["k-1"].KnowledgeBaseID = "raw-2" }),
		"another tenant": notFound(func(s *liveSources) { s.knowledge["k-1"].TenantID = 8 }),
		"lookup failure": {
			func(s *liveSources) { s.lookupErr = errors.New("lookup unavailable") },
			http.StatusServiceUnavailable, "SOURCE_UNAVAILABLE",
		},
	}
	for _, route := range liveRoutes {
		for name, c := range cases {
			t.Run(route.name+" "+name, func(t *testing.T) {
				for _, tag := range []string{"", `"` + pdfSHA + `"`, "*"} {
					world, live := newCitationWorld(t), newLiveSources()
					if route.name == "session" {
						world = sessionWorld(t)
					}
					c.change(live)
					w := liveGET(route.router(t, world, live), route, tag)
					require.Equal(t, c.status, w.Code, "validator %q: %s", tag, w.Body.String())
					require.Equal(t, c.code, code(t, w.Body.Bytes()), tag)
					require.Empty(t, w.Header().Get("ETag"), tag)
					require.Empty(t, w.Header().Get("Cache-Control"), tag)
					require.Equal(t, 1, live.lookups, "the live check runs exactly once, validator %q", tag)
					require.Zero(t, live.opens, tag)
				}
			})
		}
	}
}

func TestAValid304OpensThenClosesTheFileWithoutReadingIt(t *testing.T) {
	for _, route := range liveRoutes {
		t.Run(route.name, func(t *testing.T) {
			world, live := newCitationWorld(t), newLiveSources()
			if route.name == "session" {
				world = sessionWorld(t)
			}
			w := liveGET(route.router(t, world, live), route, `"`+pdfSHA+`"`)
			require.Equal(t, http.StatusNotModified, w.Code, w.Body.String())
			require.Empty(t, w.Body.Bytes())
			requireRevalidatedEveryTime(t, w)
			require.Equal(t, 1, live.lookups)
			require.Equal(t, 1, live.opens, "the 304 passes the same source check as the full read")
			require.Zero(t, live.reads, "a 304 never reads or hashes the file")
			require.Equal(t, 1, live.closes)

			full := newLiveSources()
			w = liveGET(route.router(t, world, full), route, "")
			require.Equal(t, http.StatusOK, w.Code, w.Body.String())
			require.Equal(t, pdfBytes, w.Body.Bytes())
			require.Positive(t, full.reads)
			require.Equal(t, 1, full.closes)
		})
	}
}
