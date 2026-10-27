package database

import (
	"testing"

	"github.com/stretchr/testify/require"
)

// The confirmation source column (S5b-3d-2, 000012) is the packaged enterprise head; the point
// decision migration (000011) it follows is no longer accepted as a finished migration set.
func TestConfirmationSourceMigrationIsThePackagedEnterpriseHead(t *testing.T) {
	require.Equal(t, uint(12), packagedEnterpriseMigrationHead)
	require.NoError(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 12))
	require.Error(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 11))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 8))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 9))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 10))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 11))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 12))
	require.False(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 13))
}
