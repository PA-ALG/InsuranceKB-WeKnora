package enterprise_test

// Requires WEKNORA_TEST_POSTGRES_URL (the enterprise-postgres CI job); a skip is no evidence.
import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/middleware"
)

func confirmationDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := strings.TrimSpace(os.Getenv("WEKNORA_TEST_POSTGRES_URL"))
	if dsn == "" {
		t.Skip("WEKNORA_TEST_POSTGRES_URL is required for PostgreSQL route evidence")
	}
	admin, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	schema := fmt.Sprintf("s5b3a_%d", time.Now().UnixNano())
	require.NoError(t, admin.Exec("CREATE SCHEMA "+schema).Error)
	adminSQL, err := admin.DB()
	require.NoError(t, err)
	t.Cleanup(func() {
		_ = admin.Exec("DROP SCHEMA " + schema + " CASCADE").Error
		_ = adminSQL.Close()
	})
	separator := "?"
	if strings.Contains(dsn, "?") {
		separator = "&"
	}
	db, err := gorm.Open(postgres.Open(dsn+separator+"search_path="+schema), &gorm.Config{})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	t.Cleanup(func() { _ = sqlDB.Close() })
	_, file, _, _ := runtime.Caller(0)
	up, err := os.ReadFile(filepath.Join(filepath.Dir(file),
		"../../migrations/enterprise/versioned/000010_enterprise_confirmations.up.sql"))
	require.NoError(t, err)
	require.NoError(t, db.Exec(string(up)).Error)
	return db
}

func TestPostgresConfirmationAPIRefusesASpaceOutsideTheConfiguration(t *testing.T) {
	db := confirmationDB(t)
	spaces, err := releasestore.ParseSpaces(`[{"tenant_id":7,"space_id":"demo","raw_kb_id":"raw","wiki_kb_id":"wiki"}]`)
	require.NoError(t, err)
	service := confirm.NewService(releasestore.New(db, spaces))
	require.NoError(t, db.Exec(`INSERT INTO enterprise_confirmations
(id, tenant_id, space_id, subject, revision, content_digest, title, detail, options, created_by, created_at)
VALUES ('old-item', 7, 'outside', 'k', '1', 'd', 't', '', '[{"key":"ignore","label":"x"}]', 'svc', now())`).Error)

	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: machineKey()}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	group := r.Group("/api/v1/enterprise", gate.Middleware())
	enterprise.Mount(group.Group("/spaces/:space_id"), enterprise.Deps{Authorizer: gate, Confirmations: service})

	outside := "/api/v1/enterprise/spaces/outside"
	for _, route := range []struct{ method, path, body string }{
		{http.MethodGet, outside + "/confirmations", ""},
		{http.MethodPost, outside + "/confirmations/old-item/closure", `{"reason":"obsolete"}`},
		{http.MethodPost, outside + "/confirmations", confirmBody},
	} {
		res := request(r, route.method, route.path, "test-key", []byte(route.body))
		require.Equal(t, 404, res.Code, "%s %s: %s", route.method, route.path, res.Body.String())
		require.Equal(t, confirm.ErrorConfirmationNotFound, code(t, res.Body.Bytes()))
		require.NotContains(t, res.Body.String(), "old-item")
	}
	var written int64
	require.NoError(t, db.Raw(`SELECT (SELECT count(*) FROM enterprise_confirmation_closures)
 + (SELECT count(*) FROM enterprise_confirmations WHERE id <> 'old-item')`).Scan(&written).Error)
	require.Zero(t, written)

	res := request(r, http.MethodPost, "/api/v1/enterprise/spaces/demo/confirmations", "test-key", []byte(confirmBody))
	require.Equal(t, 201, res.Code, "the configured Space still works: %s", res.Body.String())
}
