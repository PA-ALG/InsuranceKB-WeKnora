package releasestore

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// Store implements release.Store and release.Publisher on PostgreSQL. Candidates and
// decisions live in the 000006 tables; releases go through the 000002 Head authority.
type Store struct {
	db       *gorm.DB
	releases *repository.WikiReleaseRepository
	spaces   Spaces
	now      func() time.Time
	members  memberCache
}

// New wires the adapter to the platform database and the configured Spaces.
func New(db *gorm.DB, spaces Spaces) *Store {
	return &Store{
		db: db, releases: repository.NewWikiReleaseRepository(db), spaces: spaces,
		now: func() time.Time { return time.Now().UTC() },
	}
}

type candidateRow struct {
	ID              string    `gorm:"column:id;primaryKey"`
	TenantID        uint64    `gorm:"column:tenant_id"`
	SpaceID         string    `gorm:"column:space_id"`
	BundleDigest    string    `gorm:"column:bundle_digest"`
	ContractVersion string    `gorm:"column:contract_version"`
	BaseReleaseID   string    `gorm:"column:base_release_id"`
	RawBundle       []byte    `gorm:"column:raw_bundle"`
	CreatedBy       string    `gorm:"column:created_by"`
	CreatedAt       time.Time `gorm:"column:created_at"`
}

func (candidateRow) TableName() string { return "enterprise_candidates" }

type decisionRow struct {
	ID           string    `gorm:"column:id;primaryKey"`
	TenantID     uint64    `gorm:"column:tenant_id"`
	SpaceID      string    `gorm:"column:space_id"`
	CandidateID  string    `gorm:"column:candidate_id"`
	BundleDigest string    `gorm:"column:bundle_digest"`
	Digest       string    `gorm:"column:digest"`
	Outcome      string    `gorm:"column:outcome"`
	Mode         string    `gorm:"column:mode"`
	PolicyRef    string    `gorm:"column:policy_ref"`
	Score        string    `gorm:"column:score"`
	Reason       string    `gorm:"column:reason"`
	Subject      string    `gorm:"column:subject"`
	CreatedAt    time.Time `gorm:"column:created_at"`
}

func (decisionRow) TableName() string { return "enterprise_decisions" }

// CreateCandidate stores the exact submitted bytes once per (tenant, Space, digest);
// a concurrent duplicate inserts nothing and reads the winner back.
func (s *Store) CreateCandidate(ctx context.Context, c release.Candidate, b release.Bundle) (release.Candidate, error) {
	if _, err := s.spaces.Scope(c.TenantID, c.SpaceID); err != nil {
		return release.Candidate{}, err
	}
	subject := ""
	if scope, ok := release.ScopeFromContext(ctx); ok {
		subject = scope.Principal.Subject
	}
	row := candidateRow{
		ID:       "cand_" + shortDigest(fmt.Sprintf("%d:%s:%s", c.TenantID, c.SpaceID, c.BundleDigest)),
		TenantID: c.TenantID, SpaceID: c.SpaceID, BundleDigest: c.BundleDigest,
		ContractVersion: c.ContractVersion, BaseReleaseID: c.BaseReleaseID,
		RawBundle: append([]byte(nil), b.RawJSON...), CreatedBy: subject, CreatedAt: s.now(),
	}
	result := s.db.WithContext(ctx).Clauses(clause.OnConflict{DoNothing: true}).Create(&row)
	if result.Error != nil {
		return release.Candidate{}, result.Error
	}
	stored, err := s.CandidateByID(ctx, c.TenantID, c.SpaceID, row.ID)
	if err != nil {
		return release.Candidate{}, err
	}
	stored.Status = "existing"
	if result.RowsAffected == 1 {
		stored.Status = "created"
	}
	return stored, nil
}

