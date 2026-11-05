package releasestore

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/sirupsen/logrus"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func observationFixture(t *testing.T) (*gorm.DB, *Store, string) {
	t.Helper()
	db := memberStorageDB(t)
	s := New(db, testSpaces(t))
	r := storagePublish(t, s, "observed", storageMembers(t, 70, 0))
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	require.NoError(t, s.storage.StartObservation(context.Background(), db, sc))
	ageObservation(t, db)
	return db, s, r.ID
}

func ageObservation(t *testing.T, db *gorm.DB) {
	t.Helper()
	require.NoError(t, db.Exec(
		`UPDATE enterprise_member_scopes SET observation_started_at=clock_timestamp()-INTERVAL '8 days'`).Error)
}

func TestPostgresObservationFailureSurvivesActivationScopeLock(t *testing.T) {
	db, s, id := observationFixture(t)
	locked, resume := make(chan struct{}), make(chan struct{})
	var once sync.Once
	releaseLock := func() { once.Do(func() { close(resume) }) }
	defer releaseLock()
	require.NoError(t, db.Callback().Create().After("gorm:create").Register(
		"observation-held-activation", func(tx *gorm.DB) {
			if tx.Statement.Table == "enterprise_member_sets" {
				close(locked)
				<-resume
			}
		}))
	w := activation(t, s, "concurrent-observed")
	w.Members = storageMembers(t, 70, 1)
	done := make(chan error, 1)
	go func() { _, err := s.Activate(context.Background(), w); done <- err }()
	select {
	case <-locked:
	case <-time.After(5 * time.Second):
		t.Fatal("activation did not reach locked Put")
	}
	require.NoError(t, db.Exec(
		`UPDATE enterprise_member_contents SET title='damaged' WHERE logical_slug='group/000001'`).Error)
	read := make(chan error, 1)
	go func() {
		_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
		read <- err
	}()
	select {
	case err := <-read:
		require.Error(t, err)
	case <-time.After(3 * time.Second):
		t.Fatal("failure record blocked behind activation scope lock")
	}
	releaseLock()
	require.NoError(t, <-done)
	require.NoError(t, db.Callback().Create().Remove("observation-held-activation"))
	require.NoError(t, db.Exec(
		`UPDATE enterprise_member_contents SET title='' WHERE logical_slug='group/000001'`).Error)
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	require.Error(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc),
		"an activation lock must not erase a failed read from the observation gate")
	var failures int64
	require.NoError(t, db.Table("enterprise_member_validation_failures").
		Where("kind='integrity'").Count(&failures).Error)
	require.Positive(t, failures)
}

func TestPostgresObservationIncludesReleaseDecoderFailures(t *testing.T) {
	for _, field := range []string{"content", "member_digest"} {
		t.Run(field, func(t *testing.T) {
			db, s, id := observationFixture(t)
			require.NoError(t, db.Exec(`UPDATE wiki_releases SET member_storage='bridge.v1'`).Error)
			var before types.WikiReleaseMember
			require.NoError(t, db.Where("release_id=?", id).Order("logical_slug ASC").First(&before).Error)
			value := strings.Repeat("a", 64)
			if field == "content" {
				value = `{"v":99,"payload":"{}"}`
			}
			require.NoError(t, db.Model(&types.WikiReleaseMember{}).Where("id=?", before.ID).Update(field, value).Error)
			_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
			require.Error(t, err)
			original := before.MemberDigest
			if field == "content" {
				original = before.Content
			}
			require.NoError(t, db.Model(&types.WikiReleaseMember{}).
				Where("id=?", before.ID).Update(field, original).Error)
			sc, err := s.spaces.Scope(7, "space-1")
			require.NoError(t, err)
			require.Error(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc),
				"producer decode/business digest failure must invalidate observation")
		})
	}
}

func failJournalTerminal(t *testing.T, db *gorm.DB) {
	t.Helper()
	require.NoError(t, db.Exec(`CREATE FUNCTION reject_validation_record() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'synthetic private diagnostic must not escape'; END $$;
 CREATE TRIGGER reject_validation_record BEFORE INSERT ON enterprise_member_validation_failures
 FOR EACH ROW EXECUTE FUNCTION reject_validation_record()`).Error)
}

func TestPostgresObservationRecordOutageIsDurableAndLogged(t *testing.T) {
	db, s, id := observationFixture(t)
	failJournalTerminal(t, db)
	require.NoError(t, db.Exec(
		`UPDATE enterprise_member_contents SET title='damaged' WHERE logical_slug='group/000001'`).Error)
	var output bytes.Buffer
	log := logrus.New()
	log.SetOutput(&output)
	ctx := context.WithValue(context.Background(), types.LoggerContextKey, logrus.NewEntry(log))
	_, err := New(db, testSpaces(t)).ReleaseByID(ctx, 7, "space-1", id)
	require.Error(t, err)
	require.Contains(t, output.String(), "level=error")
	require.NotContains(t, output.String(), "synthetic private diagnostic")
	require.NoError(t, db.Exec(`DROP TRIGGER reject_validation_record ON enterprise_member_validation_failures`).Error)
	require.NoError(t, db.Exec(
		`UPDATE enterprise_member_contents SET title='' WHERE logical_slug='group/000001'`).Error)
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	fresh := NewMemberStorage()
	require.Error(t, fresh.ReferenceOnly(context.Background(), db, sc),
		"new Store must see durable incomplete recording")
	require.NoError(t, db.Exec(`UPDATE enterprise_member_scopes SET mode='reference'`).Error)
	before := storageCount(t, db, "wiki_release_members")
	require.Error(t, fresh.CompactLegacy(context.Background(), db, sc))
	require.Equal(t, before, storageCount(t, db, "wiki_release_members"))
	require.Error(t, fresh.StartObservation(context.Background(), db, sc), "unresolved gaps cannot silently reset")
}

