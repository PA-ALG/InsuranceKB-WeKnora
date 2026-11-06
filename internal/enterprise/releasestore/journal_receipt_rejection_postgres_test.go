package releasestore

import (
	"bytes"
	"context"
	"database/sql"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/sirupsen/logrus"
	"github.com/stretchr/testify/require"
)

func TestPostgresJournalUnknownResponsesRejectUnprovedStates(t *testing.T) {
	for _, item := range []struct {
		name, stage string
		before      bool
		readFails   bool
		mutate      func(*testing.T, *sql.Conn, string)
	}{
		{name: "admission-not-committed", stage: "admission", before: true},
		{name: "probe-not-committed-only-reservation", stage: "terminal", before: true},
		{name: "admission-readback-fails", stage: "admission", readFails: true},
		{name: "probe-readback-fails", stage: "terminal", readFails: true},
		{name: "admission-other-scope", stage: "admission", mutate: func(t *testing.T, c *sql.Conn, id string) {
			mutateReceipt(t, c,
				"UPDATE enterprise_member_validation_pending SET space_id='space-2' WHERE attempt_id=$1", id)
		}},
		{name: "admission-other-attempt", stage: "admission", mutate: func(t *testing.T, c *sql.Conn, id string) {
			_, err := c.ExecContext(context.Background(),
				"UPDATE enterprise_member_validation_pending SET attempt_id=$2 WHERE attempt_id=$1",
				id, uuid.NewString())
			require.NoError(t, err)
		}},
		{
			name: "matching-admission-with-foreign-terminal", stage: "admission",
			mutate: func(t *testing.T, c *sql.Conn, id string) {
				mutateReceipt(t, c, `INSERT INTO enterprise_member_validation_failures
 (tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id,kind)
 VALUES(7,'space-2','raw-2','wiki-2',$1,'probe')`, id)
			},
		},
		{name: "admission-missing-after-write", stage: "admission", mutate: func(t *testing.T, c *sql.Conn, id string) {
			mutateReceipt(t, c, "DELETE FROM enterprise_member_validation_pending WHERE attempt_id=$1", id)
		}},
		{name: "admission-has-only-terminal", stage: "admission", mutate: func(t *testing.T, c *sql.Conn, id string) {
			mutateReceipt(t, c, "DELETE FROM enterprise_member_validation_pending WHERE attempt_id=$1", id)
			mutateReceipt(t, c, `INSERT INTO enterprise_member_validation_failures
 (tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id,kind)
 VALUES(7,'space-1','raw-1','wiki-1',$1,'probe')`, id)
		}},
		{name: "probe-wrong-kind", stage: "terminal", mutate: func(t *testing.T, c *sql.Conn, id string) {
			mutateReceipt(t, c, "UPDATE enterprise_member_validation_failures SET kind='gap' WHERE attempt_id=$1", id)
		}},
		{name: "probe-other-scope", stage: "terminal", mutate: func(t *testing.T, c *sql.Conn, id string) {
			mutateReceipt(t, c,
				"UPDATE enterprise_member_validation_failures SET space_id='space-2' WHERE attempt_id=$1", id)
		}},
		{name: "probe-missing", stage: "terminal", mutate: func(t *testing.T, c *sql.Conn, id string) {
			mutateReceipt(t, c, "DELETE FROM enterprise_member_validation_failures WHERE attempt_id=$1", id)
		}},
		{name: "probe-with-reservation", stage: "terminal", mutate: func(t *testing.T, c *sql.Conn, id string) {
			mutateReceipt(t, c, `INSERT INTO enterprise_member_validation_pending
 (tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id)VALUES(7,'space-1','raw-1','wiki-1',$1)`, id)
		}},
		{name: "probe-with-foreign-reservation", stage: "terminal", mutate: func(t *testing.T, c *sql.Conn, id string) {
			mutateReceipt(t, c, `INSERT INTO enterprise_member_validation_pending
 (tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id)VALUES(7,'space-2','raw-2','wiki-2',$1)`, id)
		}},
	} {
		t.Run(item.name, func(t *testing.T) {
			db, _, id := observationFixture(t)
			before := storedSnapshots(t, db, id)
			fault := &receiptFault{stage: item.stage, beforeCommit: item.before, readbackFails: item.readFails}
			if item.mutate != nil {
				fault.mutate = func(c *sql.Conn, id string) { item.mutate(t, c, id) }
			}
			installReceiptFault(t, db, fault)
			var output bytes.Buffer
			log := logrus.New()
			log.SetOutput(&output)
			ctx := context.WithValue(context.Background(), types.LoggerContextKey, logrus.NewEntry(log))
			if item.stage == "admission" {
				out, err := New(db, testSpaces(t)).ReleaseByID(ctx, 7, "space-1", id)
				require.Error(t, err)
				require.Empty(t, out.Members)
			} else {
				require.Error(t, NewMemberStorage().ReferenceOnly(ctx, db, receiptScope(t)))
			}
			require.Equal(t, !item.before, fault.commitObserved.Load())
			require.EqualValues(t, 1, fault.writes.Load(), "no write retries with a fresh or reused identity")
			require.EqualValues(t, 1, fault.readbacks.Load(), "one bounded read, not a polling loop")
			require.Equal(t, "bridge", receiptMode(t, db))
			require.Equal(t, before, storedSnapshots(t, db, id))
			require.Contains(t, output.String(), "level=error")
			require.NotContains(t, output.String(), "synthetic private readback")
		})
	}
}

func TestPostgresJournalUnknownHealthyCleanupCannotUseAbsenceAsReceipt(t *testing.T) {
	db, _, id := observationFixture(t)
	fault := &receiptFault{stage: "cleanup"}
	installReceiptFault(t, db, fault)
	_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.Error(t, err, "absence alone is not a durable completion receipt")
	require.True(t, fault.commitObserved.Load())
	require.EqualValues(t, 1, fault.readbacks.Load())
	var pending, terminal int64
	require.NoError(t, db.Table("enterprise_member_validation_pending").
		Where("attempt_id=?", fault.attempt).Count(&pending).Error)
	require.NoError(t, db.Table("enterprise_member_validation_failures").
		Where("attempt_id=?", fault.attempt).Count(&terminal).Error)
	require.Zero(t, pending)
	require.Zero(t, terminal)
}

func TestPostgresJournalDefiniteRejectionDoesNotTrustAnExistingRow(t *testing.T) {
	db, _, id := observationFixture(t)
	fault := &receiptFault{stage: "admission", response: &pgconn.PgError{Code: "42501"}}
	installReceiptFault(t, db, fault)
	_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.Error(t, err, "a definite rejection cannot be converted using convenient metadata")
	require.True(t, fault.commitObserved.Load(),
		"the forged response control deliberately leaves an otherwise matching row")
	require.Zero(t, fault.readbacks.Load())
	require.EqualValues(t, 1, fault.writes.Load())
}
