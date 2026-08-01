package container

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"gorm.io/gorm"
)

func TestInitDatabaseUsesParameterizedGORMLogger(t *testing.T) {
	t.Setenv("DB_DRIVER", "sqlite")
	t.Setenv("DB_PATH", filepath.Join(t.TempDir(), "weknora.db"))
	t.Setenv("AUTO_MIGRATE", "false")

	db, err := initDatabase(&config.Config{})
	if err != nil {
		t.Fatalf("init database: %v", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatalf("get sql.DB: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })

	filter, ok := db.Logger.(gorm.ParamsFilter)
	if !ok {
		t.Fatalf("production GORM logger %T has no ParamsFilter", db.Logger)
	}
	query := "INSERT INTO sensitive_rows(token, embedding) VALUES (?, ?)"
	gotQuery, gotParams := filter.ParamsFilter(
		context.Background(),
		query,
		"synthetic.jwt.auth-token-secret",
		"[0.125,-0.5,0.75]",
	)
	if gotQuery != query {
		t.Fatalf("ParamsFilter changed SQL structure: got %q, want %q", gotQuery, query)
	}
	if len(gotParams) != 0 {
		t.Fatalf("production GORM logger retained %d sensitive params", len(gotParams))
	}
}
