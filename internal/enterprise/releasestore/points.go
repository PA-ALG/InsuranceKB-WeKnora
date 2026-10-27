package releasestore

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

type pointRow struct {
	ID          string `gorm:"primaryKey"`
	TenantID    uint64
	SpaceID     string
	CandidateID string
	Slug        string
	Outcome     string
	Reason      string
	Subject     string
	ReleaseID   *string
	CreatedAt   time.Time
}

func (pointRow) TableName() string { return "enterprise_point_decisions" }

// PointDecisions returns the immutable decisions within one tenant and Space.
func (s *Store) PointDecisions(ctx context.Context, tenant uint64, space, id string) ([]release.PointDecision, error) {
	if _, err := s.spaces.Scope(tenant, space); err != nil {
		return nil, err
	}
	var rows []pointRow
	err := s.db.WithContext(ctx).Where("tenant_id = ? AND space_id = ? AND candidate_id = ?", tenant, space, id).
		Order("slug").Find(&rows).Error
	if err != nil {
		return nil, err
	}
	out := make([]release.PointDecision, 0, len(rows))
	for _, r := range rows {
		d := release.PointDecision{
			ID: r.ID, TenantID: r.TenantID, SpaceID: r.SpaceID, CandidateID: r.CandidateID,
			Slug: r.Slug, Outcome: r.Outcome, Reason: r.Reason, Subject: r.Subject, CreatedAt: r.CreatedAt,
		}
		if r.ReleaseID != nil {
			d.ReleaseID = *r.ReleaseID
		}
		out = append(out, d)
	}
	return out, nil
}

// The mode lock precedes the existing digest/source/Head locks everywhere. A
// batch digest differs from its candidate, so that digest lock alone is not enough.
func lockReviewCandidate(tx *gorm.DB, tenant uint64, space, id string) error {
	raw, _ := json.Marshal([]any{"review", tenant, space, id})
	return tx.Exec("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", string(raw)).Error
}

func noStoredPoints(tx *gorm.DB, tenant uint64, space, id string) error {
	var count int64
	if err := tx.Model(&pointRow{}).Where("tenant_id = ? AND space_id = ? AND candidate_id = ?", tenant, space, id).
		Count(&count).Error; err != nil {
		return err
	}
	if count > 0 {
		return &release.Error{Code: release.ErrorCandidateDecided, Detail: "candidate has point decisions"}
	}
	return nil
}

func noWholeDecision(tx *gorm.DB, tenant uint64, space, id string) error {
	var c candidateRow
	if err := tx.Where("tenant_id = ? AND space_id = ? AND id = ?", tenant, space, id).Take(&c).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return &release.Error{Code: release.ErrorCandidateNotFound}
		}
		return err
	}
	var count int64
	if err := tx.Model(&decisionRow{}).Where("tenant_id = ? AND space_id = ? AND candidate_id = ?", tenant, space, id).
		Count(&count).Error; err != nil {
		return err
	}
	if count > 0 {
		return &release.Error{Code: release.ErrorCandidateDecided, Detail: "candidate has a whole decision"}
	}
	committed, err := candidateReleaseID(tx, tenant, space, c.BundleDigest)
	if err != nil {
		return err
	}
	if committed != "" {
		return &release.Error{Code: release.ErrorCandidateDecided, Detail: "candidate was published as a whole"}
	}
	return nil
}

func validatePointRows(ds []release.PointDecision, outcome string) error {
	if len(ds) == 0 || len(ds) > 500 {
		return &release.Error{Code: release.ErrorDecisionInvalid}
	}
	first := ds[0]
	seen := map[string]bool{}
	for _, d := range ds {
		if d.TenantID == 0 || d.SpaceID == "" || d.CandidateID == "" || d.TenantID != first.TenantID ||
			d.SpaceID != first.SpaceID || d.CandidateID != first.CandidateID || d.Subject != first.Subject ||
			d.Subject == "" || d.Outcome != outcome || strings.TrimSpace(d.Slug) == "" || seen[d.Slug] ||
			strings.TrimSpace(d.Reason) == "" || !utf8.ValidString(d.Reason) ||
			utf8.RuneCountInString(d.Reason) > 2000 ||
			d.ReleaseID != "" {
			return &release.Error{Code: release.ErrorDecisionInvalid, Detail: "inconsistent point decisions"}
		}
		seen[d.Slug] = true
	}
	return nil
}

func checkPointRows(tx *gorm.DB, ds []release.PointDecision) error {
	first := ds[0]
	if err := noWholeDecision(tx, first.TenantID, first.SpaceID, first.CandidateID); err != nil {
		return err
	}
	slugs := make([]string, 0, len(ds))
	for _, d := range ds {
		slugs = append(slugs, d.Slug)
	}
	var count int64
	if err := tx.Model(&pointRow{}).Where(
		"tenant_id = ? AND space_id = ? AND candidate_id = ? AND slug IN ?",
		first.TenantID, first.SpaceID, first.CandidateID, slugs).Count(&count).Error; err != nil {
		return err
	}
	if count > 0 {
		return &release.Error{Code: release.ErrorMemberDecided, Detail: "point already decided"}
	}
	return nil
}

func (s *Store) insertPoints(tx *gorm.DB, ds []release.PointDecision, releaseID string) error {
	rows := make([]pointRow, 0, len(ds))
	now := s.now()
	for _, d := range ds {
		row := pointRow{
			ID: "point_" + uuid.NewString(), TenantID: d.TenantID, SpaceID: d.SpaceID, CandidateID: d.CandidateID,
			Slug: d.Slug, Outcome: d.Outcome, Reason: d.Reason, Subject: d.Subject, CreatedAt: now,
		}
		if releaseID != "" {
			row.ReleaseID = &releaseID
		}
		rows = append(rows, row)
	}
	return tx.Create(&rows).Error
}

// RejectPoints commits a homogeneous batch or writes nothing on any conflict.
func (s *Store) RejectPoints(ctx context.Context, ds []release.PointDecision) error {
	if err := validatePointRows(ds, "reject"); err != nil {
		return err
	}
	first := ds[0]
	if _, err := s.spaces.Scope(first.TenantID, first.SpaceID); err != nil {
		return err
	}
	return s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := lockReviewCandidate(tx, first.TenantID, first.SpaceID, first.CandidateID); err != nil {
			return err
		}
		if err := checkPointRows(tx, ds); err != nil {
			return err
		}
		return s.insertPoints(tx, ds, "")
	})
}
