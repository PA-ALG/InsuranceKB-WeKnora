package enterprise_test

// S3d-1 acceptance (protected, written by Claude): read-only enterprise routes for logged-in
// browser users (Spec docs/design/slices/S3d-1-会话只读接口.md §3.1). Session identities are
// injected the way middleware.applyAuthSession does. Reuses the citation fixtures of this
// package (newCitationWorld, releaseMember, data, code, pdfBytes). RED until S3d-1 implements it.

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

const viewPath = "/api/v1/enterprise/spaces/demo/view/releases"

var hiddenRef = "source:v1:k-9:1:" + strings.Repeat("cd", 32)

type spaceDirectory map[uint64][]string

func (d spaceDirectory) SpaceIDs(tenantID uint64) []string { return d[tenantID] }

func (d spaceDirectory) KnowledgeBases(tenantID uint64, spaceID string) (string, string, bool) {
	for _, id := range d[tenantID] {
		if id == spaceID {
			return "raw-" + id, "wiki-" + id, true
		}
	}
	return "", "", false
}

type identity struct {
	tenant    uint64
	principal types.Principal
	apiKey    bool
}

var browser = identity{tenant: 7, principal: types.Principal{Type: types.PrincipalWebUser, ID: "user-1"}}

// sessionWorld adds a member outside the "space" access scope to the citation fixtures.
func sessionWorld(t *testing.T) *citationWorld {
	t.Helper()
	world := newCitationWorld(t)
	hidden := releaseMember(t, "restricted/rule", "SOURCE_SUPPORTED", map[string]any{
		"source_ref": hiddenRef, "file_sha256": hiddenRef[len(hiddenRef)-64:], "quote": "受限", "access_scope": "board",
		"locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1, "start": 0, "end": 2},
	})
	hidden.EvidenceRefs = []string{hiddenRef}
	hidden.AccessScope = "board"
	r := world.store.releases["release-1"]
	r.Members = append(r.Members, hidden)
	world.store.releases["release-1"] = r
	return world
}

// sessionRouter mounts the session routes behind an injected identity, the way
// middleware.applyAuthSession sets tenant, principal and (for API keys) the key scope.
func sessionRouter(t *testing.T, world *citationWorld, who identity, guards ...gin.HandlerFunc) *gin.Engine {
	t.Helper()
	schema, err := os.ReadFile("../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	service := release.NewService(world.store, nil, map[string][]byte{"candidate_bundle": schema},
		release.WithPublisher(world.store))
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := c.Request.Context()
		if who.tenant != 0 {
			c.Set(types.TenantIDContextKey.String(), who.tenant)
			ctx = context.WithValue(ctx, types.TenantIDContextKey, who.tenant)
		}
		c.Set(types.PrincipalContextKey.String(), who.principal)
		ctx = types.WithPrincipal(ctx, who.principal)
		if who.apiKey {
			ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 3, FullAccess: true})
		}
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	})
	enterprise.MountSessionReads(r.Group("/api/v1/enterprise"), enterprise.SessionDeps{
		Candidates: service, Sources: source.NewService(world.pages),
		Spaces: spaceDirectory{7: {"alpha", "demo"}, 8: {"other"}},
		Files: func(_ context.Context, scope source.Scope, knowledgeID string) (io.ReadCloser, string, error) {
			world.opens = append(world.opens, scope)
			reader, ok := world.files[knowledgeID]
			if !ok {
				return nil, "", source.ErrNotFound
			}
			return io.NopCloser(reader), "保险条款.pdf", nil
		},
	}, guards...)
	return r
}

func read(r http.Handler, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path, nil))
	return w
}

func sessionCitation(member string) string {
	return viewPath + "/release-1/citation?" + url.Values{"member": {member}, "evidence": {"0"}}.Encode()
}

func memberSlugs(t *testing.T, body []byte) []string {
	t.Helper()
	members, _ := data(t, body)["members"].([]any)
	slugs := make([]string, 0, len(members))
	for _, m := range members {
		slugs = append(slugs, m.(map[string]any)["logical_slug"].(string))
	}
	return slugs
}

func TestSessionUsersListTheSpacesOfTheirOwnTenant(t *testing.T) {
	w := read(sessionRouter(t, sessionWorld(t), browser), "/api/v1/enterprise/spaces")
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	var got struct {
		Data struct {
			Spaces []struct {
				SpaceID string `json:"space_id"`
			} `json:"spaces"`
		} `json:"data"`
	}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &got))
	ids := []string{}
	for _, s := range got.Data.Spaces {
		ids = append(ids, s.SpaceID)
	}
	require.Equal(t, []string{"alpha", "demo"}, ids, "another tenant's Space is never listed")
}

