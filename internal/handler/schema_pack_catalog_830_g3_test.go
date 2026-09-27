package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func schemaPackCatalog830G3Context(t *testing.T, seal bool, proofScope *types.WikiReleaseScope) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	response := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(response)
	request := httptest.NewRequest(http.MethodGet, "/catalog", nil)
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer-g3"}
	scope := types.WikiReleaseScope{TenantID: 830, SpaceID: "space-g3", RawKBID: "raw-g3", WikiKBID: "wiki-g3"}
	ctx := types.WithPrincipal(context.Background(), principal)
	if seal {
		sealedScope := scope
		if proofScope != nil {
			sealedScope = *proofScope
		}
		ctx = service.SealWikiReleaseAccess(ctx, types.WikiReleasePrincipal{
			ID: principal.StorageID(), TenantID: scope.TenantID, SpaceID: scope.SpaceID,
		}, sealedScope)
	}
	request = request.WithContext(ctx)
	c.Request = request
	c.Set(types.TenantIDContextKey.String(), scope.TenantID)
	c.Set(types.PrincipalContextKey.String(), principal)
	c.Params = gin.Params{
		{Key: "kb_id", Value: scope.WikiKBID},
		{Key: "space_id", Value: scope.SpaceID},
		{Key: "raw_kb_id", Value: scope.RawKBID},
		{Key: "catalog_id", Value: "schema_catalog_insurance_product"},
		{Key: "catalog_version", Value: "2026-08-12-v5"},
	}
	return c, response
}

func TestReadSchemaPackCatalog830G3ReturnsExactProtectedAsset(t *testing.T) {
	t.Parallel()
	c, response := schemaPackCatalog830G3Context(t, true, nil)
	NewSchemaWikiHandler(nil, nil).ReadSchemaPackCatalog830G3(c)

	require.Equal(t, http.StatusOK, response.Code, "body=%s", response.Body.String())
	require.Equal(t, "private, no-store", response.Header().Get("Cache-Control"))
	var wire struct {
		Success bool            `json:"success"`
		Data    json.RawMessage `json:"data"`
	}
	require.NoError(t, json.Unmarshal(response.Body.Bytes(), &wire))
	require.True(t, wire.Success)
	expected, err := os.ReadFile("schema_pack_catalog_830_g3.generated.json")
	require.NoError(t, err)
	require.JSONEq(t, string(expected), string(wire.Data))
}

func TestReadSchemaPackCatalog830G3RequiresExactSeal(t *testing.T) {
	t.Parallel()
	for name, testCase := range map[string]struct {
		seal  bool
		proof *types.WikiReleaseScope
	}{
		"missing seal": {seal: false},
		"scope drift": {seal: true, proof: &types.WikiReleaseScope{
			TenantID: 830, SpaceID: "space-g3", RawKBID: "other-raw", WikiKBID: "wiki-g3",
		}},
	} {
		t.Run(name, func(t *testing.T) {
			c, response := schemaPackCatalog830G3Context(t, testCase.seal, testCase.proof)
			NewSchemaWikiHandler(nil, nil).ReadSchemaPackCatalog830G3(c)
			require.Equal(t, http.StatusForbidden, response.Code, "body=%s", response.Body.String())
		})
	}
}

func TestReadSchemaPackCatalog830G3RejectsNonExactIdentity(t *testing.T) {
	t.Parallel()
	c, response := schemaPackCatalog830G3Context(t, true, nil)
	c.Params[3].Value = " schema_catalog_insurance_product"
	NewSchemaWikiHandler(nil, nil).ReadSchemaPackCatalog830G3(c)
	require.Equal(t, http.StatusNotFound, response.Code, "body=%s", response.Body.String())
}
