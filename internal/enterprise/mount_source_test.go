package enterprise_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

type pageStore struct {
	artifact *source.Artifact
	err      error
	calls    int
	scope    source.Scope
}

func (s *pageStore) Load(_ context.Context, scope source.Scope, _ string, _ int64) (*source.Artifact, error) {
	s.calls++
	s.scope = scope
	return s.artifact, s.err
}

func mountSourceRouter(t *testing.T, pages *source.Service, key *types.TenantAPIKey) *gin.Engine {
	t.Helper()
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: key}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	api := r.Group("/api/v1", gate.Middleware())
	enterprise.Mount(api.Group("/enterprise/spaces/:space_id"), enterprise.Deps{
		Sources: pages, Authorizer: gate,
	})
	return r
}

const sourcePagesPath = "/api/v1/enterprise/spaces/demo/sources/document/attempts/2/pages"

func mountArtifact(t *testing.T) *source.Artifact {
	t.Helper()
	text := "alpha\r\n𠮷"
	sum := sha256.Sum256([]byte(text))
	digest := hex.EncodeToString(sum[:])
	raw, err := json.Marshal(map[string]any{"pages": []any{map[string]any{
		"page_number": 1, "global_codepoint_start": 0,
		"global_codepoint_end": len([]rune(text)), "page_text_sha256": digest,
	}}})
	require.NoError(t, err)
	return &source.Artifact{
		KnowledgeID: "document", ParseAttempt: 2, FileName: "document.pdf", FileSHA256: digest,
		ParserIdentitySHA256: digest, Markdown: text, NativeJSON: raw,
	}
}

func TestMountSourcePagesReturnsPageSetAndTrustedScope(t *testing.T) {
	store := &pageStore{artifact: mountArtifact(t)}
	w := request(mountSourceRouter(t, source.NewService(store), machineKey()),
		http.MethodGet, sourcePagesPath, "test-key", nil)
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	var result source.PageSet
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &result))
	require.Equal(t, "document", result.KnowledgeID)
	require.Equal(t, int64(2), result.ParseAttempt)
	require.Equal(t, "alpha\r\n𠮷", result.Pages[0].Text)
	require.Equal(t, source.Scope{TenantID: 7, SpaceID: "demo"}, store.scope)
	require.Equal(t, 1, store.calls)
}

func TestMountSourcePagesRequiresFullUnrestrictedServiceKey(t *testing.T) {
	for _, raw := range []string{"", "invalid"} {
		store := &pageStore{artifact: mountArtifact(t)}
		w := request(mountSourceRouter(t, source.NewService(store), machineKey()),
			http.MethodGet, sourcePagesPath, raw, nil)
		require.Equal(t, http.StatusUnauthorized, w.Code)
		require.Zero(t, store.calls)
	}
	for _, key := range []*types.TenantAPIKey{
		{ID: 1, TenantID: machineKey().TenantID, Capabilities: types.StringArray{"retrieve"}},
		{ID: 1, TenantID: machineKey().TenantID, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"raw"}},
	} {
		store := &pageStore{artifact: mountArtifact(t)}
		w := request(mountSourceRouter(t, source.NewService(store), key),
			http.MethodGet, sourcePagesPath, "test-key", nil)
		require.Equal(t, http.StatusForbidden, w.Code)
		require.Zero(t, store.calls)
	}
}

func TestMountSourcePagesMapsErrorsAndNeverExposesStorageDiagnostics(t *testing.T) {
	for _, tc := range []struct {
		err    error
		status int
		code   string
	}{
		{source.ErrNotFound, 404, source.ErrorSourceNotFound},
		{source.ErrNotCaptured, 409, source.ErrorNotCaptured},
		{&source.Error{Code: source.ErrorIntegrity, Detail: "private storage diagnostic"}, 500, source.ErrorIntegrity},
		{errors.New("private storage diagnostic"), 503, source.ErrorUnavailable},
	} {
		t.Run(tc.code, func(t *testing.T) {
			store := &pageStore{err: tc.err}
			w := request(mountSourceRouter(t, source.NewService(store), machineKey()),
				http.MethodGet, sourcePagesPath, "test-key", nil)
			require.Equal(t, tc.status, w.Code, w.Body.String())
			require.Contains(t, w.Body.String(), `"success":false`)
			require.Contains(t, w.Body.String(), tc.code)
			require.NotContains(t, w.Body.String(), "private storage diagnostic")
		})
	}
	for _, attempt := range []string{"0", "-1", "invalid", "9223372036854775808"} {
		store := &pageStore{}
		path := "/api/v1/enterprise/spaces/demo/sources/document/attempts/" + attempt + "/pages"
		w := request(mountSourceRouter(t, source.NewService(store), machineKey()),
			http.MethodGet, path, "test-key", nil)
		require.Equal(t, http.StatusBadRequest, w.Code)
		require.Contains(t, w.Body.String(), source.ErrorInvalidRequest)
		require.Zero(t, store.calls)
	}
}

func TestMountSourcePagesFailsClosedWithoutDependencyOrAuthentication(t *testing.T) {
	w := request(mountSourceRouter(t, nil, machineKey()), http.MethodGet, sourcePagesPath, "test-key", nil)
	require.Equal(t, http.StatusServiceUnavailable, w.Code)
	store := &pageStore{artifact: mountArtifact(t)}
	r := gin.New()
	gate := middleware.NewAPIKeyRouteAuthorizer()
	enterprise.Mount(r.Group("/api/v1/enterprise/spaces/:space_id"), enterprise.Deps{
		Sources: source.NewService(store), Authorizer: gate,
	})
	w = request(r, http.MethodGet, sourcePagesPath, "test-key", nil)
	require.Equal(t, http.StatusForbidden, w.Code)
	require.Zero(t, store.calls)
}

func TestMountMissingCandidatesDoesNotDisableSources(t *testing.T) {
	r := mountSourceRouter(t, source.NewService(&pageStore{artifact: mountArtifact(t)}), machineKey())
	w := request(r, http.MethodGet, sourcePagesPath, "test-key", nil)
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	for _, tc := range []struct{ method, path string }{
		{http.MethodPost, "/api/v1/enterprise/spaces/demo/candidates"},
		{http.MethodGet, "/api/v1/enterprise/spaces/demo/candidates/candidate/preview"},
	} {
		w = request(r, tc.method, tc.path, "test-key", nil)
		require.Equal(t, http.StatusServiceUnavailable, w.Code)
		require.Contains(t, w.Body.String(), "SERVICE_UNAVAILABLE")
	}
}
