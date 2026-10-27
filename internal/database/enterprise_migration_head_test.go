package database

import (
	"testing"

	"github.com/stretchr/testify/require"
)

// The point decision table (RV6b, 000011) is the packaged enterprise head; the confirmation
// migration (000010) it follows is no longer accepted as a finished migration set.
func TestPointDecisionMigrationIsThePackagedEnterpriseHead(t *testing.T) {
	require.Equal(t, uint(11), packagedEnterpriseMigrationHead)
	require.NoError(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 11))
	require.Error(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 10))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 8))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 9))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 10))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 11))
	require.False(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 12))
}
