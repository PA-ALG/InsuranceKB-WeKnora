package releasestore

import (
	"context"
	"database/sql"
	"fmt"
	"sort"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"gorm.io/gorm"
)

var _ spotcheck.Store = (*Store)(nil)

// InsertSamples atomically inserts a batch, preserving the complete first row
// for each scoped logical identity and returning winners in the caller's order.
func (s *Store) InsertSamples(
	ctx context.Context, tenantID uint64, samples []spotcheck.Sample,
) ([]spotcheck.Sample, error) {
	out := make([]spotcheck.Sample, 0, len(samples))
	if len(samples) == 0 {
		return out, nil
	}
	for _, sample := range samples {
		if _, err := s.spaces.Scope(tenantID, sample.SpaceID); err != nil {
			return nil, err
		}
	}
	ordered := append([]spotcheck.Sample(nil), samples...)
	// Every batch acquires unique-index conflicts in the same order. Opposing
	// input orders must not deadlock when concurrent batches overlap.
	sort.SliceStable(ordered, func(i, j int) bool {
		a, b := ordered[i], ordered[j]
		if a.SpaceID != b.SpaceID {
			return a.SpaceID < b.SpaceID
		}
		if a.ReleaseID != b.ReleaseID {
			return a.ReleaseID < b.ReleaseID
		}
		return a.LogicalSlug < b.LogicalSlug
	})
	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		for _, sample := range ordered {
			// Only this logical identity is idempotent. An unrelated PK or other
			// database error must abort the entire batch rather than disappear.
			if err := tx.Exec(`INSERT INTO enterprise_samples
(id, tenant_id, space_id, release_id, logical_slug, member_digest, stratum, created_by, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (tenant_id, space_id, release_id, logical_slug) DO NOTHING`,
				sample.ID, tenantID, sample.SpaceID, sample.ReleaseID, sample.LogicalSlug,
				sample.MemberDigest, sample.Stratum, sample.CreatedBy, sample.CreatedAt).Error; err != nil {
				return err
			}
		}
		for _, sample := range samples {
			stored, err := readSpotSamples(tx, `s.tenant_id = ? AND s.space_id = ?
AND s.release_id = ? AND s.logical_slug = ?`,
				tenantID, sample.SpaceID, sample.ReleaseID, sample.LogicalSlug)
			if err != nil {
				return err
			}
			if len(stored) != 1 {
				return fmt.Errorf("stored spot-check sample disappeared within insert transaction")
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

// ListSamples reads one tenant and Space, including only the greatest appended
// verdict sequence for each sample. Filtering and stable ordering share one query.
func (s *Store) ListSamples(
	ctx context.Context, tenantID uint64, spaceID string, f spotcheck.Filter,
) ([]spotcheck.Sample, error) {
	where := `s.tenant_id = ? AND s.space_id = ?`
	args := []any{tenantID, spaceID}
	if f.ReleaseID != "" {
		where += ` AND s.release_id = ?`
		args = append(args, f.ReleaseID)
	}
	switch f.Status {
	case "pending":
		where += ` AND v.id IS NULL`
	case "decided":
		where += ` AND v.id IS NOT NULL`
	case "":
	default:
		return nil, &release.Error{Code: spotcheck.ErrorSampleInvalid, Detail: "unknown sample status"}
	}
	return readSpotSamples(s.db.WithContext(ctx), where, args...)
}

// SampleByID does not reveal whether a missing ID belongs to another scope.
func (s *Store) SampleByID(ctx context.Context, tenantID uint64, spaceID, id string) (spotcheck.Sample, bool, error) {
	samples, err := readSpotSamples(s.db.WithContext(ctx),
		`s.tenant_id = ? AND s.space_id = ? AND s.id = ?`, tenantID, spaceID, id)
	if err != nil || len(samples) == 0 {
		return spotcheck.Sample{}, false, err
	}
	return samples[0], true, nil
}

// AppendVerdict checks sample ownership in the insert itself; the global sample
// foreign key alone cannot enforce tenant and Space isolation.
func (s *Store) AppendVerdict(ctx context.Context, tenantID uint64, spaceID string, v spotcheck.Verdict) error {
	result := s.db.WithContext(ctx).Exec(`INSERT INTO enterprise_sample_verdicts
(id, tenant_id, space_id, sample_id, outcome, note, reviewer, decided_at)
SELECT ?, s.tenant_id, s.space_id, s.id, ?, ?, ?, ? FROM enterprise_samples s
WHERE s.tenant_id = ? AND s.space_id = ? AND s.id = ?`,
		v.ID, v.Outcome, v.Note, v.Reviewer, v.DecidedAt, tenantID, spaceID, v.SampleID)
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected == 0 {
		return &release.Error{Code: spotcheck.ErrorSampleNotFound, Detail: "no such sample in this Space"}
	}
	return nil
}

type spotSampleRecord struct {
	ID, SpaceID, ReleaseID, LogicalSlug, MemberDigest, Stratum, CreatedBy string
	CreatedAt                                                             time.Time
	VerdictID, VerdictOutcome, VerdictNote, VerdictReviewer               sql.NullString
	VerdictDecidedAt                                                      sql.NullTime
}

// The lateral query uses the tenant/Space guard for verdicts as well as samples,
// and seq, rather than timestamps or IDs, defines the latest verdict.
const spotSamplesSQL = `SELECT s.id, s.space_id, s.release_id, s.logical_slug,
s.member_digest, s.stratum, s.created_by, s.created_at,
v.id AS verdict_id, v.outcome AS verdict_outcome, v.note AS verdict_note,
v.reviewer AS verdict_reviewer, v.decided_at AS verdict_decided_at
FROM enterprise_samples s
LEFT JOIN LATERAL (
 SELECT id, outcome, note, reviewer, decided_at FROM enterprise_sample_verdicts
 WHERE tenant_id = s.tenant_id AND space_id = s.space_id AND sample_id = s.id
 ORDER BY seq DESC LIMIT 1
) v ON true WHERE `

func readSpotSamples(db *gorm.DB, where string, args ...any) ([]spotcheck.Sample, error) {
	var rows []spotSampleRecord
	err := db.Raw(spotSamplesSQL+where+` ORDER BY s.created_at ASC, s.id ASC`, args...).Scan(&rows).Error
	if err != nil {
		return nil, err
	}
	out := make([]spotcheck.Sample, 0, len(rows))
	for _, row := range rows {
		sample := spotcheck.Sample{
			ID: row.ID, SpaceID: row.SpaceID, ReleaseID: row.ReleaseID, LogicalSlug: row.LogicalSlug,
			MemberDigest: row.MemberDigest, Stratum: row.Stratum,
			CreatedBy: row.CreatedBy, CreatedAt: row.CreatedAt.UTC(),
		}
		if row.VerdictID.Valid {
			sample.Verdict = &spotcheck.Verdict{
				ID: row.VerdictID.String, SampleID: row.ID, Outcome: row.VerdictOutcome.String,
				Note: row.VerdictNote.String, Reviewer: row.VerdictReviewer.String,
				DecidedAt: row.VerdictDecidedAt.Time.UTC(),
			}
		}
		out = append(out, sample)
	}
	return out, nil
}
