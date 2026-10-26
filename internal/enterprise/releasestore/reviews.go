package releasestore

import (
	"context"
	"encoding/json"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

var _ release.QueueStore = (*Store)(nil)

type reviewRow struct {
	Candidate    candidateRow `gorm:"embedded"`
	ReviewStatus string       `gorm:"column:review_status"`
	DecisionJSON []byte       `gorm:"column:decision_json"`
	ReleaseID    string       `gorm:"column:release_id"`
}

// Queue derives review state in a single statement; neither latest-decision nor release
// lookup performs a separate per-candidate round trip. Bundle reads remain Store.BundleOf.
func (s *Store) Queue(
	ctx context.Context, tenantID uint64, spaceID, status string, limit int,
) ([]release.QueueEntry, error) {
	if status != "pending" && status != "decided" {
		return nil, &release.Error{Code: release.ErrorDecisionInvalid, Detail: "unknown queue status"}
	}
	out := make([]release.QueueEntry, 0)
	if _, err := s.spaces.Scope(tenantID, spaceID); err != nil {
		return out, nil
	}
	query := `WITH queue AS (
SELECT c.*, to_jsonb(d) AS decision_json, COALESCE(r.release_id, '') AS release_id,
  CASE WHEN r.release_id IS NOT NULL THEN 'released'
       WHEN d.outcome = 'approve' THEN 'approved'
       WHEN d.outcome = 'reject' THEN 'rejected' ELSE 'pending' END AS review_status
FROM enterprise_candidates c
LEFT JOIN LATERAL (
  SELECT * FROM enterprise_decisions d
  WHERE d.tenant_id = c.tenant_id AND d.space_id = c.space_id AND d.candidate_id = c.id
  ORDER BY d.created_at DESC, d.id DESC LIMIT 1
) d ON true
LEFT JOIN LATERAL (
  SELECT release_id FROM wiki_releases r
  WHERE r.tenant_id = c.tenant_id AND r.space_id = c.space_id AND r.candidate_digest = c.bundle_digest
  ORDER BY r.created_at DESC, r.release_id DESC LIMIT 1
) r ON true
WHERE c.tenant_id = ? AND c.space_id = ?
)
SELECT * FROM queue WHERE review_status `
	args := []any{tenantID, spaceID}
	if status == "pending" {
		query += `= 'pending' ORDER BY created_at ASC, id ASC`
	} else {
		if limit <= 0 {
			return out, nil
		}
		query += `<> 'pending' ORDER BY created_at DESC, id DESC LIMIT ?`
		args = append(args, limit)
	}
	var rows []reviewRow
	if err := s.db.WithContext(ctx).Raw(query, args...).Scan(&rows).Error; err != nil {
		return nil, err
	}
	for _, row := range rows {
		c := row.Candidate
		entry := release.QueueEntry{
			Candidate: release.Candidate{
				ID: c.ID, TenantID: c.TenantID, SpaceID: c.SpaceID, ContractVersion: c.ContractVersion,
				BundleDigest: c.BundleDigest, BaseReleaseID: c.BaseReleaseID, Status: row.ReviewStatus,
			},
			CreatedAt: c.CreatedAt, CreatedBy: c.CreatedBy, ReleaseID: row.ReleaseID,
		}
		if len(row.DecisionJSON) > 0 {
			if err := json.Unmarshal(row.DecisionJSON, &entry.Decision); err != nil {
				return nil, err
			}
		}
		out = append(out, entry)
	}
	return out, nil
}
