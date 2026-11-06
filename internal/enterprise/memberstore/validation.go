package memberstore

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"sync"
	"time"

	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/google/uuid"
	"gorm.io/gorm"
	glog "gorm.io/gorm/logger"
)

type validationKey struct{}

type validationAttempt struct {
	scope     types.WikiReleaseScope
	id        string
	db        *gorm.DB
	done      bool
	integrity bool
	mu        sync.Mutex
	refs      int
	kind      string
}

// Validate reserves durable evidence of an in-flight validation before any bytes are
// trusted. Nested producer/storage validations share a ticket only for the exact scope.
// A failed terminal write leaves the reservation, including across caller rollback/restart.
func (s *Store) Validate(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, fn func(context.Context) error,
) error {
	if scope.TenantID == 0 || scope.SpaceID == "" || scope.RawKBID == "" || scope.WikiKBID == "" {
		return ErrIntegrity
	}
	if parent, ok := ctx.Value(validationKey{}).(*validationAttempt); ok && parent.scope == scope {
		return fn(ctx)
	}
	a := &validationAttempt{scope: scope, id: uuid.NewString(), db: journalPool(db), refs: 1}
	if err := a.begin(ctx); err != nil {
		return err
	}
	observed := context.WithValue(ctx, validationKey{}, a)
	err := fn(observed)
	if endErr := a.finish(observed, err, false); endErr != nil && err == nil {
		return endErr
	}
	return err
}

// ValidationIntegrity marks producer protocol/digest failures without replacing its
// original error or exposing the failed member's bytes to the journal.
func ValidationIntegrity(ctx context.Context) {
	if a, ok := ctx.Value(validationKey{}).(*validationAttempt); ok {
		a.mu.Lock()
		a.integrity = true
		a.mu.Unlock()
	}
}

// A GORM transaction changes Statement.ConnPool, not Config.ConnPool. Rebinding to
// the configured root pool is intentional: telemetry must survive that tx's rollback.
func journalPool(db *gorm.DB) *gorm.DB {
	root := db.Session(&gorm.Session{NewDB: true, Context: context.Background()})
	root.Statement.ConnPool = db.ConnPool
	root.Logger = journalLogger{root.Logger}
	return root
}

type journalLogger struct{ glog.Interface }

func (l journalLogger) LogMode(level glog.LogLevel) glog.Interface {
	return journalLogger{l.Interface.LogMode(level)}
}

func (l journalLogger) Trace(ctx context.Context, started time.Time, sql func() (string, int64), err error) {
	_, n := sql()
	if err != nil {
		err = ErrState
	}
	l.Interface.Trace(ctx, started, func() (string, int64) { return "member validation journal", n }, err)
}

func validationLock(scope types.WikiReleaseScope) int64 {
	h := sha256.New()
	_, _ = h.Write([]byte("enterprise-member-validation.v1\x00"))
	var length [8]byte
	binary.BigEndian.PutUint64(length[:], scope.TenantID)
	_, _ = h.Write(length[:])
	for _, s := range []string{scope.SpaceID, scope.RawKBID, scope.WikiKBID} {
		binary.BigEndian.PutUint64(length[:], uint64(len(s)))
		_, _ = h.Write(length[:])
		_, _ = h.Write([]byte(s))
	}
	return int64(binary.BigEndian.Uint64(h.Sum(nil)[:8]))
}

func journalContext(ctx context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.WithoutCancel(ctx), 2*time.Second)
}

func journalError(ctx context.Context) error {
	logger.GetLogger(ctx).Error("member validation journal write failed")
	return ErrState
}

func (a *validationAttempt) begin(ctx context.Context) error {
	bounded, cancel := journalContext(ctx)
	defer cancel()
	// No FK or UPDATE of the scope row: Put's FOR UPDATE cannot block this INSERT.
	result := a.db.WithContext(bounded).Exec(`WITH admission AS MATERIALIZED
 (SELECT pg_advisory_xact_lock_shared(?), set_config('synchronous_commit','on',true))
 INSERT INTO enterprise_member_validation_pending(tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id)
 SELECT ?,?,?,?,? FROM admission`, validationLock(a.scope),
		a.scope.TenantID, a.scope.SpaceID, a.scope.RawKBID, a.scope.WikiKBID, a.id)
	if result.Error != nil || result.RowsAffected != 1 {
		return journalError(ctx)
	}
	return nil
}

