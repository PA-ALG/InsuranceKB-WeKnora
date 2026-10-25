package enterprise_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

// httpConfirmStore keeps the confirm.Store contract in memory for route tests.
type httpConfirmStore struct {
	mu       sync.Mutex
	items    map[string]confirm.Item // keyed by "<tenant>/<id>"
	order    []string
	answers  map[string][]confirm.Answer
	closures map[string]confirm.Closure
	calls    int
}

func newHTTPConfirmStore() *httpConfirmStore {
	return &httpConfirmStore{
		items:    map[string]confirm.Item{},
		answers:  map[string][]confirm.Answer{},
		closures: map[string]confirm.Closure{},
	}
}

func (s *httpConfirmStore) view(k string) confirm.Item {
	it := s.items[k]
	if a := s.answers[k]; len(a) > 0 {
		last := a[len(a)-1]
		it.Answer = &last
	}
	if c, ok := s.closures[k]; ok {
		it.Closure = &c
	}
	return it
}

func (s *httpConfirmStore) InsertItems(_ context.Context, tenant uint64, in []confirm.Item) ([]confirm.Item, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	out := make([]confirm.Item, 0, len(in))
	for _, it := range in {
		kept := ""
		for _, k := range s.order {
			old := s.items[k]
			if strings.HasPrefix(k, fmt.Sprintf("%d/", tenant)) && old.SpaceID == it.SpaceID &&
				old.Subject == it.Subject && old.Revision == it.Revision && old.ContentDigest == it.ContentDigest {
				kept = k
			}
		}
		if kept == "" {
			kept = fmt.Sprintf("%d/%s", tenant, it.ID)
			s.items[kept], s.order = it, append(s.order, kept)
		}
		out = append(out, s.view(kept))
	}
	return out, nil
}

func (s *httpConfirmStore) ListItems(
	_ context.Context, tenant uint64, space string, f confirm.Filter,
) ([]confirm.Item, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	out := []confirm.Item{}
	for _, k := range s.order {
		it := s.view(k)
		if !strings.HasPrefix(k, fmt.Sprintf("%d/", tenant)) || it.SpaceID != space ||
			(f.Status == "open" && it.Closure != nil) || (f.Status == "closed" && it.Closure == nil) {
			continue
		}
		out = append(out, it)
	}
	return out, nil
}

func (s *httpConfirmStore) ItemByID(_ context.Context, tenant uint64, space, id string) (confirm.Item, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := fmt.Sprintf("%d/%s", tenant, id)
	it, ok := s.items[k]
	if !ok || it.SpaceID != space {
		return confirm.Item{}, false, nil
	}
	return s.view(k), true, nil
}

func (s *httpConfirmStore) AppendAnswer(_ context.Context, tenant uint64, _ string, a confirm.Answer) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := fmt.Sprintf("%d/%s", tenant, a.ItemID)
	if _, closed := s.closures[k]; closed {
		return &release.Error{Code: confirm.ErrorConfirmationClosed, Detail: "closed"}
	}
	s.answers[k] = append(s.answers[k], a)
	return nil
}

func (s *httpConfirmStore) CloseItem(_ context.Context, tenant uint64, _, id string, c confirm.Closure) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := fmt.Sprintf("%d/%s", tenant, id)
	if _, closed := s.closures[k]; closed {
		return &release.Error{Code: confirm.ErrorConfirmationClosed, Detail: "closed"}
	}
	s.closures[k] = c
	return nil
}

type httpConfirmWorld struct {
	store   *httpConfirmStore
	service *confirm.Service
	spaces  enterprise.SpaceDirectory
}

func newHTTPConfirmWorld() *httpConfirmWorld {
	store, next := newHTTPConfirmStore(), 0
	service := confirm.NewService(store, confirm.WithIDs(func() string {
		next++
		return fmt.Sprintf("c-%03d", next)
	}))
	return &httpConfirmWorld{store: store, service: service, spaces: spaceDirectory{7: {"demo"}}}
}

func (w *httpConfirmWorld) apiRouter(key *types.TenantAPIKey) *gin.Engine {
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: key}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	group := r.Group("/api/v1/enterprise", gate.Middleware())
	enterprise.Mount(group.Group("/spaces/:space_id"), enterprise.Deps{Authorizer: gate, Confirmations: w.service})
	deps := enterprise.SessionDeps{Confirmations: w.service, Spaces: w.spaces}
	enterprise.MountSessionReads(group, deps)
	enterprise.MountSessionConfirmations(group, deps)
	return r
}

