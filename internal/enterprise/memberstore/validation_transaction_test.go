package memberstore

import (
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func TestJournalPoolNeverRebindsCallerTransaction(t *testing.T) {
	sqlDB, mock, err := sqlmock.New()
	require.NoError(t, err)
	defer sqlDB.Close()
	db, err := gorm.Open(postgres.New(postgres.Config{Conn: sqlDB}), &gorm.Config{DisableAutomaticPing: true})
	require.NoError(t, err)
	mock.ExpectBegin()
	tx := db.Begin()
	require.NoError(t, tx.Error)
	callerPool := tx.Statement.ConnPool
	root := journalPool(tx)
	require.Same(t, callerPool, tx.Statement.ConnPool, "journal must not escape the caller's transaction")
	require.NotSame(t, tx.Statement, root.Statement)
	require.Same(t, db.Config.ConnPool, root.Statement.ConnPool)
	mock.ExpectRollback()
	require.NoError(t, tx.Rollback().Error)
	require.NoError(t, mock.ExpectationsWereMet())
}
