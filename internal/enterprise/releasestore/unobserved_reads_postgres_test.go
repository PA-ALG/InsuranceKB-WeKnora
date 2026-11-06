package releasestore

import (
	"context"
	"database/sql"
	"os"
	"regexp"
	"sync/atomic"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/stdlib"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

type readonlyWriteTrace struct{ writes atomic.Int64 }

var writeStatement = regexp.MustCompile(`(?i)\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE)\b`)

func (w *readonlyWriteTrace) TraceQueryStart(
	ctx context.Context, _ *pgx.Conn, d pgx.TraceQueryStartData,
) context.Context {
	if writeStatement.MatchString(d.SQL) {
		w.writes.Add(1)
	}
	return ctx
}

func (*readonlyWriteTrace) TraceQueryEnd(context.Context, *pgx.Conn, pgx.TraceQueryEndData) {}

// The real driver observes attempted SQL before GORM sanitizes journal logging.
// PostgreSQL itself rejects writes; the test does not replace the storage port.
func readonlyStorageDB(t *testing.T, source *gorm.DB) (*gorm.DB, *readonlyWriteTrace) {
	t.Helper()
	cfg, err := pgx.ParseConfig(os.Getenv("WEKNORA_TEST_POSTGRES_URL"))
	require.NoError(t, err)
	var schema string
	require.NoError(t, source.Raw("SELECT current_schema()").Scan(&schema).Error)
	cfg.RuntimeParams["search_path"] = schema
	cfg.RuntimeParams["default_transaction_read_only"] = "on"
	trace := &readonlyWriteTrace{}
	cfg.Tracer = trace
	pool := sql.OpenDB(stdlib.GetConnector(*cfg))
	pool.SetMaxOpenConns(1)
	pool.SetMaxIdleConns(1)
	t.Cleanup(func() { _ = pool.Close() })
	db, err := gorm.Open(postgres.New(postgres.Config{Conn: pool}),
		&gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	require.NoError(t, err)
	var setting string
	require.NoError(t, db.Raw("SHOW transaction_read_only").Scan(&setting).Error)
	require.Equal(t, "on", setting)
	return db, trace
}

func TestPostgresUnobservedReadsAreReadOnlyWhenJournalCannotWrite(t *testing.T) {
	for _, format := range []string{"", "bridge.v1"} {
		t.Run("format="+format, func(t *testing.T) {
			db := memberStorageDB(t)
			members := storageMembers(t, 3, 0)
			r := storagePublish(t, New(db, testSpaces(t)), "readonly-history", members)
			require.NoError(t, db.Exec("UPDATE wiki_releases SET member_storage=?", format).Error)
			require.NoError(t, db.Exec("UPDATE wiki_release_preparations SET member_storage=?", format).Error)
			want := storedSnapshots(t, db, r.ID)
			ro, trace := readonlyStorageDB(t, db)
			scope, err := testSpaces(t).Scope(7, "space-1")
			require.NoError(t, err)
			for _, entry := range []string{"Read", "repository", "ReleaseByID", "Active"} {
				t.Run(entry, func(t *testing.T) {
					trace.writes.Store(0)
					s := New(ro, testSpaces(t))
					switch entry {
					case "Read":
						got, err := s.storage.Read(context.Background(), ro, scope, r.ID)
						assert.NoError(t, err)
						assert.Equal(t, want, got)
					case "repository":
						repo := repository.NewWikiReleaseRepository(ro).WithMemberStorage(s.storage)
						got, err := repo.GetReleaseMembers(context.Background(), scope, r.ID)
						assert.NoError(t, err)
						assert.Equal(t, want, got)
					default:
						id := r.ID
						if entry == "Active" {
							id = ""
						}
						got, err := s.ReleaseByID(context.Background(), 7, "space-1", id)
						assert.NoError(t, err)
						assert.Equal(t, members, got.Members)
					}
					assert.Zero(t, trace.writes.Load(), "unobserved reads must not attempt SQL writes")
				})
			}
		})
	}
}

func TestPostgresObservedReadsStillRequireWritableJournal(t *testing.T) {
	db, _, id := observationFixture(t)
	ro, trace := readonlyStorageDB(t, db)
	s := New(ro, testSpaces(t))
	scope, err := testSpaces(t).Scope(7, "space-1")
	require.NoError(t, err)
	got, err := s.storage.Read(context.Background(), ro, scope, id)
	require.Error(t, err)
	require.Nil(t, got)
	require.Positive(t, trace.writes.Load())
	trace.writes.Store(0)
	_, err = s.ReleaseByID(context.Background(), 7, "space-1", id)
	require.Error(t, err, "new-format reads must not fall back to retained legacy bytes")
	require.Positive(t, trace.writes.Load())
}