func (w *httpConfirmWorld) sessionRouter(who identity) *gin.Engine {
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, who.tenant)
		ctx = types.WithPrincipal(ctx, who.principal)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: who.tenant, UserID: "user-1", Role: types.TenantRoleAdmin})
		if who.apiKey {
			ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 3, FullAccess: true})
		}
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), who.tenant)
		c.Set(types.PrincipalContextKey.String(), who.principal)
		c.Next()
	})
	group := r.Group("/api/v1/enterprise")
	deps := enterprise.SessionDeps{Confirmations: w.service, Spaces: w.spaces}
	enterprise.MountSessionReads(group, deps)
	enterprise.MountSessionConfirmations(group, deps)
	return r
}

const confirmBody = `{"items":[{"subject":"k-1","revision":"1:abc","title":"材料 甲","detail":"说明",` +
	`"options":[{"key":"assign:p-1","label":"归入 甲"},{"key":"ignore","label":"忽略"}]}]}`

func confirmItems(t *testing.T, body []byte) []confirm.Item {
	t.Helper()
	encoded, err := json.Marshal(data(t, body)["items"])
	require.NoError(t, err)
	require.NotEqual(t, "null", string(encoded), "an empty list must be []")
	var items []confirm.Item
	require.NoError(t, json.Unmarshal(encoded, &items))
	return items
}

func TestConfirmationHTTPSubmitAnswerCloseFlow(t *testing.T) {
	w := newHTTPConfirmWorld()
	api, page := w.apiRouter(machineKey()), w.sessionRouter(browser)
	res := request(api, http.MethodPost, spotPath+"/confirmations", "test-key", []byte(confirmBody))
	require.Equal(t, 201, res.Code, res.Body.String())
	items := confirmItems(t, res.Body.Bytes())
	require.Len(t, items, 1)
	id := items[0].ID

	res = request(page, http.MethodGet, spotPath+"/view/confirmations?status=open", "", nil)
	require.Equal(t, 200, res.Code, res.Body.String())
	require.Len(t, confirmItems(t, res.Body.Bytes()), 1)

	res = request(page, http.MethodPost, spotPath+"/view/confirmations/"+id+"/answers", "",
		[]byte(`{"option_key":"assign:p-1","note":"依据条款"}`))
	require.Equal(t, 201, res.Code, res.Body.String())
	answer := data(t, res.Body.Bytes())["answer"].(map[string]any)
	require.Equal(t, "web_user:user-1", answer["answerer"], "the principal storage id, as spot-check reviewers")

	res = request(api, http.MethodPost, spotPath+"/confirmations/"+id+"/closure", "test-key",
		[]byte(`{"reason":"applied","answer_id":"`+answer["id"].(string)+`"}`))
	require.Equal(t, 201, res.Code, res.Body.String())

	res = request(page, http.MethodPost, spotPath+"/view/confirmations/"+id+"/answers", "",
		[]byte(`{"option_key":"ignore"}`))
	require.Equal(t, 409, res.Code, res.Body.String())
	require.Equal(t, confirm.ErrorConfirmationClosed, code(t, res.Body.Bytes()))

	res = request(api, http.MethodGet, spotPath+"/confirmations?status=closed", "test-key", nil)
	require.Equal(t, 200, res.Code, res.Body.String())
	closed := confirmItems(t, res.Body.Bytes())
	require.Len(t, closed, 1)
	require.Equal(t, "applied", closed[0].Closure.Reason)
	res = request(api, http.MethodGet, spotPath+"/confirmations?status=open", "test-key", nil)
	require.Empty(t, confirmItems(t, res.Body.Bytes()))
}

func TestConfirmationHTTPStatusCodes(t *testing.T) {
	w := newHTTPConfirmWorld()
	api, page := w.apiRouter(machineKey()), w.sessionRouter(browser)
	res := request(api, http.MethodPost, spotPath+"/confirmations", "test-key", []byte(confirmBody))
	id := confirmItems(t, res.Body.Bytes())[0].ID
	for _, tc := range []struct {
		router http.Handler
		path   string
		key    string
		body   string
		status int
		code   string
	}{
		{
			page, "/view/confirmations/" + id + "/answers", "", `{"option_key":"other"}`, 400,
			confirm.ErrorAnswerInvalid,
		},
		{
			page, "/view/confirmations/missing/answers", "", `{"option_key":"ignore"}`, 404,
			confirm.ErrorConfirmationNotFound,
		},
		{
			api, "/confirmations/" + id + "/closure", "test-key", `{"reason":"applied","answer_id":""}`, 400,
			confirm.ErrorConfirmationInvalid,
		},
		{
			api, "/confirmations/" + id + "/closure", "test-key", `{"reason":"applied","answer_id":"x"}`, 409,
			confirm.ErrorAnswerStale,
		},
	} {
		res = request(tc.router, http.MethodPost, spotPath+tc.path, tc.key, []byte(tc.body))
		require.Equal(t, tc.status, res.Code, res.Body.String())
		require.Equal(t, tc.code, code(t, res.Body.Bytes()))
	}
	res = request(api, http.MethodGet, spotPath+"/confirmations?status=answered", "test-key", nil)
	require.Equal(t, 400, res.Code, res.Body.String())
}

