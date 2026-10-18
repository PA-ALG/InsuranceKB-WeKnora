package database

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestSpotCheckMigrationIsThePackagedEnterpriseHead(t *testing.T) {
	require.Equal(t, uint(8), packagedEnterpriseMigrationHead)
	require.NoError(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 8))
	require.Error(t, validatePostgresMigrationSetVersion(enterprisePostgresMigrationSource, false, 7))
	require.True(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 8))
	require.False(t, enterpriseVersionKnownAtOfficialCheckpoint(releasedOfficial75Checkpoint, 9))
}
