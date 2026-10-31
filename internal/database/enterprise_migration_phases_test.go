package database

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/deploy/upstream"
	"github.com/stretchr/testify/require"
)

type recordingMigrationPhaseGuard struct {
	events *[]string
	err    error
}

func (g *recordingMigrationPhaseGuard) Release(context.Context) error {
	*g.events = append(*g.events, "release")
	return g.err
}

func TestRunPostgresMigrationPhasesOrdersPreflightOfficialEnterpriseRelease(t *testing.T) {
	var events []string
	acquire := func() (postgresMigrationPhaseGuard, error) {
		events = append(events, "raw_preflight_and_lock")
		return &recordingMigrationPhaseGuard{events: &events}, nil
	}
	official := func() error {
		events = append(events, "official_constructor_and_up")
		return nil
	}
	enterprise := func() error {
		events = append(events, "enterprise_constructor_and_up")
		return nil
	}

	err := runPostgresMigrationPhases(
		context.Background(),
		acquire,
		official,
		enterprise,
	)

	require.NoError(t, err)
	require.Equal(t, []string{
		"raw_preflight_and_lock",
		"official_constructor_and_up",
		"enterprise_constructor_and_up",
		"release",
	}, events)
}

func TestRunPostgresMigrationPhasesStopsAfterOfficialFailureAndReleases(t *testing.T) {
	var events []string
	officialErr := errors.New("official migration failed")
	err := runPostgresMigrationPhases(
		context.Background(),
		func() (postgresMigrationPhaseGuard, error) {
			events = append(events, "preflight")
			return &recordingMigrationPhaseGuard{events: &events}, nil
		},
		func() error {
			events = append(events, "official")
			return officialErr
		},
		func() error {
			events = append(events, "enterprise")
			return nil
		},
	)

	require.ErrorIs(t, err, officialErr)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.Equal(t, []string{"preflight", "official", "release"}, events)
}

func TestRunPostgresMigrationPhasesDoesNotLoseReleaseError(t *testing.T) {
	var events []string
	releaseErr := errors.New("unlock failed")

	err := runPostgresMigrationPhases(
		context.Background(),
		func() (postgresMigrationPhaseGuard, error) {
			return &recordingMigrationPhaseGuard{events: &events, err: releaseErr}, nil
		},
		func() error { return nil },
		func() error { return nil },
	)

	require.ErrorIs(t, err, releaseErr)
	var safetyErr *MigrationSafetyError
	require.ErrorAs(t, err, &safetyErr)
	require.Equal(t, []string{"release"}, events)
}

func TestEnterpriseMigrationDSNUsesIndependentLedger(t *testing.T) {
	got, err := enterpriseMigrationDSN(
		"postgres://user:pass@localhost:5432/weknora?sslmode=disable",
	)

	require.NoError(t, err)
	require.Contains(t, got, "x-migrations-table=enterprise_schema_migrations")
	require.Contains(t, got, "sslmode=disable")
}

func TestValidatePostgresMigrationSetVersionRequiresFrozenHeads(t *testing.T) {
	officialHead := uint(upstream.OfficialMigrationHead())
	require.NoError(t, validatePostgresMigrationSetVersion(
		officialPostgresMigrationSource,
		true,
		officialHead,
	))
	require.NoError(t, validatePostgresMigrationSetVersion(
		enterprisePostgresMigrationSource,
		false,
		packagedEnterpriseMigrationHead,
	))

	for _, tt := range []struct {
		source        string
		cacheOfficial bool
		version       uint
	}{
		{source: officialPostgresMigrationSource, cacheOfficial: true, version: officialHead - 1},
		{source: enterprisePostgresMigrationSource, version: 1},
	} {
		err := validatePostgresMigrationSetVersion(tt.source, tt.cacheOfficial, tt.version)
		var safetyErr *MigrationSafetyError
		require.ErrorAs(t, err, &safetyErr)
	}
}

func TestEnterpriseFailureDoesNotOverwriteOfficialMigrationCache(t *testing.T) {
	officialHead := uint(upstream.OfficialMigrationHead())
	oldVersion, oldDirty, oldKnown := CachedMigrationVersion()
	oldError := CachedMigrationError()
	t.Cleanup(func() {
		setMigrationState(oldVersion, oldDirty, oldError, oldKnown)
	})
	setMigrationState(officialHead, false, "", true)
	enterpriseErr := errors.New("enterprise migration failed")

	got := recordPostgresMigrationSetFailure(nil, false, enterpriseErr)

	require.ErrorIs(t, got, enterpriseErr)
	version, dirty, known := CachedMigrationVersion()
	require.True(t, known)
	require.Equal(t, officialHead, version)
	require.False(t, dirty)
	require.Empty(t, CachedMigrationError())
}