func TestConfirmationHTTPStrictJSONAndLimits(t *testing.T) {
	for name, body := range map[string]string{
		"null": `null`, "trailing": confirmBody + ` {}`, "unknown": `{"items":[],"extra":1}`,
		"duplicate":     `{"items":[],"items":[]}`,
		"forged digest": strings.Replace(confirmBody, `"title"`, `"content_digest":"x","title"`, 1),
		"invalid UTF8":  strings.Replace(confirmBody, "说明", "\xff", 1),
	} {
		t.Run(name, func(t *testing.T) {
			w := newHTTPConfirmWorld()
			router := w.apiRouter(machineKey())
			res := request(router, http.MethodPost, spotPath+"/confirmations", "test-key", []byte(body))
			require.Equal(t, 400, res.Code, res.Body.String())
			require.Equal(t, confirm.ErrorConfirmationInvalid, code(t, res.Body.Bytes()))
			require.Empty(t, w.store.items)
		})
	}
	for _, delta := range []int{0, 1} {
		w := newHTTPConfirmWorld()
		body := confirmBody + strings.Repeat(" ", (512<<10)+delta-len(confirmBody))
		router := w.apiRouter(machineKey())
		res := request(router, http.MethodPost, spotPath+"/confirmations", "test-key", []byte(body))
		if delta == 0 {
			require.Equal(t, 201, res.Code, res.Body.String())
		} else {
			require.Equal(t, 400, res.Code, res.Body.String())
			require.Empty(t, w.store.items)
		}
	}
	w := newHTTPConfirmWorld()
	api := w.apiRouter(machineKey())
	res := request(api, http.MethodPost, spotPath+"/confirmations", "test-key", []byte(confirmBody))
	id := confirmItems(t, res.Body.Bytes())[0].ID
	res = request(w.sessionRouter(browser), http.MethodPost, spotPath+"/view/confirmations/"+id+"/answers", "",
		[]byte(`{"option_key":"ignore","answerer":"admin"}`))
	require.Equal(t, 400, res.Code, res.Body.String())
	require.Equal(t, confirm.ErrorAnswerInvalid, code(t, res.Body.Bytes()))
}

func TestConfirmationHTTPRequiresFullServiceKeysAndKeepsRoutesApart(t *testing.T) {
	for name, key := range map[string]*types.TenantAPIKey{
		"readonly": {ID: 1, TenantID: machineKey().TenantID, Capabilities: types.StringArray{"retrieve"}},
		"KB restricted": {
			ID: 1, TenantID: machineKey().TenantID, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"wiki-demo"},
		},
	} {
		t.Run(name, func(t *testing.T) {
			w := newHTTPConfirmWorld()
			router := w.apiRouter(key)
			for _, route := range []struct{ method, path, body string }{
				{http.MethodGet, spotPath + "/confirmations", ""},
				{http.MethodPost, spotPath + "/confirmations", confirmBody},
				{http.MethodPost, spotPath + "/confirmations/c-001/closure", `{"reason":"obsolete"}`},
			} {
				res := request(router, route.method, route.path, "test-key", []byte(route.body))
				require.Equal(t, 403, res.Code, res.Body.String())
			}
			require.Zero(t, w.store.calls)
		})
	}
	w := newHTTPConfirmWorld()
	keyed := identity{tenant: 7, principal: browser.principal, apiKey: true}
	res := request(w.sessionRouter(keyed), http.MethodGet, spotPath+"/view/confirmations", "", nil)
	require.Equal(t, 403, res.Code, "session routes refuse API keys: %s", res.Body.String())
	other := "/api/v1/enterprise/spaces/other/view/confirmations"
	res = request(w.sessionRouter(browser), http.MethodGet, other, "", nil)
	require.Equal(t, 404, res.Code, "a Space outside the directory: %s", res.Body.String())
}

func TestConfirmationRoutesReturn503WhenUnconfigured(t *testing.T) {
	w := &httpConfirmWorld{spaces: spaceDirectory{7: {"demo"}}}
	res := request(w.apiRouter(machineKey()), http.MethodGet, spotPath+"/confirmations", "test-key", nil)
	require.Equal(t, 503, res.Code, res.Body.String())
	res = request(w.sessionRouter(browser), http.MethodGet, spotPath+"/view/confirmations", "", nil)
	require.Equal(t, 503, res.Code, res.Body.String())
}
