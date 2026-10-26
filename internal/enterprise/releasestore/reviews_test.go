package releasestore

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func reviewSQL(t *testing.T) (*Store, sqlmock.Sqlmock) {
	t.Helper()
	db, mock, err := sqlmock.New()
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })
	orm, err := gorm.Open(postgres.New(postgres.Config{Conn: db}), &gorm.Config{DisableAutomaticPing: true})
	require.NoError(t, err)
	return New(orm, testSpaces(t)), mock
}

// The adapter has exactly one query even with several candidates. The protected PG tests
// exercise real SQL status derivation; this offline test checks binds, joins and row mapping.
func TestReviewSQLUsesOneScopedOrderedQueryAndPreservesMetadata(t *testing.T) {
	now := time.Date(2026, 10, 26, 10, 0, 0, 0, time.UTC)
	d := release.Decision{
		ID: "decision-a", TenantID: 7, SpaceID: "space-1", CandidateID: "candidate-a",
		BundleDigest: "digest-a", Outcome: "approve", Mode: "human", Subject: "web_user:a", Reason: "checked",
		Digest: "decision-digest", CreatedAt: now,
	}
	raw, err := json.Marshal(d)
	require.NoError(t, err)
	for _, status := range []string{"pending", "decided"} {
		t.Run(status, func(t *testing.T) {
			store, mock := reviewSQL(t)
			query := `(?s)WITH queue AS .*CASE WHEN r.release_id IS NOT NULL THEN 'released'.*` +
				`d.tenant_id = c.tenant_id AND d.space_id = c.space_id AND d.candidate_id = c.id.*` +
				`ORDER BY d.created_at DESC, d.id DESC LIMIT 1.*` +
				`r.tenant_id = c.tenant_id AND r.space_id = c.space_id AND r.candidate_digest = c.bundle_digest.*` +
				`WHERE c.tenant_id = \$1 AND c.space_id = \$2.*`
			columns := []string{
				"id", "tenant_id", "space_id", "bundle_digest", "contract_version", "base_release_id",
				"created_by", "created_at", "review_status", "decision_json", "release_id",
			}
			rows := sqlmock.NewRows(columns)
			if status == "pending" {
				query += `= 'pending' ORDER BY created_at ASC, id ASC$`
				rows.AddRow("candidate-a", 7, "space-1", "digest-a", "1", "base", "writer", now, "pending", nil, "")
				rows.AddRow("candidate-b", 7, "space-1", "digest-b", "1", "base", "writer", now, "pending", nil, "")
				mock.ExpectQuery(query).WithArgs(uint64(7), "space-1").WillReturnRows(rows)
			} else {
				query += `<> 'pending' ORDER BY created_at DESC, id DESC LIMIT \$3$`
				rows.AddRow("candidate-a", 7, "space-1", "digest-a", "1", "base",
					"writer", now, "released", raw, "rel-a")
				mock.ExpectQuery(query).WithArgs(uint64(7), "space-1", 2).WillReturnRows(rows)
			}
			entries, err := store.Queue(context.Background(), 7, "space-1", status, 2)
			require.NoError(t, err)
			require.Equal(t, "candidate-a", entries[0].Candidate.ID)
			require.Equal(t, uint64(7), entries[0].Candidate.TenantID)
			require.Equal(t, "space-1", entries[0].Candidate.SpaceID)
			require.Equal(t, "digest-a", entries[0].Candidate.BundleDigest)
			require.Equal(t, "writer", entries[0].CreatedBy)
			require.Equal(t, now, entries[0].CreatedAt)
			if status == "pending" {
				require.Len(t, entries, 2)
				require.Nil(t, entries[0].Decision)
			} else {
				require.Equal(t, "released", entries[0].Candidate.Status)
				require.Equal(t, &d, entries[0].Decision)
				require.Equal(t, "rel-a", entries[0].ReleaseID)
			}
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestReviewSQLUnconfiguredScopesAndInvalidFiltersDoNotQuery(t *testing.T) {
	store, mock := reviewSQL(t)
	for _, scope := range []struct {
		tenant uint64
		space  string
	}{{8, "space-1"}, {7, "missing"}} {
		items, err := store.Queue(context.Background(), scope.tenant, scope.space, "pending", 100)
		require.NoError(t, err)
		require.Empty(t, items)
	}
	_, err := store.Queue(context.Background(), 7, "space-1", "all", 100)
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorDecisionInvalid, failure.Code)
	items, err := store.Queue(context.Background(), 7, "space-1", "decided", 0)
	require.NoError(t, err)
	require.Empty(t, items)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestReviewSQLPropagatesQueryErrorWithoutReturningPartialRows(t *testing.T) {
	store, mock := reviewSQL(t)
	failure := errors.New("offline query failed")
	mock.ExpectQuery(`WITH queue AS`).WithArgs(uint64(7), "space-1").WillReturnError(failure)
	items, err := store.Queue(context.Background(), 7, "space-1", "pending", 100)
	require.ErrorIs(t, err, failure)
	require.Nil(t, items)
	require.NoError(t, mock.ExpectationsWereMet())
}
