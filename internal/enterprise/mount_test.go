package enterprise_test

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	enterprise "github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type mountStore struct {
	release.Store
	candidate release.Candidate
	bundle    release.Bundle
	err       error
}

func (s *mountStore) CreateCandidate(
	_ context.Context, c release.Candidate, b release.Bundle,
) (release.Candidate, error) {
	if s.err != nil {
		return release.Candidate{}, s.err
	}
	if s.candidate.ID != "" {
		c = s.candidate
		c.Status = "existing"
		return c, nil
	}
	c.ID, c.Status = "candidate", "created"
	s.candidate, s.bundle = c, b
	return c, nil
}

func (s *mountStore) CandidateByID(_ context.Context, _ uint64, _, id string) (release.Candidate, error) {
	if s.candidate.ID != id {
		return release.Candidate{}, &release.Error{Code: release.ErrorCandidateNotFound, Detail: "not found"}
	}
	return s.candidate, nil
}

func (s *mountStore) BundleOf(context.Context, uint64, string, string) (release.Bundle, error) {
	return s.bundle, nil
}

func (s *mountStore) Head(context.Context, uint64, string) (release.Head, error) {
	return release.Head{}, nil
}

type tenantService struct{ interfaces.TenantService }

func (tenantService) GetTenantByID(_ context.Context, id uint64) (*types.Tenant, error) {
	return &types.Tenant{ID: id}, nil
}

type userService struct{ interfaces.UserService }

func (userService) GetUserByTenantID(_ context.Context, id uint64) (*types.User, error) {
	return &types.User{ID: "service-user", TenantID: id, IsActive: true}, nil
}

type keyService struct {
	interfaces.TenantAPIKeyService
	key *types.TenantAPIKey
}

func (s keyService) AuthenticateAPIKey(_ context.Context, key string) (*types.TenantAPIKey, error) {
	if key != "test-key" {
		return nil, errors.New("unknown key")
	}
	return s.key, nil
}

func machineKey() *types.TenantAPIKey {
	tenant := uint64(7)
	return &types.TenantAPIKey{ID: 1, TenantID: &tenant, FullAccess: true}
}

func mountService(t *testing.T, store *mountStore) *release.Service {
	t.Helper()
	schema, err := os.ReadFile("../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	return release.NewService(store, nil, map[string][]byte{"candidate_bundle": schema})
}

func mountRouter(service *release.Service, key *types.TenantAPIKey) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: key}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	api := r.Group("/api/v1", gate.Middleware())
	enterprise.Mount(api.Group("/spaces/:space_id"), enterprise.Deps{Candidates: service, Authorizer: gate})
	return r
}

func candidateBody(t *testing.T) []byte {
	t.Helper()
	payload := []byte(`{"name":"Product"}`)
	sum := sha256.Sum256(payload)
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "compiler/test",
		"members": []any{map[string]any{
			"kind": "entity", "logical_slug": "product", "access_scope": "space",
			"payload": json.RawMessage(payload), "member_digest": hex.EncodeToString(sum[:]),
		}},
	})
	require.NoError(t, err)
	return raw
}

func request(r http.Handler, method, path, key string, body []byte) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, bytes.NewReader(body))
	if key != "" {
		req.Header.Set("X-API-Key", key)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

const candidatesPath = "/api/v1/spaces/demo/candidates"

func TestMountRunsReceiveAndPreviewThroughExistingAuthentication(t *testing.T) {
	store := &mountStore{}
	r := mountRouter(mountService(t, store), machineKey())
	w := request(r, http.MethodPost, candidatesPath, "test-key", candidateBody(t))
	require.Equal(t, http.StatusCreated, w.Code, w.Body.String())
	require.Contains(t, w.Body.String(), `"bundle_digest"`)
	require.Equal(t, uint64(7), store.candidate.TenantID)
	require.Equal(t, "demo", store.candidate.SpaceID)
	w = request(r, http.MethodPost, candidatesPath, "test-key", candidateBody(t))
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	w = request(r, http.MethodGet, candidatesPath+"/candidate/preview", "test-key", nil)
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Contains(t, w.Body.String(), `"added":["product"]`)
	w = request(r, http.MethodGet, candidatesPath+"/missing/preview", "test-key", nil)
	require.Equal(t, http.StatusNotFound, w.Code)
	require.Contains(t, w.Body.String(), release.ErrorCandidateNotFound)
	w = request(r, http.MethodGet, "/api/v1/spaces/other/candidates/candidate/preview", "test-key", nil)
	require.Equal(t, http.StatusForbidden, w.Code)
}

func TestMountRejectsUnauthenticatedAndRestrictedKeys(t *testing.T) {
	for _, key := range []string{"", "invalid"} {
		store := &mountStore{}
		r := mountRouter(mountService(t, store), machineKey())
		w := request(r, http.MethodPost, candidatesPath, key, candidateBody(t))
		require.Equal(t, http.StatusUnauthorized, w.Code)
		require.Empty(t, store.candidate.ID)
	}
	for _, key := range []*types.TenantAPIKey{
		{ID: 1, TenantID: machineKey().TenantID, Capabilities: types.StringArray{"retrieve"}},
		{ID: 1, TenantID: machineKey().TenantID, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"restricted"}},
	} {
		store := &mountStore{}
		r := mountRouter(mountService(t, store), key)
		w := request(r, http.MethodPost, candidatesPath, "test-key", candidateBody(t))
		require.Equal(t, http.StatusForbidden, w.Code)
		require.Empty(t, store.candidate.ID)
	}
}

func TestMountDoesNotTrustIdentityHeadersWithoutAuthentication(t *testing.T) {
	r := gin.New()
	gate := middleware.NewAPIKeyRouteAuthorizer()
	enterprise.Mount(r.Group("/api/v1/spaces/:space_id"), enterprise.Deps{
		Candidates: mountService(t, &mountStore{}), Authorizer: gate,
	})
	req := httptest.NewRequest(http.MethodPost, candidatesPath, bytes.NewReader(candidateBody(t)))
	req.Header.Set("X-API-Key", "test-key")
	req.Header.Set("X-Tenant-ID", "7")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	require.Equal(t, http.StatusForbidden, w.Code)
}

func TestMountRejectsOversizedAndMalformedInput(t *testing.T) {
	for _, body := range [][]byte{[]byte(`{`), bytes.Repeat([]byte(" "), release.MaxBundleBytes+1)} {
		store := &mountStore{}
		w := request(mountRouter(mountService(t, store), machineKey()),
			http.MethodPost, candidatesPath, "test-key", body)
		require.Equal(t, http.StatusBadRequest, w.Code)
		require.Contains(t, w.Body.String(), release.ErrorCandidateInvalid)
		require.Empty(t, store.candidate.ID)
	}
}

func TestMountFailsClosedWhenDependenciesAreMissing(t *testing.T) {
	w := request(mountRouter(nil, machineKey()), http.MethodPost, candidatesPath, "test-key", candidateBody(t))
	require.Equal(t, http.StatusServiceUnavailable, w.Code)
}

func TestMountDoesNotExposeStorageFailureDetails(t *testing.T) {
	store := &mountStore{err: errors.New("private database diagnostic")}
	w := request(mountRouter(mountService(t, store), machineKey()),
		http.MethodPost, candidatesPath, "test-key", candidateBody(t))
	require.Equal(t, http.StatusInternalServerError, w.Code)
	require.False(t, strings.Contains(w.Body.String(), "private database diagnostic"))
}
