package database

import (
	"testing"

	"github.com/stretchr/testify/require"
)

// The confirmation tables (S5b-3a, 000010) are the packaged enterprise head; the expert revision
// migration (000009) they follow is no longer accepted as a finished migration set.
func TestConfirmationMigrationIsThePackagedEnterpriseHead(t *testing.T) {
	require.Equal(t, uint(10), packagedEnterpriseMigrationHead)
	require.NoError(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 10))
	require.Error(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 9))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 8))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 9))
	require.False(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 10))
}
