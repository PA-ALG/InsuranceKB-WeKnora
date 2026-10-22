package releasestore

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

var _ expert.Store = (*Store)(nil)

type expertRevisionRow struct {
	ID               string    `gorm:"column:id"`
	TenantID         uint64    `gorm:"column:tenant_id"`
	SpaceID          string    `gorm:"column:space_id"`
	BaseReleaseID    string    `gorm:"column:base_release_id"`
	MemberSlug       string    `gorm:"column:member_slug"`
	BaseMemberDigest string    `gorm:"column:base_member_digest"`
	Actor            string    `gorm:"column:actor"`
	Role             string    `gorm:"column:role"`
	RecordedAt       time.Time `gorm:"column:recorded_at"`
	BeforeJSON       string    `gorm:"column:before_json"`
	AfterJSON        string    `gorm:"column:after_json"`
	Reason           string    `gorm:"column:reason"`
	RecordSHA256     string    `gorm:"column:record_sha256"`
}

// CreateRevision inserts one immutable record (migration 000009). Rows are never updated or
// deleted, so a published citation keeps resolving to exactly what the expert wrote.
func (s *Store) CreateRevision(ctx context.Context, r expert.Revision) error {
	if _, err := s.spaces.Scope(r.TenantID, r.SpaceID); err != nil {
		return err
	}
	before, err := json.Marshal(r.Before)
	if err != nil {
		return fmt.Errorf("encode revision before: %w", err)
	}
	after, err := json.Marshal(r.After)
	if err != nil {
		return fmt.Errorf("encode revision after: %w", err)
	}
	return s.db.WithContext(ctx).Exec(`INSERT INTO enterprise_expert_revisions
(id, tenant_id, space_id, base_release_id, member_slug, base_member_digest, actor, role,
 recorded_at, before_json, after_json, reason, record_sha256)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		r.ID, r.TenantID, r.SpaceID, r.BaseReleaseID, r.MemberSlug, r.BaseMemberDigest, r.Actor, r.Role,
		r.RecordedAt.UTC(), string(before), string(after), r.Reason, r.RecordSHA256).Error
}

// RevisionByID reads a record of one tenant and Space; a record of another scope is reported
// as missing, never as existing elsewhere.
func (s *Store) RevisionByID(ctx context.Context, tenantID uint64, spaceID, id string) (expert.Revision, error) {
	var rows []expertRevisionRow
	err := s.db.WithContext(ctx).Raw(`SELECT id, tenant_id, space_id, base_release_id, member_slug,
 base_member_digest, actor, role, recorded_at, before_json, after_json, reason, record_sha256
FROM enterprise_expert_revisions WHERE tenant_id = ? AND space_id = ? AND id = ?`,
		tenantID, spaceID, id).Scan(&rows).Error
	if err != nil {
		return expert.Revision{}, err
	}
	if len(rows) == 0 {
		return expert.Revision{}, &release.Error{
			Code: release.ErrorEvidenceNotFound, Detail: "the expert revision record does not exist",
		}
	}
	row := rows[0]
	out := expert.Revision{
		ID: row.ID, TenantID: row.TenantID, SpaceID: row.SpaceID, BaseReleaseID: row.BaseReleaseID,
		MemberSlug: row.MemberSlug, BaseMemberDigest: row.BaseMemberDigest, Actor: row.Actor,
		Role: row.Role, RecordedAt: row.RecordedAt.UTC(), Reason: row.Reason, RecordSHA256: row.RecordSHA256,
	}
	if err := json.Unmarshal([]byte(row.BeforeJSON), &out.Before); err != nil {
		return expert.Revision{}, fmt.Errorf("decode revision before: %w", err)
	}
	if err := json.Unmarshal([]byte(row.AfterJSON), &out.After); err != nil {
		return expert.Revision{}, fmt.Errorf("decode revision after: %w", err)
	}
	return out, nil
}
