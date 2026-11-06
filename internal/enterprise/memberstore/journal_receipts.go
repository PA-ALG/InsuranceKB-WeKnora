package memberstore

import (
	"context"
	"errors"
	"net"

	"github.com/Tencent/WeKnora/internal/types"
)

// Only an explicit server rejection proves that the statement could not commit.
// Connection states, completion unknown (40003), and unrecognized errors require
// reconciliation even when a driver supplies a SQLSTATE or an affected-row count.
func definiteJournalRejection(err error) bool {
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return false
	}
	var network net.Error
	if errors.As(err, &network) {
		return false
	}
	var server interface{ SQLState() string }
	if !errors.As(err, &server) {
		return false
	}
	code := server.SQLState()
	if len(code) == 5 && code[:2] == "23" {
		return true // Integrity-constraint rejection, including a duplicate reservation.
	}
	switch code {
	case "42501", "25006", "40001", "40P01", "55P03", "57014":
		return true
	default:
		return false
	}
}

func (a *validationAttempt) executeJournal(
	ctx context.Context, statement string, args []any, admission bool, kind string,
) error {
	bounded, cancel := a.policy.writeContext(ctx)
	result := a.db.WithContext(bounded).Exec(statement, args...)
	cancel()
	if result.Error == nil {
		if result.RowsAffected == 1 {
			return nil
		}
		return journalError(ctx)
	}
	if !definiteJournalRejection(result.Error) && a.recoverJournalReceipt(ctx, admission, kind) {
		return nil
	}
	return journalError(ctx)
}

type journalIdentity struct {
	TenantID  *uint64 `gorm:"column:tenant_id"`
	SpaceID   *string `gorm:"column:space_id"`
	RawKBID   *string `gorm:"column:raw_kb_id"`
	WikiKBID  *string `gorm:"column:wiki_kb_id"`
	AttemptID *string `gorm:"column:attempt_id"`
}

func (r journalIdentity) matches(scope types.WikiReleaseScope, id string) bool {
	return r.TenantID != nil && *r.TenantID == scope.TenantID &&
		r.SpaceID != nil && *r.SpaceID == scope.SpaceID &&
		r.RawKBID != nil && *r.RawKBID == scope.RawKBID &&
		r.WikiKBID != nil && *r.WikiKBID == scope.WikiKBID &&
		r.AttemptID != nil && *r.AttemptID == id
}

type journalReceipt struct {
	Pending        journalIdentity `gorm:"embedded;embeddedPrefix:pending_"`
	Terminal       journalIdentity `gorm:"embedded;embeddedPrefix:terminal_"`
	TerminalKind   *string
	PendingExists  bool
	TerminalExists bool
}

func (a *validationAttempt) recoverJournalReceipt(ctx context.Context, admission bool, kind string) bool {
	bounded, cancel := a.policy.readContext(ctx)
	defer cancel()
	var receipt journalReceipt
	// One snapshot projects only our complete identity. Global existence flags expose
	// contradictions for the attempt without returning another scope's identity/data.
	result := a.db.WithContext(bounded).Raw(`WITH expected AS (
 SELECT ?::bigint AS tenant_id, ?::text AS space_id, ?::text AS raw_kb_id,
 ?::text AS wiki_kb_id, ?::text AS attempt_id)
 SELECT p.tenant_id AS pending_tenant_id, p.space_id AS pending_space_id,
 p.raw_kb_id AS pending_raw_kb_id, p.wiki_kb_id AS pending_wiki_kb_id, p.attempt_id AS pending_attempt_id,
 f.tenant_id AS terminal_tenant_id, f.space_id AS terminal_space_id,
 f.raw_kb_id AS terminal_raw_kb_id, f.wiki_kb_id AS terminal_wiki_kb_id,
 f.attempt_id AS terminal_attempt_id, f.kind AS terminal_kind,
 EXISTS(SELECT 1 FROM enterprise_member_validation_pending WHERE attempt_id=e.attempt_id) AS pending_exists,
 EXISTS(SELECT 1 FROM enterprise_member_validation_failures WHERE attempt_id=e.attempt_id) AS terminal_exists
 FROM expected e LEFT JOIN enterprise_member_validation_pending p
 ON p.tenant_id=e.tenant_id AND p.space_id=e.space_id AND p.raw_kb_id=e.raw_kb_id
 AND p.wiki_kb_id=e.wiki_kb_id AND p.attempt_id=e.attempt_id
 LEFT JOIN enterprise_member_validation_failures f
 ON f.tenant_id=e.tenant_id AND f.space_id=e.space_id AND f.raw_kb_id=e.raw_kb_id
 AND f.wiki_kb_id=e.wiki_kb_id AND f.attempt_id=e.attempt_id`,
		a.scope.TenantID, a.scope.SpaceID, a.scope.RawKBID, a.scope.WikiKBID, a.id).Scan(&receipt)
	if result.Error != nil || result.RowsAffected != 1 {
		return false
	}
	if admission {
		return receipt.PendingExists && !receipt.TerminalExists && receipt.Pending.matches(a.scope, a.id)
	}
	// A successful DELETE has no durable receipt: absence cannot prove completion.
	return kind != "" && !receipt.PendingExists && receipt.TerminalExists &&
		receipt.Terminal.matches(a.scope, a.id) && receipt.TerminalKind != nil && *receipt.TerminalKind == kind
}