// CandidateByID reads a candidate within its tenant and Space only.
func (s *Store) CandidateByID(ctx context.Context, tenantID uint64, spaceID, id string) (release.Candidate, error) {
	row, err := s.candidate(ctx, tenantID, spaceID, id)
	if err != nil {
		return release.Candidate{}, err
	}
	return release.Candidate{
		ID: row.ID, SpaceID: row.SpaceID, TenantID: row.TenantID, ContractVersion: row.ContractVersion,
		BundleDigest: row.BundleDigest, BaseReleaseID: row.BaseReleaseID,
	}, nil
}

// BundleOf decodes the stored bytes; RawJSON is exactly what was submitted.
func (s *Store) BundleOf(ctx context.Context, tenantID uint64, spaceID, candidateID string) (release.Bundle, error) {
	row, err := s.candidate(ctx, tenantID, spaceID, candidateID)
	if err != nil {
		return release.Bundle{}, err
	}
	var b release.Bundle
	if err := json.Unmarshal(row.RawBundle, &b); err != nil {
		return release.Bundle{}, fmt.Errorf("stored bundle %s is unreadable: %w", row.ID, err)
	}
	b.RawJSON = row.RawBundle
	return b, nil
}

func (s *Store) candidate(ctx context.Context, tenantID uint64, spaceID, id string) (candidateRow, error) {
	var row candidateRow
	err := s.db.WithContext(ctx).Where("tenant_id = ? AND space_id = ? AND id = ?", tenantID, spaceID, id).
		Take(&row).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return candidateRow{}, &release.Error{
			Code: release.ErrorCandidateNotFound, Detail: "no such candidate in this Space",
		}
	}
	return row, err
}

// SaveDecision stores a decision once per (tenant, Space, digest).
func (s *Store) SaveDecision(ctx context.Context, d release.Decision) (release.Decision, error) {
	if _, err := s.spaces.Scope(d.TenantID, d.SpaceID); err != nil {
		return release.Decision{}, err
	}
	row := decisionRow{
		ID:       "dec_" + shortDigest(fmt.Sprintf("%d:%s:%s", d.TenantID, d.SpaceID, d.Digest)),
		TenantID: d.TenantID, SpaceID: d.SpaceID, CandidateID: d.CandidateID, BundleDigest: d.BundleDigest,
		Digest: d.Digest, Outcome: d.Outcome, Mode: d.Mode, PolicyRef: d.PolicyRef, Score: d.Score,
		Reason: d.Reason, Subject: d.Subject, CreatedAt: s.now(),
	}
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := lockReviewCandidate(tx, d.TenantID, d.SpaceID, d.CandidateID); err != nil {
			return err
		}
		if err := noStoredPoints(tx, d.TenantID, d.SpaceID, d.CandidateID); err != nil {
			return err
		}
		return tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&row).Error
	})
	if err != nil {
		return release.Decision{}, err
	}
	return s.DecisionByID(ctx, d.TenantID, d.SpaceID, row.ID)
}

// DecisionByID reads a decision within its tenant and Space only.
func (s *Store) DecisionByID(ctx context.Context, tenantID uint64, spaceID, id string) (release.Decision, error) {
	var row decisionRow
	err := s.db.WithContext(ctx).Where("tenant_id = ? AND space_id = ? AND id = ?", tenantID, spaceID, id).
		Take(&row).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return release.Decision{}, &release.Error{
			Code: release.ErrorDecisionNotFound, Detail: "no such decision in this Space",
		}
	}
	if err != nil {
		return release.Decision{}, err
	}
	return release.Decision{
		ID: row.ID, TenantID: row.TenantID, SpaceID: row.SpaceID, CandidateID: row.CandidateID,
		BundleDigest: row.BundleDigest, Outcome: row.Outcome, Mode: row.Mode, PolicyRef: row.PolicyRef,
		Score: row.Score, Reason: row.Reason, Subject: row.Subject, Digest: row.Digest, CreatedAt: row.CreatedAt,
	}, nil
}

func shortDigest(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])[:32]
}
