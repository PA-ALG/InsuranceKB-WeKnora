package memberstore

import (
	"testing"

	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func TestStorageKeyQueryUsesOneBinaryParameter(t *testing.T) {
	db, err := gorm.Open(postgres.New(postgres.Config{DSN: "host=unused dbname=unused"}),
		&gorm.Config{DryRun: true, DisableAutomaticPing: true})
	require.NoError(t, err)
	for _, count := range []int{1, 100} {
		keys := make([][]byte, count)
		for i := range keys {
			keys[i] = make([]byte, 32)
			keys[i][0] = byte(i)
		}
		var rows []contentRow
		query := byDigests(db, "enterprise_member_contents", 1, keys).Find(&rows)
		require.NoError(t, query.Error)
		require.Len(t, query.Statement.Vars, 3, "binary keys must not become one bind parameter per byte")
		require.Contains(t, query.Statement.SQL.String(), "substring($1::bytea FROM")
	}
}
