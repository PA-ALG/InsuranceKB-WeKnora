package releasestore

import (
	"context"
	"errors"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func expectPointModeLock(mock sqlmock.Sqlmock) {
	mock.ExpectExec(`SELECT pg_advisory_xact_lock`).WithArgs(`["review",7,"space-1","candidate"]`).
		WillReturnResult(sqlmock.NewResult(0, 1))
}

func expectWholeUndecided(mock sqlmock.Sqlmock) {
	mock.ExpectQuery(`SELECT .* FROM "enterprise_candidates"`).WithArgs(uint64(7), "space-1", "candidate", 1).
		WillReturnRows(sqlmock.NewRows([]string{"id", "bundle_digest"}).AddRow("candidate", "original"))
	mock.ExpectQuery(`SELECT count\(\*\) FROM "enterprise_decisions"`).WithArgs(uint64(7), "space-1", "candidate").
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(0))
	expectCandidateLookup(mock, "original", "")
}

func ownPoint(slug, outcome string) release.PointDecision {
	return release.PointDecision{
		TenantID: 7, SpaceID: "space-1", CandidateID: "candidate", Slug: slug,
		Outcome: outcome, Reason: "checked", Subject: "user",
	}
}

func TestPointRejectInsertFailureRollsBackWholeBatch(t *testing.T) {
	store, mock := reviewSQL(t)
	mock.ExpectBegin()
	expectPointModeLock(mock)
	expectWholeUndecided(mock)
	mock.ExpectQuery(`SELECT count\(\*\) FROM "enterprise_point_decisions"`).
		WithArgs(uint64(7), "space-1", "candidate", "a", "b").
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(0))
	failure := errors.New("insert failed")
	mock.ExpectExec(`INSERT INTO "enterprise_point_decisions"`).WillReturnError(failure)
	mock.ExpectRollback()
	err := store.RejectPoints(context.Background(), []release.PointDecision{
		ownPoint("a", "reject"), ownPoint("b", "reject"),
	})
	require.ErrorIs(t, err, failure)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestPointWholeDecisionRechecksPointsWhileHoldingModeLock(t *testing.T) {
	store, mock := reviewSQL(t)
	mock.ExpectBegin()
	expectPointModeLock(mock)
	mock.ExpectQuery(`SELECT count\(\*\) FROM "enterprise_point_decisions"`).
		WithArgs(uint64(7), "space-1", "candidate").WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	mock.ExpectRollback()
	_, err := store.SaveDecision(context.Background(), release.Decision{
		TenantID: 7, SpaceID: "space-1", CandidateID: "candidate", Outcome: "approve", Digest: "whole",
	})
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorCandidateDecided, failure.Code)
	require.NoError(t, mock.ExpectationsWereMet(), "no whole decision insertion after a point won the lock")
}

func TestPointActivationConflictWritesNeitherHeadNorDecision(t *testing.T) {
	store, mock := reviewSQL(t)
	expectNoNonce(mock)
	expectCandidateLookup(mock, "batch", "")
	mock.ExpectBegin()
	expectPointModeLock(mock)
	mock.ExpectExec(`SELECT pg_advisory_xact_lock`).WithArgs(`[7,"space-1","batch"]`).
		WillReturnResult(sqlmock.NewResult(0, 1))
	expectCandidateLookup(mock, "batch", "")
	expectWholeUndecided(mock)
	mock.ExpectQuery(`SELECT count\(\*\) FROM "enterprise_point_decisions"`).
		WithArgs(uint64(7), "space-1", "candidate", "a").WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	mock.ExpectRollback()
	expectNoNonce(mock)
	expectCandidateLookup(mock, "batch", "")
	_, err := store.Activate(context.Background(), release.ActivationWrite{
		TenantID: 7, SpaceID: "space-1", CandidateID: "candidate", BundleDigest: "batch", Nonce: "second-decision",
		Subject: "user", Points: []release.PointDecision{ownPoint("a", "approve")},
	})
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorMemberDecided, failure.Code)
	require.NoError(t, mock.ExpectationsWereMet(), "no Head, source pins, or release writes on conflict")
}

func TestPointStoreRejectsMixedScopeAndInvalidWritesBeforeSQL(t *testing.T) {
	store, mock := reviewSQL(t)
	for _, mutate := range []func(*release.PointDecision){
		func(p *release.PointDecision) { p.TenantID = 8 },
		func(p *release.PointDecision) { p.SpaceID = "space-2" },
		func(p *release.PointDecision) { p.CandidateID = "foreign" },
		func(p *release.PointDecision) { p.Outcome = "approve" },
		func(p *release.PointDecision) { p.Subject = "another" },
		func(p *release.PointDecision) { p.ReleaseID = "unexpected" },
	} {
		ds := []release.PointDecision{ownPoint("a", "reject"), ownPoint("b", "reject")}
		mutate(&ds[1])
		err := store.RejectPoints(context.Background(), ds)
		var failure *release.Error
		require.ErrorAs(t, err, &failure)
		require.Equal(t, release.ErrorDecisionInvalid, failure.Code)
	}
	_, err := store.Activate(context.Background(), release.ActivationWrite{
		TenantID: 8, SpaceID: "space-1", CandidateID: "candidate", Subject: "user",
		Points: []release.PointDecision{ownPoint("a", "approve")},
	})
	require.Error(t, err)
	require.NoError(t, mock.ExpectationsWereMet())
}