func (a *validationAttempt) finish(ctx context.Context, failure error, probe bool) error {
	a.mu.Lock()
	if a.done {
		a.mu.Unlock()
		return nil
	}
	switch {
	case a.integrity || errors.Is(failure, ErrIntegrity):
		a.kind = "integrity"
	case failure != nil && !errors.Is(failure, ErrState) && !errors.Is(failure, gorm.ErrRecordNotFound):
		if a.kind == "" {
			a.kind = "gap"
		}
	}
	if probe && (a.refs != 1 || a.kind != "") {
		a.done = true
		a.mu.Unlock()
		return journalError(ctx)
	}
	a.refs--
	if a.refs > 0 {
		a.mu.Unlock()
		return nil
	}
	a.done = true // Failed finalization cannot later retry as successful cleanup.
	kind := a.kind
	if probe {
		kind = "probe"
	}
	a.mu.Unlock()
	bounded, cancel := journalContext(ctx)
	defer cancel()
	q := a.db.WithContext(bounded)
	args := []any{a.scope.TenantID, a.scope.SpaceID, a.scope.RawKBID, a.scope.WikiKBID, a.id}
	// Only successful cleanup may acknowledge before WAL flush. Losing this DELETE
	// after a crash resurrects a pending ticket and blocks maintenance conservatively.
	// Admission, failures and maintenance probes must remain synchronously durable.
	statement := `DELETE FROM enterprise_member_validation_pending
 WHERE tenant_id=? AND space_id=? AND raw_kb_id=? AND wiki_kb_id=? AND attempt_id=?
 AND set_config('synchronous_commit','off',true)='off'`
	if kind != "" {
		statement = `WITH recorded AS (
 INSERT INTO enterprise_member_validation_failures(tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id,kind)
 SELECT tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id,? FROM enterprise_member_validation_pending
 WHERE tenant_id=? AND space_id=? AND raw_kb_id=? AND wiki_kb_id=? AND attempt_id=?
 AND set_config('synchronous_commit','on',true)='on' RETURNING ` +
			`tenant_id,space_id,raw_kb_id,wiki_kb_id,attempt_id)
 DELETE FROM enterprise_member_validation_pending p USING recorded r WHERE p.attempt_id=r.attempt_id
 AND p.tenant_id=r.tenant_id AND p.space_id=r.space_id AND p.raw_kb_id=r.raw_kb_id AND p.wiki_kb_id=r.wiki_kb_id`
		args = append([]any{kind}, args...)
	}
	result := q.Exec(statement, args...)
	if result.Error != nil || result.RowsAffected != 1 {
		return journalError(ctx)
	}
	return nil
}

func (a *validationAttempt) completed() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.done
}

// RetainValidation extends the durable reservation through asynchronous work.
// The singleflight owner may outlive its canceled caller; every live waiter owns
// one lease until the actual flight result, even when its request returned early.
func RetainValidation(ctx context.Context) func(error) {
	a, ok := ctx.Value(validationKey{}).(*validationAttempt)
	if !ok {
		return func(error) {}
	}
	a.mu.Lock()
	if a.done {
		a.mu.Unlock()
		return func(error) {}
	}
	a.refs++
	a.mu.Unlock()
	var once sync.Once
	return func(err error) { once.Do(func() { _ = a.finish(ctx, err, false) }) }
}

// lockValidationGate serializes admission with the final checks through tx commit.
// Terminal failure writes never take this advisory lock and cannot block on the gate.
func lockValidationGate(ctx context.Context, tx *gorm.DB, sc scopeRow, window bool) error {
	a, ok := ctx.Value(validationKey{}).(*validationAttempt)
	if !ok || a.scope != sc.WikiReleaseScope || a.completed() {
		return ErrState
	}
	if err := tx.Exec(`SELECT pg_advisory_xact_lock(?)`, validationLock(a.scope)).Error; err != nil {
		return err
	}
	var pending int64
	if err := exactScope(tx.Table("enterprise_member_validation_pending"), a.scope).
		Where("attempt_id<>?", a.id).Count(&pending).Error; err != nil {
		return err
	}
	if pending != 0 {
		return ErrState
	}
	if window {
		var ready bool
		if err := tx.Raw(`SELECT observation_started_at <= clock_timestamp()-`+
			`observation_window_seconds*INTERVAL '1 second'
 AND read_failures=0 AND NOT EXISTS(SELECT 1 FROM enterprise_member_validation_failures f
 WHERE f.tenant_id=s.tenant_id AND f.space_id=s.space_id AND f.raw_kb_id=s.raw_kb_id
 AND f.wiki_kb_id=s.wiki_kb_id AND f.kind<>'probe' AND f.recorded_at>=`+
			`COALESCE(s.observation_failure_since,s.observation_started_at))
 FROM enterprise_member_scopes s WHERE id=?`, sc.ID).Scan(&ready).Error; err != nil {
			return err
		}
		if !ready {
			return ErrState
		}
	}
	return nil
}

// The validation outcome/channel probe must commit BEFORE the original transaction
// changes mode or deletes legacy rows. It never waits on the scope/admission locks.
func confirmValidation(ctx context.Context) error {
	a, ok := ctx.Value(validationKey{}).(*validationAttempt)
	if !ok {
		return ErrState
	}
	return a.finish(ctx, nil, true)
}
