package router

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

var assembledFileBytes = []byte("%PDF-1.7\noriginal fixture\n%%EOF")

func assembledFileRef() string {
	sum := sha256.Sum256(assembledFileBytes)
	return "source:v1:k-file:2:" + hex.EncodeToString(sum[:])
}

type fileAssemblyItems struct {
	confirm.Store
	reads int
}

func (s *fileAssemblyItems) ItemByID(
	_ context.Context, tenant uint64, space, id string,
) (confirm.Item, bool, error) {
	s.reads++
	return confirm.Item{ID: "item-a", SpaceID: "space-a", SourceRef: assembledFileRef()},
		tenant == 7 && space == "space-a" && id == "item-a", nil
}

type fileAssemblyReleases struct {
	release.Store
	release.Publisher
}

func (*fileAssemblyReleases) ReleaseByID(context.Context, uint64, string, string) (release.Release, error) {
	return release.Release{ID: "release-a", Members: []release.Member{{
		LogicalSlug: "document", AccessScope: "space", EvidenceRefs: []string{assembledFileRef()},
	}}}, nil
}

type fileAssemblySource struct {
	failure         error
	kb              string
	lookups, opens  int
	lookupTenant    uint64
	executionTenant uint64
}

type fileAssemblyLookup struct {
	interfaces.KnowledgeRepository
	source *fileAssemblySource
}

func (s fileAssemblyLookup) GetKnowledgeByID(ctx context.Context, tenant uint64, id string) (*types.Knowledge, error) {
	return s.source.GetKnowledgeByID(ctx, tenant, id)
}

type fileAssemblyOpener struct {
	interfaces.KnowledgeService
	source *fileAssemblySource
}

func (s fileAssemblyOpener) GetKnowledgeFile(ctx context.Context, id string) (io.ReadCloser, string, error) {
	return s.source.GetKnowledgeFile(ctx, id)
}

func (s *fileAssemblySource) GetKnowledgeByID(_ context.Context, tenant uint64, id string) (*types.Knowledge, error) {
	s.lookups++
	s.lookupTenant = tenant
	return &types.Knowledge{ID: id, TenantID: tenant, KnowledgeBaseID: s.kb}, nil
}

func (s *fileAssemblySource) GetKnowledgeFile(ctx context.Context, _ string) (io.ReadCloser, string, error) {
	s.opens++
	s.executionTenant, _ = types.TenantIDFromContext(ctx)
	if s.failure != nil {
		return nil, "", s.failure
	}
	return io.NopCloser(bytes.NewReader(assembledFileBytes)), "original.pdf", nil
}

// Call the production registration, not MountSessionConfirmations with hand-built SessionDeps.
// The real SourceFiles adapter must receive the same scoped reader as the existing citation path.
func assembledFileRouter(
	t *testing.T, role types.TenantRole, source *fileAssemblySource,
) (*gin.Engine, *fileAssemblyItems) {
	t.Helper()
	enabled := false // Admin checking must remain effective even when tenant RBAC is disabled.
	cfg := &config.Config{Tenant: &config.TenantConfig{EnableRBAC: &enabled}}
	spaces, err := releasestore.ParseSpaces(spaceSourceSpaces)
	require.NoError(t, err)
	items := &fileAssemblyItems{}
	releases := &fileAssemblyReleases{}
	guards := &rbacGuards{cfg: cfg, kbService: confirmationLookup(), kbShareService: &routerSpotShares{
		roles: map[string]types.OrgMemberRole{"raw-a": types.OrgRoleViewer, "wiki-a": types.OrgRoleEditor},
	}}
	r := gin.New()
	r.Use(middleware.ErrorHandler(), func(c *gin.Context) {
		principal := types.Principal{Type: types.PrincipalWebUser, ID: "user-1"}
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, uint64(7))
		ctx = context.WithValue(ctx, types.UserIDContextKey, "user-1")
		ctx = context.WithValue(ctx, types.TenantRoleContextKey, role)
		ctx = types.WithPrincipal(ctx, principal)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: 7, UserID: "user-1", Role: role})
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), uint64(7))
		c.Set(types.PrincipalContextKey.String(), principal)
		c.Set(types.UserIDContextKey.String(), "user-1")
		c.Next()
	})
	gate := guards.ensureAPIKeyAuthorizer()
	registerEnterpriseRoutes(r.Group("/api/v1", gate.Middleware()), RouterParams{
		Config: cfg, EnterpriseSpaces: spaces, EnterpriseConfirmations: confirm.NewService(items),
		EnterpriseCandidates: release.NewService(releases, nil, nil, release.WithPublisher(releases)),
		KnowledgeRepository:  fileAssemblyLookup{source: source}, KnowledgeService: fileAssemblyOpener{source: source},
	}, guards)
	guards.assertAPIKeyPoliciesMatchRoutes(r)
	return r, items
}

