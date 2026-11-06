package releasestore

import (
	"bytes"
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/sirupsen/logrus"
	"github.com/stretchr/testify/require"
)

func TestPostgresJournalAdmissionRecoversOnlyItsCommittedAttempt(t *testing.T) {
	for _, response := range []struct {
		name string
		err  error
	}{
		{"deadline", context.DeadlineExceeded},
		{"connection-state", &pgconn.PgError{Code: "08006"}},
		{"completion-unknown", &pgconn.PgError{Code: "40003"}},
	} {
		t.Run(response.name, func(t *testing.T) {
			db, _, id := observationFixture(t)
			fault := &receiptFault{stage: "admission", response: response.err}
			installReceiptFault(t, db, fault)
			out, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
			require.NoError(t, err, "the original reservation was independently proved committed")
			require.Len(t, out.Members, 70)
			require.True(t, fault.commitObserved.Load())
			require.EqualValues(t, 1, fault.writes.Load(), "do not resend the reservation")
			require.EqualValues(t, 1, fault.readbacks.Load(), "one exact consistent-state read")
			var pending int64
			require.NoError(t, db.Table("enterprise_member_validation_pending").Count(&pending).Error)
			require.Zero(t, pending)
		})
	}
}

func TestPostgresJournalCommittedProbeAllowsNormalMaintenance(t *testing.T) {
	for _, operation := range []string{"reference", "restore"} {
		t.Run(operation, func(t *testing.T) {
			db, _, id := observationFixture(t)
			want := storedSnapshots(t, db, id)
			fault := &receiptFault{stage: "terminal"}
			installReceiptFault(t, db, fault)
			store, scope := NewMemberStorage(), receiptScope(t)
			var err error
			if operation == "reference" {
				err = store.ReferenceOnly(context.Background(), db, scope)
			} else {
				err = store.RestoreLegacy(context.Background(), db, scope, 8<<20)
			}
			require.NoError(t, err, "a durable same-attempt probe is a recoverable lost response")
			require.True(t, fault.commitObserved.Load())
			require.EqualValues(t, 1, fault.writes.Load())
			require.EqualValues(t, 1, fault.readbacks.Load())
			if operation == "reference" {
				require.Equal(t, "reference", receiptMode(t, db))
			} else {
				require.Equal(t, "legacy", receiptMode(t, db))
				var marker string
				require.NoError(t, db.Table("wiki_releases").Where("release_id=?", id).
					Select("member_storage").Scan(&marker).Error)
				require.Empty(t, marker)
			}
			require.Equal(t, want, storedSnapshots(t, db, id))
		})
	}
}

func TestPostgresJournalRecoveredIntegrityRecordPreservesBusinessFailure(t *testing.T) {
	db, _, id := observationFixture(t)
	require.NoError(t, db.Exec("UPDATE enterprise_member_contents SET title='synthetic damaged title'").Error)
	fault := &receiptFault{stage: "terminal"}
	installReceiptFault(t, db, fault)
	var output bytes.Buffer
	log := logrus.New()
	log.SetOutput(&output)
	ctx := context.WithValue(context.Background(), types.LoggerContextKey, logrus.NewEntry(log))
	_, err := New(db, testSpaces(t)).ReleaseByID(ctx, 7, "space-1", id)
	require.Error(t, err, "recovering the log cannot turn corrupt member bytes into success")
	require.True(t, fault.commitObserved.Load())
	require.EqualValues(t, 1, fault.readbacks.Load())
	require.NotContains(t, output.String(), "member validation journal write failed")
	var kind string
	require.NoError(t, db.Table("enterprise_member_validation_failures").Where("attempt_id=?", fault.attempt).
		Select("kind").Scan(&kind).Error)
	require.Equal(t, "integrity", kind)
	require.Error(t, NewMemberStorage().ReferenceOnly(context.Background(), db, receiptScope(t)))
}

func TestPostgresJournalRecoveredGapPreservesOriginalBusinessError(t *testing.T) {
	db, _, _ := observationFixture(t)
	fault := &receiptFault{stage: "terminal"}
	installReceiptFault(t, db, fault)
	var output bytes.Buffer
	log := logrus.New()
	log.SetOutput(&output)
	ctx := context.WithValue(context.Background(), types.LoggerContextKey, logrus.NewEntry(log))
	err := NewMemberStorage().Validate(ctx, db, receiptScope(t), func(context.Context) error {
		return context.Canceled
	})
	require.ErrorIs(t, err, context.Canceled)
	require.True(t, fault.commitObserved.Load())
	require.EqualValues(t, 1, fault.readbacks.Load())
	require.NotContains(t, output.String(), "member validation journal write failed")
	var kind string
	require.NoError(t, db.Table("enterprise_member_validation_failures").Where("attempt_id=?", fault.attempt).
		Select("kind").Scan(&kind).Error)
	require.Equal(t, "gap", kind)
}

func TestPostgresJournalRecoveryNeverOverridesCallerCancellation(t *testing.T) {
	for _, stage := range []string{"admission", "terminal"} {
		t.Run(stage, func(t *testing.T) {
			db, _, id := observationFixture(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			fault := &receiptFault{stage: stage, afterCommit: cancel}
			installReceiptFault(t, db, fault)
			if stage == "admission" {
				out, err := New(db, testSpaces(t)).ReleaseByID(ctx, 7, "space-1", id)
				require.Error(t, err)
				require.Empty(t, out.Members)
			} else {
				require.Error(t, NewMemberStorage().ReferenceOnly(ctx, db, receiptScope(t)))
			}
			require.True(t, fault.commitObserved.Load())
			require.Positive(t, fault.readbacks.Load())
			require.Equal(t, "bridge", receiptMode(t, db), "canceled transaction must not change mode")
			require.Len(t, storedSnapshots(t, db, id), 70)
		})
	}
}

func TestPostgresJournalConfiguredBudgetAppliesToActualReadAdmission(t *testing.T) {
	db, _, id := observationFixture(t)
	require.NoError(t, db.Exec(`CREATE FUNCTION slow_journal_admission() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN PERFORM pg_sleep(2.15); RETURN NEW; END $$;
 CREATE TRIGGER slow_journal_admission BEFORE INSERT ON enterprise_member_validation_pending
 FOR EACH ROW EXECUTE FUNCTION slow_journal_admission()`).Error)
	t.Setenv(journalTimeoutEnv, "3")
	result, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.NoError(t, err, "the public read must use the configured budget beyond the old2s")
	require.Len(t, result.Members, 70)
}

func TestPostgresJournalInvalidConfigurationDoesNotBindLegacyReadsToWrites(t *testing.T) {
	for _, format := range []string{"", "bridge.v1"} {
		t.Run(format, func(t *testing.T) {
			db := memberStorageDB(t)
			want := storageMembers(t, 3, 0)
			r := storagePublish(t, New(db, testSpaces(t)), "journal-legacy-read", want)
			require.NoError(t, db.Exec("UPDATE wiki_releases SET member_storage=?", format).Error)
			require.NoError(t, db.Exec("UPDATE wiki_release_preparations SET member_storage=?", format).Error)
			ro, trace := readonlyStorageDB(t, db)
			t.Setenv(journalTimeoutEnv, "invalid")
			got, err := New(ro, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", r.ID)
			require.NoError(t, err)
			require.Equal(t, want, got.Members)
			require.Zero(t, trace.writes.Load())
		})
	}
}
