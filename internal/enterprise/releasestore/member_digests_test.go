package releasestore

import (
	"context"
	"errors"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func expectDigestHeader(mock sqlmock.Sqlmock) {
	mock.ExpectQuery(`SELECT .* FROM "wiki_releases"`).
		WithArgs(uint64(7), "space-1", "raw-1", "wiki-1", "base", 1).
		WillReturnRows(sqlmock.NewRows([]string{"release_id", "preparation_id"}).AddRow("base", "prep"))
	mock.ExpectQuery(`SELECT "manifest" FROM "wiki_release_preparations"`).
		WithArgs("prep", uint64(7), "space-1", 1).
		WillReturnRows(sqlmock.NewRows([]string{"manifest"}).AddRow(`{"candidate_id":"candidate"}`))
	mock.ExpectQuery(`SELECT .* FROM "enterprise_release_retirements"`).
		WithArgs(uint64(7), "space-1", "base", 1).
		WillReturnRows(sqlmock.NewRows([]string{"retired_at"}))
}

func TestMemberDigestsReadNoPayloadAfterScopedHeaderValidation(t *testing.T) {
	store, mock := reviewSQL(t)
	expectDigestHeader(mock)
	mock.ExpectQuery(`SELECT "logical_slug","member_digest" FROM "wiki_release_members"`).
		WithArgs("base").WillReturnRows(sqlmock.NewRows([]string{"logical_slug", "member_digest"}).
		AddRow("a", "digest-a").AddRow("b", "digest-b"))
	digests, err := store.MembersOf(context.Background(), 7, "space-1", "base")
	require.NoError(t, err)
	require.Equal(t, map[string]string{"a": "digest-a", "b": "digest-b"}, digests)
	require.NoError(t, mock.ExpectationsWereMet(), "full member/content/payload SELECT is forbidden")
}

func TestMemberDigestsKeepScopeNotFoundAndReadErrors(t *testing.T) {
	t.Run("scope", func(t *testing.T) {
		store, mock := reviewSQL(t)
		for _, scope := range []struct {
			tenant uint64
			space  string
		}{{8, "space-1"}, {7, "other"}} {
			_, err := store.MembersOf(context.Background(), scope.tenant, scope.space, "base")
			require.Error(t, err)
		}
		require.NoError(t, mock.ExpectationsWereMet(), "invalid scope never reads members")
	})
	t.Run("not found", func(t *testing.T) {
		store, mock := reviewSQL(t)
		mock.ExpectQuery(`SELECT .* FROM "wiki_releases"`).
			WithArgs(uint64(7), "space-1", "raw-1", "wiki-1", "missing", 1).
			WillReturnRows(sqlmock.NewRows([]string{"release_id"}))
		_, err := store.MembersOf(context.Background(), 7, "space-1", "missing")
		var typed *release.Error
		require.ErrorAs(t, err, &typed)
		require.Equal(t, release.ErrorReleaseNotFound, typed.Code)
		require.NoError(t, mock.ExpectationsWereMet())
	})
	t.Run("read failure", func(t *testing.T) {
		store, mock := reviewSQL(t)
		expectDigestHeader(mock)
		failure := errors.New("member digest query failed")
		mock.ExpectQuery(`SELECT "logical_slug","member_digest" FROM "wiki_release_members"`).
			WithArgs("base").WillReturnError(failure)
		_, err := store.MembersOf(context.Background(), 7, "space-1", "base")
		require.ErrorIs(t, err, failure)
		require.NoError(t, mock.ExpectationsWereMet())
	})
}
