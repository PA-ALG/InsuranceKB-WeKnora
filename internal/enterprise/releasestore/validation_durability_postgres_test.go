package releasestore

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestPostgresHealthyValidationCleanupMayBeAsyncButCannotLeakSettings(t *testing.T) {
	db, _, id := observationFixture(t)
	pool, err := db.DB()
	require.NoError(t, err)
	pool.SetMaxOpenConns(1)
	require.NoError(t, db.Exec(`CREATE FUNCTION check_success_completion() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN IF current_setting('synchronous_commit')<>'off' THEN
 RAISE EXCEPTION 'healthy completion waited for WAL'; END IF; RETURN OLD; END $$;
 CREATE TRIGGER check_success_completion BEFORE DELETE ON enterprise_member_validation_pending
 FOR EACH ROW EXECUTE FUNCTION check_success_completion()`).Error)
	_, err = New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.NoError(t, err)
	var setting string
	require.NoError(t, db.Raw(`SHOW synchronous_commit`).Scan(&setting).Error)
	require.Equal(t, "on", setting, "cleanup change must be transaction-local")
}

func TestPostgresAdmissionFailureAndProbeAlwaysRequireSynchronousCommit(t *testing.T) {
	db, s, id := observationFixture(t)
	pool, err := db.DB()
	require.NoError(t, err)
	pool.SetMaxOpenConns(1)
	require.NoError(t, db.Exec(`CREATE FUNCTION check_durable_validation() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN IF current_setting('synchronous_commit')<>'on' THEN
 RAISE EXCEPTION 'validation evidence must be durable'; END IF; RETURN NEW; END $$;
 CREATE TRIGGER check_durable_start BEFORE INSERT ON enterprise_member_validation_pending
 FOR EACH ROW EXECUTE FUNCTION check_durable_validation();
 CREATE TRIGGER check_durable_failure BEFORE INSERT ON enterprise_member_validation_failures
 FOR EACH ROW EXECUTE FUNCTION check_durable_validation()`).Error)
	// An inherited session default must not silently weaken the observation evidence.
	require.NoError(t, db.Exec(`SET synchronous_commit=off`).Error)
	_, err = New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.NoError(t, err, "admission must force synchronous durability even from an async session")
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='damaged'`).Error)
	_, err = New(db, testSpaces(t)).ReleaseByID(context.Background(), 7, "space-1", id)
	require.Error(t, err)
	var failures int64
	require.NoError(t, db.Table("enterprise_member_validation_failures").Where("kind='integrity'").Count(&failures).Error)
	require.Positive(t, failures)
	var setting string
	require.NoError(t, db.Raw(`SHOW synchronous_commit`).Scan(&setting).Error)
	require.Equal(t, "off", setting, "critical durability change must not leak either")
	require.NoError(t, db.Exec(`SET synchronous_commit=on`).Error)
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title=''`).Error)
	pool.SetMaxOpenConns(3)
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	require.NoError(t, s.storage.StartObservation(context.Background(), db, sc), "maintenance probe remains synchronous")
}
