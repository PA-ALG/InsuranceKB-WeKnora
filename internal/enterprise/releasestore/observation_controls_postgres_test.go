package releasestore

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/memberstore"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestPostgresObservationNotFoundIsNotAnIntegrityFailure(t *testing.T) {
	db, s, _ := observationFixture(t)
	_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", "nonexistent")
	var typed *release.Error
	require.ErrorAs(t, err, &typed)
	require.Equal(t, release.ErrorReleaseNotFound, typed.Code)
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	require.NoError(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc))
}

func TestPostgresObservationFailureUsesAllFourScopeFields(t *testing.T) {
	for _, field := range []string{"tenant", "space", "raw", "wiki"} {
		t.Run(field, func(t *testing.T) {
			db, s, _ := observationFixture(t)
			sc, err := s.spaces.Scope(7, "space-1")
			require.NoError(t, err)
			other := sc
			switch field {
			case "tenant":
				other.TenantID++
			case "space":
				other.SpaceID += "-other"
			case "raw":
				other.RawKBID += "-other"
			case "wiki":
				other.WikiKBID += "-other"
			}
			err = NewMemberStorage().Validate(context.Background(), db, other, func(context.Context) error { return memberstore.ErrIntegrity })
			require.ErrorIs(t, err, memberstore.ErrIntegrity)
			require.NoError(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc))
			var failure struct {
				types.WikiReleaseScope
				Kind string
			}
			require.NoError(t, db.Table("enterprise_member_validation_failures").Where("kind='integrity'").Take(&failure).Error)
			require.Equal(t, other, failure.WikiReleaseScope)
		})
	}
}
