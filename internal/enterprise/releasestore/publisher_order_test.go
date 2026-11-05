package releasestore

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func TestPublisherUnsortedInputFailsBeforeAnyDatabaseAccess(t *testing.T) {
	store, mock := reviewSQL(t)
	_, err := store.Activate(context.Background(), release.ActivationWrite{
		TenantID: 7,
		SpaceID:  "space-1", Members: []release.Member{
			{LogicalSlug: "b"},
			{LogicalSlug: "a"},
		},
	})
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorCandidateInvalid, failure.Code)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestPostgresPublisherUnsortedInputIsZeroWriteAndSortedInputPublishes(t *testing.T) {
	for _, withPoints := range []bool{false, true} {
		t.Run(map[bool]string{false: "whole", true: "points"}[withPoints], func(t *testing.T) {
			db := memberStorageDB(t)
			store := New(db, testSpaces(t))
			w := activation(t, store, "order")
			w.Members = storageMembers(t, 2, 0)
			w.Members[0].EvidenceRefs = []string{seedSource(t, db, "order-source", 7, "raw-1", 1)}
			if withPoints {
				w.Points = []release.PointDecision{{
					TenantID: 7, SpaceID: w.SpaceID,
					CandidateID: w.CandidateID, Slug: w.Members[0].LogicalSlug,
					Outcome: "approve", Subject: w.Subject,
				}}
			}
			w.Members[0], w.Members[1] = w.Members[1], w.Members[0]
			before := fullStorageCounts(t, db)
			before["enterprise_point_decisions"] = storageCount(t, db, "enterprise_point_decisions")
			counter := &storageQueryCounter{Interface: logger.Default.LogMode(logger.Silent)}
			_, err := New(db.Session(&gorm.Session{Logger: counter}), testSpaces(t)).Activate(context.Background(), w)
			var failure *release.Error
			require.ErrorAs(t, err, &failure)
			require.Equal(t, release.ErrorCandidateInvalid, failure.Code)
			require.Zero(t, counter.queries.Load(), "no DB access means no pin/decision/body mutation")
			after := fullStorageCounts(t, db)
			after["enterprise_point_decisions"] = storageCount(t, db, "enterprise_point_decisions")
			require.Equal(t, before, after)
			w.Members[0], w.Members[1] = w.Members[1], w.Members[0]
			got, err := store.Activate(context.Background(), w)
			require.NoError(t, err)
			require.Equal(t, w.Members, got.Members)
			require.EqualValues(t, 1, storageCount(t, db, "wiki_release_receipts"))
		})
	}
}
