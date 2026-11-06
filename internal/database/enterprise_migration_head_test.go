package database

import (
	"testing"

	"github.com/stretchr/testify/require"
)

// Member chunks (000013) are the packaged enterprise head. Older clean ledgers
// remain resumable checkpoints but are not a finished migration set.
func TestEnterpriseMemberStorageMigrationIsThePackagedHead(t *testing.T) {
	require.Equal(t, uint(13), packagedEnterpriseMigrationHead)
	require.NoError(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 13))
	require.Error(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 11))
	require.Error(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 12))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 8))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 9))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 10))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 11))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 12))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 13))
	require.False(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 14))
}
