package releasestore

import (
	"bytes"
	"context"
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/sirupsen/logrus"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// Supplemental implementation regression: cancellation cannot end the ticket
// while the existing singleflight loader still owns untrusted decode work.
func TestPostgresObservationOutlivesCanceledSingleflightCaller(t *testing.T) {
	db, s, id := observationFixture(t)
	original := storedSnapshots(t, db, id)
	broken := append([]types.WikiReleaseMemberSnapshot(nil), original...)
	broken[0].Content = `{"v":99,"payload":"{}"}`
	replaceObservedSnapshots(t, db, s, id, broken)
	entered, resume := make(chan struct{}), make(chan struct{})
	var once, finish sync.Once
	releaseRead := func() { finish.Do(func() { close(resume) }) }
	defer releaseRead()
	require.NoError(t, db.Callback().Query().After("gorm:query").Register("canceled-validation", func(tx *gorm.DB) {
		if tx.Statement.TableExpr != nil && strings.Contains(tx.Statement.TableExpr.SQL, "enterprise_member_contents") {
			wait := false
			once.Do(func() { close(entered); wait = true })
			if wait {
				<-resume
			}
		}
	}))
	reader := New(db, testSpaces(t))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	returned := make(chan error, 1)
	go func() { _, err := reader.ReleaseByID(ctx, 7, "space-1", id); returned <- err }()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("loader did not pause after snapshot read")
	}
	cancel()
	select {
	case err := <-returned:
		require.ErrorIs(t, err, context.Canceled)
	case <-time.After(time.Second):
		t.Fatal("caller cancellation no longer returns promptly")
	}
	replaceObservedSnapshots(t, db, s, id, original)
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	require.Error(t, NewMemberStorage().StartObservation(context.Background(), db, sc),
		"a loader still processing old corrupt bytes must retain its reservation")
	releaseRead()
	_, _, _ = reader.members.flights.Do(fmt.Sprintf("%d:%q:%q", 7, "space-1", id), func() (any, error) {
		return nil, nil
	})
	require.Eventually(t, func() bool {
		var pending int64
		err := db.Table("enterprise_member_validation_pending").Count(&pending).Error
		return err == nil && pending == 0
	}, 3*time.Second, 10*time.Millisecond)
	var failures int64
	require.NoError(t, db.Table("enterprise_member_validation_failures").
		Where("kind='integrity'").Count(&failures).Error)
	require.Positive(t, failures, "late decode failure remains durable")
}

func TestPostgresObservationCannotValidateWhenAdmissionWriteFails(t *testing.T) {
	db, _, id := observationFixture(t)
	require.NoError(t, db.Exec(`CREATE FUNCTION reject_validation_start() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'synthetic private diagnostic'; END $$;
 CREATE TRIGGER reject_validation_start BEFORE INSERT ON enterprise_member_validation_pending
 FOR EACH ROW EXECUTE FUNCTION reject_validation_start()`).Error)
	var reads atomic.Int64
	require.NoError(t, db.Callback().Query().Before("gorm:query").Register("count-validation-reads", func(tx *gorm.DB) {
		// Format routing may read only the scoped release header before admission.
		if tx.Statement.Table != "wiki_releases" {
			reads.Add(1)
		}
	}))
	var output bytes.Buffer
	log := logrus.New()
	log.SetOutput(&output)
	ctx := context.WithValue(context.Background(), types.LoggerContextKey, logrus.NewEntry(log))
	_, err := New(db, testSpaces(t)).ReleaseByID(ctx, 7, "space-1", id)
	require.Error(t, err)
	require.Zero(t, reads.Load(), "cannot inspect bytes before recording admission")
	require.Contains(t, output.String(), "level=error")
	require.NotContains(t, output.String(), "synthetic private")
	require.NoError(t, db.Callback().Query().Remove("count-validation-reads"))
	sc, err := testSpaces(t).Scope(7, "space-1")
	require.NoError(t, err)
	require.Error(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc))
}
