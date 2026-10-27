package releasestore

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"sort"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"gorm.io/gorm"
)

var _ confirm.Store = (*Store)(nil)

// InsertItems atomically inserts a batch, preserving the first row for each scoped identity and
// returning the stored items in the caller's order.
func (s *Store) InsertItems(ctx context.Context, tenantID uint64, items []confirm.Item) ([]confirm.Item, error) {
	out := make([]confirm.Item, 0, len(items))
	if len(items) == 0 {
		return out, nil
	}
	for _, item := range items {
		if err := s.confirmationScope(tenantID, item.SpaceID); err != nil {
			return nil, err
		}
	}
	ordered := append([]confirm.Item(nil), items...)
	// Concurrent overlapping batches take unique-index conflicts in one order, so they cannot
	// deadlock whatever their input order.
	sort.SliceStable(ordered, func(i, j int) bool { return identity(ordered[i]) < identity(ordered[j]) })
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		for _, item := range ordered {
			options, err := json.Marshal(item.Options)
			if err != nil {
				return err
			}
			if err := tx.Exec(`INSERT INTO enterprise_confirmations
(id, tenant_id, space_id, subject, revision, content_digest, title, detail, options, created_by, created_at, source_ref)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (tenant_id, space_id, subject, revision, content_digest) DO NOTHING`,
				item.ID, tenantID, item.SpaceID, item.Subject, item.Revision, item.ContentDigest,
				item.Title, item.Detail, string(options), item.CreatedBy,
				item.CreatedAt, item.SourceRef).Error; err != nil {
				return err
			}
		}
		for _, item := range items {
			stored, err := readConfirmations(tx, `c.tenant_id = ? AND c.space_id = ?
AND c.subject = ? AND c.revision = ? AND c.content_digest = ?`,
				tenantID, item.SpaceID, item.Subject, item.Revision, item.ContentDigest)
			if err != nil {
				return err
			}
			if len(stored) != 1 {
				return fmt.Errorf("stored confirmation disappeared within insert transaction")
			}
			out = append(out, stored[0])
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return out, nil
}

// confirmationScope keeps every entry point inside the configured Spaces: once a Space leaves the
// configuration its items can no longer be read, answered or closed, and nothing is queried.
func (s *Store) confirmationScope(tenantID uint64, spaceID string) error {
	if _, err := s.spaces.Scope(tenantID, spaceID); err != nil {
		return &release.Error{Code: confirm.ErrorConfirmationNotFound, Detail: "the Space is not configured"}
	}
	return nil
}

func identity(item confirm.Item) string {
	return item.SpaceID + "\x00" + item.Subject + "\x00" + item.Revision + "\x00" + item.ContentDigest
}

// ListItems reads one tenant and Space with each item's latest answer and its closure.
func (s *Store) ListItems(
	ctx context.Context, tenantID uint64, spaceID string, f confirm.Filter,
) ([]confirm.Item, error) {
	if err := s.confirmationScope(tenantID, spaceID); err != nil {
		return nil, err
	}
	where := `c.tenant_id = ? AND c.space_id = ?`
	switch f.Status {
	case "open":
		where += ` AND k.confirmation_id IS NULL`
	case "closed":
		where += ` AND k.confirmation_id IS NOT NULL`
	case "":
	default:
		return nil, &release.Error{Code: confirm.ErrorConfirmationInvalid, Detail: "unknown status"}
	}
	return readConfirmations(s.db.WithContext(ctx), where, tenantID, spaceID)
}

// ItemByID does not reveal whether a missing ID belongs to another scope.
func (s *Store) ItemByID(ctx context.Context, tenantID uint64, spaceID, id string) (confirm.Item, bool, error) {
	if err := s.confirmationScope(tenantID, spaceID); err != nil {
		return confirm.Item{}, false, err
	}
	items, err := readConfirmations(s.db.WithContext(ctx),
		`c.tenant_id = ? AND c.space_id = ? AND c.id = ?`, tenantID, spaceID, id)
	if err != nil || len(items) == 0 {
		return confirm.Item{}, false, err
	}
	return items[0], true, nil
}

// AppendAnswer and CloseItem both lock the item row first, so an answer and a closure racing on
// one item are serialised: whichever comes second sees the other.
func (s *Store) AppendAnswer(ctx context.Context, tenantID uint64, spaceID string, a confirm.Answer) error {
	if err := s.confirmationScope(tenantID, spaceID); err != nil {
		return err
	}
	return s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := lockOpenItem(tx, tenantID, spaceID, a.ItemID); err != nil {
			return err
		}
		return tx.Exec(`INSERT INTO enterprise_confirmation_answers
(id, tenant_id, space_id, confirmation_id, option_key, note, answerer, answered_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
			a.ID, tenantID, spaceID, a.ItemID, a.OptionKey, a.Note, a.Answerer, a.AnsweredAt).Error
	})
}

// CloseItem closes once; an applied closure must name the latest answer, judged under the lock.
func (s *Store) CloseItem(ctx context.Context, tenantID uint64, spaceID, itemID string, c confirm.Closure) error {
	if err := s.confirmationScope(tenantID, spaceID); err != nil {
		return err
	}
	return s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := lockOpenItem(tx, tenantID, spaceID, itemID); err != nil {
			return err
		}
		var answerID sql.NullString
		if c.Reason == "applied" {
			var latest []string
			if err := tx.Raw(`SELECT id FROM enterprise_confirmation_answers
WHERE tenant_id = ? AND space_id = ? AND confirmation_id = ? ORDER BY seq DESC LIMIT 1`,
				tenantID, spaceID, itemID).Scan(&latest).Error; err != nil {
				return err
			}
			if len(latest) != 1 || latest[0] != c.AnswerID {
				return &release.Error{Code: confirm.ErrorAnswerStale, Detail: "the answer is not the latest one"}
			}
			answerID = sql.NullString{String: c.AnswerID, Valid: true}
		}
		return tx.Exec(`INSERT INTO enterprise_confirmation_closures
(confirmation_id, tenant_id, space_id, reason, answer_id, closed_by, closed_at)
VALUES (?, ?, ?, ?, ?, ?, ?)`,
			itemID, tenantID, spaceID, c.Reason, answerID, c.ClosedBy, c.ClosedAt).Error
	})
}

// lockOpenItem takes the item row lock within the scope and fails if it is missing or closed.
func lockOpenItem(tx *gorm.DB, tenantID uint64, spaceID, itemID string) error {
	var locked []string
	if err := tx.Raw(`SELECT id FROM enterprise_confirmations
WHERE tenant_id = ? AND space_id = ? AND id = ? FOR UPDATE`, tenantID, spaceID, itemID).
		Scan(&locked).Error; err != nil {
		return err
	}
	if len(locked) != 1 {
		return &release.Error{Code: confirm.ErrorConfirmationNotFound, Detail: "no such item in this Space"}
	}
	var closed int64
	if err := tx.Raw(`SELECT count(*) FROM enterprise_confirmation_closures
WHERE tenant_id = ? AND space_id = ? AND confirmation_id = ?`, tenantID, spaceID, itemID).
		Scan(&closed).Error; err != nil {
		return err
	}
	if closed != 0 {
		return &release.Error{Code: confirm.ErrorConfirmationClosed, Detail: "the item is closed"}
	}
	return nil
}

type confirmationRecord struct {
	ID, SpaceID, Subject, Revision, ContentDigest, Title, Detail, Options, CreatedBy string
	SourceRef                                                                        string
	CreatedAt                                                                        time.Time
	AnswerID, AnswerOptionKey, AnswerNote, AnswerAnswerer                            sql.NullString
	AnswerAnsweredAt                                                                 sql.NullTime
	ClosureReason, ClosureAnswerID, ClosureClosedBy                                  sql.NullString
	ClosureClosedAt                                                                  sql.NullTime
}

// The lateral query guards answers by tenant and Space as well, and seq, not timestamps or IDs,
// defines the latest answer.
const confirmationsSQL = `SELECT c.id, c.space_id, c.subject, c.revision, c.content_digest,
c.title, c.detail, c.options::text AS options, c.created_by, c.created_at, c.source_ref,
a.id AS answer_id, a.option_key AS answer_option_key, a.note AS answer_note,
a.answerer AS answer_answerer, a.answered_at AS answer_answered_at,
k.reason AS closure_reason, k.answer_id AS closure_answer_id, k.closed_by AS closure_closed_by,
k.closed_at AS closure_closed_at
FROM enterprise_confirmations c
LEFT JOIN LATERAL (
 SELECT id, option_key, note, answerer, answered_at FROM enterprise_confirmation_answers
 WHERE tenant_id = c.tenant_id AND space_id = c.space_id AND confirmation_id = c.id
 ORDER BY seq DESC LIMIT 1
) a ON true
LEFT JOIN enterprise_confirmation_closures k
 ON k.confirmation_id = c.id AND k.tenant_id = c.tenant_id AND k.space_id = c.space_id
WHERE `

func readConfirmations(db *gorm.DB, where string, args ...any) ([]confirm.Item, error) {
	var rows []confirmationRecord
	err := db.Raw(confirmationsSQL+where+` ORDER BY c.created_at ASC, c.id ASC`, args...).Scan(&rows).Error
	if err != nil {
		return nil, err
	}
	out := make([]confirm.Item, 0, len(rows))
	for _, row := range rows {
		item := confirm.Item{
			ID: row.ID, SpaceID: row.SpaceID, Subject: row.Subject, Revision: row.Revision,
			ContentDigest: row.ContentDigest, Title: row.Title, Detail: row.Detail,
			CreatedBy: row.CreatedBy, CreatedAt: row.CreatedAt.UTC(), SourceRef: row.SourceRef,
		}
		if err := json.Unmarshal([]byte(row.Options), &item.Options); err != nil {
			return nil, fmt.Errorf("stored confirmation options are not valid JSON: %w", err)
		}
		if row.AnswerID.Valid {
			item.Answer = &confirm.Answer{
				ID: row.AnswerID.String, ItemID: row.ID, OptionKey: row.AnswerOptionKey.String,
				Note: row.AnswerNote.String, Answerer: row.AnswerAnswerer.String,
				AnsweredAt: row.AnswerAnsweredAt.Time.UTC(),
			}
		}
		if row.ClosureReason.Valid {
			item.Closure = &confirm.Closure{
				Reason: row.ClosureReason.String, AnswerID: row.ClosureAnswerID.String,
				ClosedBy: row.ClosureClosedBy.String, ClosedAt: row.ClosureClosedAt.Time.UTC(),
			}
		}
		out = append(out, item)
	}
	return out, nil
}