func TestSessionReleaseReadsOmitMembersOutsideTheSpaceScope(t *testing.T) {
	r := sessionRouter(t, sessionWorld(t), browser)
	for _, path := range []string{viewPath + "/release-1", viewPath + "/active"} {
		w := read(r, path)
		require.Equal(t, http.StatusOK, w.Code, path+" "+w.Body.String())
		slugs := memberSlugs(t, w.Body.Bytes())
		require.ElementsMatch(t, []string{"1828/waiting_period", "concept/waiting_period"}, slugs, path)
	}
}

func TestSessionCitationsAndFilesStayOnTheViewPaths(t *testing.T) {
	world := sessionWorld(t)
	r := sessionRouter(t, world, browser)

	w := read(r, sessionCitation("1828/waiting_period"))
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	got := data(t, w.Body.Bytes())
	require.Equal(t, "等待期为90日。", got["quote"])
	require.Equal(t, viewPath+"/release-1/sources/k-1/attempts/2/file", got["file"])
	require.Equal(t, source.Scope{TenantID: 7, SpaceID: "demo"}, world.pages.scope)

	w = read(r, viewPath+"/release-1/sources/k-1/attempts/2/file")
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Equal(t, pdfBytes, w.Body.Bytes())
	require.Equal(t, []source.Scope{{TenantID: 7, SpaceID: "demo"}}, world.opens)
}

func TestMembersOutsideTheSpaceScopeCannotBeOpened(t *testing.T) {
	world := sessionWorld(t)
	r := sessionRouter(t, world, browser)

	w := read(r, sessionCitation("restricted/rule"))
	require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
	require.Equal(t, release.ErrorMemberNotFound, code(t, w.Body.Bytes()))

	w = read(r, viewPath+"/release-1/sources/k-9/attempts/1/file")
	require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
	require.Equal(t, "SOURCE_NOT_FOUND", code(t, w.Body.Bytes()))
	require.Empty(t, world.opens, "a source only a hidden member cites is never opened")
}

func TestOnlyBrowserSessionsMayUseTheSessionRoutes(t *testing.T) {
	refused := map[string]identity{
		"full-access API key": {
			tenant: 7, principal: types.Principal{Type: types.PrincipalAPITenant, ID: "key-3"}, apiKey: true,
		},
		"web user carrying key": {tenant: 7, principal: browser.principal, apiKey: true},
		"non-browser principal": {tenant: 7, principal: types.Principal{Type: types.PrincipalEmbedVisitor, ID: "v-1"}},
		"no tenant":             {principal: browser.principal},
		"no principal id":       {tenant: 7, principal: types.Principal{Type: types.PrincipalWebUser}},
	}
	for name, who := range refused {
		t.Run(name, func(t *testing.T) {
			world := sessionWorld(t)
			guardRan := false
			guard := func(c *gin.Context) { guardRan = true; c.Next() }
			r := sessionRouter(t, world, who, guard)
			paths := []string{"/api/v1/enterprise/spaces", viewPath + "/active", sessionCitation("1828/waiting_period")}
			for _, path := range paths {
				w := read(r, path)
				require.Equal(t, http.StatusForbidden, w.Code, path)
				require.Equal(t, release.ErrorReleaseAccessDenied, code(t, w.Body.Bytes()), path)
			}
			require.False(t, guardRan, "the session check runs before any guard")
			require.Zero(t, world.pages.calls)
		})
	}
}

func TestViewGuardsRunInOrderOnViewRoutesOnly(t *testing.T) {
	world := sessionWorld(t)
	var order []string
	first := func(c *gin.Context) { order = append(order, "first"); c.Next() }
	second := func(c *gin.Context) { order = append(order, "second"); c.Next() }
	r := sessionRouter(t, world, browser, first, second)

	require.Equal(t, http.StatusOK, read(r, "/api/v1/enterprise/spaces").Code)
	require.Empty(t, order, "listing Spaces is not a view route")
	require.Equal(t, http.StatusOK, read(r, viewPath+"/active").Code)
	require.Equal(t, []string{"first", "second"}, order)

	blocked := sessionWorld(t)
	deny := func(c *gin.Context) {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"success": false, "code": "KB_ACCESS_DENIED"})
	}
	w := read(sessionRouter(t, blocked, browser, deny), sessionCitation("1828/waiting_period"))
	require.Equal(t, http.StatusForbidden, w.Code)
	require.Zero(t, blocked.pages.calls, "a guard that aborts stops the request before the service")
}

func TestSpacesOfOtherTenantsAndUnknownSpacesAreNotFound(t *testing.T) {
	for _, space := range []string{"other", "nope"} {
		t.Run(space, func(t *testing.T) {
			world := sessionWorld(t)
			guardRan := false
			guard := func(c *gin.Context) { guardRan = true; c.Next() }
			r := sessionRouter(t, world, browser, guard)
			w := read(r, "/api/v1/enterprise/spaces/"+space+"/view/releases/active")
			require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
			require.Equal(t, release.ErrorReleaseNotFound, code(t, w.Body.Bytes()))
			require.False(t, guardRan, "Space ownership is decided before the guards")
			require.Zero(t, world.pages.calls)
		})
	}
}
