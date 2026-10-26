package releasestore

import (
	"context"
	"errors"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

const candidateLookupSQL = `SELECT release_id FROM "wiki_releases" ` +
	`WHERE tenant_id = \$1 AND space_id = \$2 AND candidate_digest = \$3 ORDER BY created_at, release_id LIMIT \$4`

func expectCandidateLookup(mock sqlmock.Sqlmock, digest, id string) {
	rows := sqlmock.NewRows([]string{"release_id"})
	if id != "" {
		rows.AddRow(id)
	}
	mock.ExpectQuery(candidateLookupSQL).WithArgs(uint64(7), "space-1", digest, 1).WillReturnRows(rows)
}

func expectNoNonce(mock sqlmock.Sqlmock) {
	mock.ExpectQuery(`SELECT .* FROM "wiki_release_receipts"`).
		WithArgs("space-1", "wiki-1", "second-decision", 1).
		WillReturnRows(sqlmock.NewRows([]string{"release_id"}))
}

func TestReviewPublicationTransactionFindsConcurrentCommitBeforeSourceOrHeadWrites(t *testing.T) {
	store, mock := reviewSQL(t)
	ctx := context.Background()
	// No nonce or candidate was visible at the optimistic check. The transaction
	// observes the first publisher's commit only AFTER acquiring its candidate lock.
	expectNoNonce(mock)
	expectCandidateLookup(mock, "bundle", "")
	mock.ExpectBegin()
	mock.ExpectExec(`SELECT pg_advisory_xact_lock\(hashtextextended\(\$1, 0\)\)`).
		WithArgs(`[7,"space-1","bundle"]`).WillReturnResult(sqlmock.NewResult(0, 1))
	expectCandidateLookup(mock, "bundle", "original")
	mock.ExpectCommit()
	mock.ExpectQuery(`SELECT .* FROM "wiki_releases"`).
		WithArgs(uint64(7), "space-1", "raw-1", "wiki-1", "original", 1).
		WillReturnRows(sqlmock.NewRows([]string{"release_id", "preparation_id", "base_activation_epoch"}).
			AddRow("original", "prep", 3))
	mock.ExpectQuery(`SELECT "manifest" FROM "wiki_release_preparations"`).
		WithArgs("prep", uint64(7), "space-1", 1).
		WillReturnRows(sqlmock.NewRows([]string{"manifest"}).AddRow(
			`{"candidate_id":"candidate","decision_digest":"first-decision"}`))
	mock.ExpectQuery(`SELECT .* FROM "enterprise_release_retirements"`).
		WithArgs(uint64(7), "space-1", "original", 1).
		WillReturnRows(sqlmock.NewRows([]string{"retired_at"}))
	store.members.put(memberKey{Tenant: 7, Space: "space-1", Release: "original"}, nil)
	r, err := store.Activate(ctx, release.ActivationWrite{
		TenantID: 7, SpaceID: "space-1", CandidateID: "candidate", BundleDigest: "bundle",
		DecisionDigest: "second", Nonce: "second-decision",
		Members: []release.Member{{EvidenceRefs: []string{"source:v1:invalid"}}},
	})
	require.NoError(t, err)
	require.Equal(t, "original", r.ID)
	require.Equal(t, "first-decision", r.DecisionDigest)
	require.EqualValues(t, 4, r.Epoch)
	require.NoError(t, mock.ExpectationsWereMet(), "no source/Head/receipt writes on candidate replay")
}

func TestReviewPublicationFailureRollsBackCandidateLock(t *testing.T) {
	for _, lockFails := range []bool{false, true} {
		t.Run(map[bool]string{false: "source invalid", true: "lock failed"}[lockFails], func(t *testing.T) {
			store, mock := reviewSQL(t)
			expectNoNonce(mock)
			expectCandidateLookup(mock, "bundle", "")
			mock.ExpectBegin()
			lock := mock.ExpectExec(`SELECT pg_advisory_xact_lock`).WithArgs(`[7,"space-1","bundle"]`)
			failure := errors.New("lock failed")
			if lockFails {
				lock.WillReturnError(failure)
			} else {
				lock.WillReturnResult(sqlmock.NewResult(0, 1))
				expectCandidateLookup(mock, "bundle", "")
			}
			mock.ExpectRollback()
			expectNoNonce(mock)
			expectCandidateLookup(mock, "bundle", "")
			_, err := store.Activate(context.Background(), release.ActivationWrite{
				TenantID: 7, SpaceID: "space-1", BundleDigest: "bundle", Nonce: "second-decision",
				Members: []release.Member{{EvidenceRefs: []string{"source:v1:invalid"}}},
			})
			if lockFails {
				require.ErrorIs(t, err, failure)
			} else {
				var typed *release.Error
				require.ErrorAs(t, err, &typed)
				require.Equal(t, release.ErrorSourceUnavailable, typed.Code)
			}
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestReviewPublicationLookupIsScopedAndFailuresPropagate(t *testing.T) {
	store, mock := reviewSQL(t)
	ctx := context.Background()
	for _, scope := range []struct {
		tenant uint64
		space  string
	}{{8, "space-1"}, {7, "missing"}} {
		_, found, err := store.PublishedCandidate(ctx, scope.tenant, scope.space, "bundle")
		require.Error(t, err)
		require.False(t, found)
	}
	mock.ExpectQuery(candidateLookupSQL).WithArgs(uint64(7), "space-2", "bundle", 1).
		WillReturnRows(sqlmock.NewRows([]string{"release_id"}))
	_, found, err := store.PublishedCandidate(ctx, 7, "space-2", "bundle")
	require.NoError(t, err)
	require.False(t, found)
	failure := errors.New("read failed")
	mock.ExpectQuery(candidateLookupSQL).WithArgs(uint64(7), "space-1", "bundle", 1).WillReturnError(failure)
	_, found, err = store.PublishedCandidate(ctx, 7, "space-1", "bundle")
	require.ErrorIs(t, err, failure)
	require.False(t, found)
	require.NoError(t, mock.ExpectationsWereMet())
}
