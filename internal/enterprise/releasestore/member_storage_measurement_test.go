package releasestore

import (
	"context"
	"database/sql"
	"net"
	"os"
	"sync/atomic"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/stdlib"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

type storageCountingConnection struct {
	net.Conn
	bytes *atomic.Int64
}

func (c storageCountingConnection) Read(p []byte) (int, error) {
	n, err := c.Conn.Read(p)
	c.bytes.Add(int64(n))
	return n, err
}

// Counts actual PostgreSQL reply wire bytes, without inspecting/logging any payload.
// Both readers share one connection/config and database/schema; startup/preheat is untimed.
func storageMeasuredConnection(t *testing.T, source *gorm.DB, log logger.Interface) (*gorm.DB, *atomic.Int64) {
	t.Helper()
	cfg, err := pgx.ParseConfig(os.Getenv("WEKNORA_TEST_POSTGRES_URL"))
	require.NoError(t, err)
	var schema string
	require.NoError(t, source.Raw("SELECT current_schema()").Scan(&schema).Error)
	cfg.RuntimeParams["search_path"] = schema
	bytes := &atomic.Int64{}
	cfg.DialFunc = func(ctx context.Context, network, addr string) (net.Conn, error) {
		var dialer net.Dialer
		c, err := dialer.DialContext(ctx, network, addr)
		if err != nil {
			return nil, err
		}
		return storageCountingConnection{c, bytes}, nil
	}
	pool := sql.OpenDB(stdlib.GetConnector(*cfg))
	pool.SetMaxOpenConns(1)
	pool.SetMaxIdleConns(1)
	t.Cleanup(func() { _ = pool.Close() })
	db, err := gorm.Open(postgres.New(postgres.Config{Conn: pool}), &gorm.Config{Logger: log})
	require.NoError(t, err)
	return db, bytes
}