func TestPostgresObservationGateChecksRecordingBeforeMutation(t *testing.T) {
	for _, op := range []string{"reference", "compact"} {
		t.Run(op, func(t *testing.T) {
			db, s, _ := observationFixture(t)
			sc, err := s.spaces.Scope(7, "space-1")
			require.NoError(t, err)
			if op == "compact" {
				require.NoError(t, s.storage.ReferenceOnly(context.Background(), db, sc))
			}
			failJournalTerminal(t, db)
			before := storageCount(t, db, "wiki_release_members")
			if op == "reference" {
				err = s.storage.ReferenceOnly(context.Background(), db, sc)
			} else {
				err = s.storage.CompactLegacy(context.Background(), db, sc)
			}
			require.Error(t, err, "logging unavailable must stop before mode/delete commit")
			require.Equal(t, before, storageCount(t, db, "wiki_release_members"))
			var mode string
			require.NoError(t, db.Table("enterprise_member_scopes").Select("mode").Scan(&mode).Error)
			if op == "reference" {
				require.Equal(t, "bridge", mode)
			}
		})
	}
}

func TestPostgresObservationCancellationAndCallerRollbackCannotHideGap(t *testing.T) {
	for _, aborted := range []bool{false, true} {
		t.Run(map[bool]string{false: "cancel", true: "aborted-tx"}[aborted], func(t *testing.T) {
			db, s, id := observationFixture(t)
			sc, err := s.spaces.Scope(7, "space-1")
			require.NoError(t, err)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			tx := db.Begin()
			require.NoError(t, tx.Error)
			if aborted {
				require.Error(t, tx.Exec(`SELECT 1/0`).Error)
			} else {
				cancel()
			}
			_, err = s.storage.Read(ctx, tx, sc, id)
			require.Error(t, err)
			if !aborted {
				require.True(t, errors.Is(err, context.Canceled))
			}
			require.NoError(t, tx.Rollback().Error)
			require.Error(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc),
				"gap survives caller rollback")
		})
	}
}

func TestPostgresObservationNoFaultPromotionAndCompaction(t *testing.T) {
	db, s, id := observationFixture(t)
	_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.NoError(t, err)
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	require.NoError(t, s.storage.ReferenceOnly(context.Background(), db, sc))
	require.NoError(t, s.storage.CompactLegacy(context.Background(), db, sc))
	_, err = New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.NoError(t, err)
}

func TestPostgresObservationGateCannotOvertakeInFlightValidation(t *testing.T) {
	db, s, id := observationFixture(t)
	entered, resume := make(chan struct{}), make(chan struct{})
	var once sync.Once
	var finish sync.Once
	releaseRead := func() { finish.Do(func() { close(resume) }) }
	defer releaseRead()
	require.NoError(t, db.Callback().Query().After("gorm:query").Register("observation-paused-read", func(tx *gorm.DB) {
		if tx.Statement.TableExpr != nil && strings.Contains(tx.Statement.TableExpr.SQL, "enterprise_member_contents") {
			shouldWait := false
			once.Do(func() { close(entered); shouldWait = true })
			if shouldWait {
				<-resume
			}
		}
	}))
	done := make(chan error, 1)
	go func() {
		_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
		done <- err
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("reader did not enter full content validation")
	}
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	err = NewMemberStorage().ReferenceOnly(context.Background(), db, sc)
	releaseRead()
	require.NoError(t, <-done)
	require.NoError(t, db.Callback().Query().Remove("observation-paused-read"))
	require.Error(t, err, "cutover must not overtake an admitted but unfinished read")
	require.NoError(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc))
}

func TestPostgresSuccessfulReadCannotHideFinalizationOutage(t *testing.T) {
	db, _, id := observationFixture(t)
	require.NoError(t, db.Exec(`CREATE FUNCTION reject_validation_finish() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'synthetic private diagnostic'; END $$;
 CREATE TRIGGER reject_validation_finish BEFORE DELETE ON enterprise_member_validation_pending
 FOR EACH ROW EXECUTE FUNCTION reject_validation_finish()`).Error)
	_, err := New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.Error(t, err, "successful validation with unrecorded completion is an observation gap")
	require.NoError(t, db.Exec(`DROP TRIGGER reject_validation_finish ON enterprise_member_validation_pending`).Error)
	sc, err := testSpaces(t).Scope(7, "space-1")
	require.NoError(t, err)
	require.Error(t, NewMemberStorage().ReferenceOnly(context.Background(), db, sc))
}
