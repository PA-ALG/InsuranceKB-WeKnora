package database

import (
	"testing"

	"github.com/stretchr/testify/require"
)

// The expert revision table (S9a, 000009) is the packaged enterprise head; the spot-check
// migration (000008) it follows is no longer accepted as a finished migration set.
func TestExpertRevisionMigrationIsThePackagedEnterpriseHead(t *testing.T) {
	require.Equal(t, uint(9), packagedEnterpriseMigrationHead)
	require.NoError(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 9))
	require.Error(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 8))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 8))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 9))
	require.False(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 10))
}