const assembledConfirmPath = "/api/v1/enterprise/spaces/space-a/view/confirmations/item-a/file"

func TestProductionConfirmationFileAssemblyAndSharedMissingFileMapping(t *testing.T) {
	paths := []string{
		assembledConfirmPath,
		"/api/v1/enterprise/spaces/space-a/view/releases/release-a/sources/k-file/attempts/2/file",
	}
	for _, path := range paths {
		for _, tc := range []struct {
			name    string
			failure error
			status  int
			code    string
		}{
			{"bytes", nil, http.StatusOK, ""},
			{"wrapped missing", fmt.Errorf("open failed: %w", fs.ErrNotExist), 404, "SOURCE_NOT_FOUND"},
			{
				"path error", &fs.PathError{Op: "open", Path: "fixture.pdf", Err: fs.ErrNotExist},
				404, "SOURCE_NOT_FOUND",
			},
			{"unavailable", errors.New("private storage failure"), 503, "SOURCE_UNAVAILABLE"},
			{"permission", fmt.Errorf("open failed: %w", fs.ErrPermission), 503, "SOURCE_UNAVAILABLE"},
		} {
			t.Run(path+"/"+tc.name, func(t *testing.T) {
				source := &fileAssemblySource{kb: "raw-a", failure: tc.failure}
				router, _ := assembledFileRouter(t, types.TenantRoleAdmin, source)
				res := httptest.NewRecorder()
				router.ServeHTTP(res, httptest.NewRequest(http.MethodGet, path, nil))
				require.Equal(t, tc.status, res.Code, res.Body.String())
				require.Equal(t, 1, source.lookups)
				require.Equal(t, 1, source.opens)
				require.Equal(t, uint64(7), source.lookupTenant)
				require.Equal(t, uint64(7), source.executionTenant, "KB guards must restore the original tenant")
				if tc.code == "" {
					require.Equal(t, assembledFileBytes, res.Body.Bytes())
					return
				}
				require.Contains(t, res.Body.String(), `"code":"`+tc.code+`"`)
				require.NotContains(t, res.Body.String(), "%PDF")
				require.NotContains(t, res.Body.String(), "fixture.pdf")
				require.NotContains(t, res.Body.String(), "private storage failure")
				require.Empty(t, res.Header().Get("Content-Disposition"))
			})
		}
	}
}

func TestProductionConfirmationFileAssemblyPreservesAccessAndRawScope(t *testing.T) {
	for _, tc := range []struct {
		name   string
		role   types.TenantRole
		kb     string
		status int
	}{
		{"non-admin", types.TenantRoleContributor, "raw-a", 403},
		{"wrong KB", types.TenantRoleAdmin, "wiki-a", 404},
	} {
		t.Run(tc.name, func(t *testing.T) {
			source := &fileAssemblySource{kb: tc.kb}
			router, items := assembledFileRouter(t, tc.role, source)
			res := httptest.NewRecorder()
			router.ServeHTTP(res, httptest.NewRequest(http.MethodGet, assembledConfirmPath, nil))
			require.Equal(t, tc.status, res.Code, res.Body.String())
			require.Zero(t, source.opens)
			if tc.status == 403 {
				require.Zero(t, items.reads)
				require.Zero(t, source.lookups)
			}
		})
	}
}
