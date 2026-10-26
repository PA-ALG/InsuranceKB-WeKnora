package releasestore

import (
	"context"
	"encoding/json"

	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// PublishedCandidate also finds historical and retired releases. Publishing the
// same candidate again must not move Head or reacquire its released source pins.
func (s *Store) PublishedCandidate(
	ctx context.Context, tenantID uint64, spaceID, bundleDigest string,
) (release.Release, bool, error) {
	if _, err := s.spaces.Scope(tenantID, spaceID); err != nil {
		return release.Release{}, false, err
	}
	id, err := candidateReleaseID(s.db.WithContext(ctx), tenantID, spaceID, bundleDigest)
	if err != nil || id == "" {
		return release.Release{}, false, err
	}
	r, err := s.ReleaseByID(ctx, tenantID, spaceID, id)
	return r, true, err
}

func candidateReleaseID(db *gorm.DB, tenantID uint64, spaceID, digest string) (string, error) {
	var row struct{ ReleaseID string }
	err := db.Table("wiki_releases").Select("release_id").
		Where("tenant_id = ? AND space_id = ? AND candidate_digest = ?", tenantID, spaceID, digest).
		Order("created_at, release_id").Limit(1).Scan(&row).Error
	return row.ReleaseID, err
}

// A Head row need not exist yet. Serialize a candidate independently of Head and
// source locks, and hold this transaction lock through publication. Query only
// AFTER the lock statement returns so READ COMMITTED sees a prior holder's commit.
func lockCandidate(tx *gorm.DB, w release.ActivationWrite) error {
	key, err := json.Marshal([]any{w.TenantID, w.SpaceID, w.BundleDigest})
	if err != nil {
		return err
	}
	return tx.Exec("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", string(key)).Error
}
