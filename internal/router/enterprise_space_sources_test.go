// S4c-2c acceptance: the source pages route serves configured enterprise Spaces
// first and keeps the isolated G3 scope as the fallback, failing closed exactly as
// before (Spec §3.4). Protected file: written by Claude.
//
// RED until RouterParams.EnterpriseSpaces exists. Requests run through the
// production enterprise mount and API-key policy with an in-memory repository and
// an empty capture store, so 409 PARSE_ARTIFACT_NOT_CAPTURED proves the Space was
// resolved to its RAW KB and the exact attempt was found; 404 proves it was not.
package router

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const spaceSourceSpaces = `[
	{"tenant_id":7,"space_id":"space-a","raw_kb_id":"raw-a","wiki_kb_id":"wiki-a"},
	{"tenant_id":7,"space_id":"space-b","raw_kb_id":"raw-b","wiki_kb_id":"wiki-b"}
]`

// spaceSourceRepo holds one knowledge row whose attempt 2 has a committed revision.
type spaceSourceRepo struct {
	interfaces.KnowledgeRepository
	knowledge                     *types.Knowledge
	knowledgeCalls, revisionCalls int
	tenant                        uint64
	attempt                       int64
}

func (r *spaceSourceRepo) GetKnowledgeByID(_ context.Context, tenant uint64, id string) (*types.Knowledge, error) {
	r.knowledgeCalls++
	r.tenant = tenant
	if r.knowledge == nil || r.knowledge.ID != id || r.knowledge.TenantID != tenant {
		return nil, repository.ErrKnowledgeNotFound
	}
	k := *r.knowledge
	return &k, nil
}

func (r *spaceSourceRepo) GetRevision(_ context.Context, id string, attempt int64) (*types.KnowledgeRevision, error) {
	r.revisionCalls++
	r.attempt = attempt
	if r.knowledge == nil || id != r.knowledge.ID || attempt != 2 {
		return nil, repository.ErrKnowledgeNotFound
	}
	return &types.KnowledgeRevision{KnowledgeID: id, ParseAttempt: attempt, FileSHA256: strings.Repeat("a", 64)}, nil
}

func knowledgeIn(kb string) *spaceSourceRepo {
	return &spaceSourceRepo{knowledge: &types.Knowledge{
		ID: "source", TenantID: 7, KnowledgeBaseID: kb, FileName: "source.pdf", CurrentParseAttempt: 5,
	}}
}

type spaceCaller struct {
	tenant uint64
	key    types.TenantAPIKeyScope
}

var fullServiceKey = spaceCaller{tenant: 7, key: types.TenantAPIKeyScope{KeyID: 1, FullAccess: true}}

func spaceSourceRouter(t *testing.T, cfg *config.Config, repo *spaceSourceRepo, caller spaceCaller) *gin.Engine {
	t.Helper()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	spaces, err := releasestore.ParseSpaces(spaceSourceSpaces)
	require.NoError(t, err)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalAPITenant, ID: strconv.FormatUint(caller.tenant, 10)}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, caller.tenant)
		ctx = types.WithPrincipal(ctx, principal)
		ctx = types.WithTenantAPIKeyScope(ctx, caller.key)
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), caller.tenant)
		c.Set(types.PrincipalContextKey.String(), principal)
	})
	g := &rbacGuards{}
	v1 := r.Group("/api/v1", g.ensureAPIKeyAuthorizer().Middleware())
	registerEnterpriseRoutes(v1, RouterParams{
		Config: cfg, KnowledgeRepository: repo, FirstParseStore: service.NewG3FirstParseStore(nil),
		EnterpriseSpaces: spaces,
	}, g)
	g.assertAPIKeyPoliciesMatchRoutes(r)
	return r
}

func sourcePages(r *gin.Engine, space, attempt string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet,
		"/api/v1/enterprise/spaces/"+space+"/sources/source/attempts/"+attempt+"/pages", nil))
	return w
}

func TestEnterpriseSpaceSourcePagesResolveTheSpaceRawKB(t *testing.T) {
	repo := knowledgeIn("raw-a")
	w := sourcePages(spaceSourceRouter(t, &config.Config{}, repo, fullServiceKey), "space-a", "2")
	require.Equal(t, http.StatusConflict, w.Code, w.Body.String())
	require.Contains(t, w.Body.String(), source.ErrorNotCaptured)
	require.NotContains(t, w.Body.String(), "raw-a", "the response never names the RAW KB")
	require.Equal(t, uint64(7), repo.tenant)
	require.Equal(t, 1, repo.revisionCalls)
	require.Equal(t, int64(2), repo.attempt, "the requested attempt, never the current one")
}

func TestEnterpriseSpaceSourcePagesFailClosed(t *testing.T) {
	restricted := types.TenantAPIKeyScope{KeyID: 1, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"raw-a"}}
	capability := types.TenantAPIKeyScope{KeyID: 1, Capabilities: types.StringArray{"retrieve"}}
	for _, tc := range []struct {
		name, kb, space, attempt string
		caller                   spaceCaller
		status                   int
		knowledgeCalls           int
		revisionCalls            int
	}{
		{"source owned by another Space", "raw-b", "space-a", "2", fullServiceKey, 404, 1, 0},
		{"unconfigured Space", "raw-a", "space-z", "2", fullServiceKey, 404, 0, 0},
		{"caller of another tenant", "raw-a", "space-a", "2", spaceCaller{8, fullServiceKey.key}, 404, 0, 0},
		{"attempt without revision", "raw-a", "space-a", "3", fullServiceKey, 404, 1, 1},
		{"KB-restricted key", "raw-a", "space-a", "2", spaceCaller{7, restricted}, 403, 0, 0},
		{"capability-only key", "raw-a", "space-a", "2", spaceCaller{7, capability}, 403, 0, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			repo := knowledgeIn(tc.kb)
			w := sourcePages(spaceSourceRouter(t, &config.Config{}, repo, tc.caller), tc.space, tc.attempt)
			require.Equal(t, tc.status, w.Code, w.Body.String())
			require.NotContains(t, w.Body.String(), `"pages"`)
			require.Equal(t, tc.knowledgeCalls, repo.knowledgeCalls)
			require.Equal(t, tc.revisionCalls, repo.revisionCalls)
			if tc.status == http.StatusNotFound {
				require.Contains(t, w.Body.String(), source.ErrorSourceNotFound)
			}
		})
	}
}
