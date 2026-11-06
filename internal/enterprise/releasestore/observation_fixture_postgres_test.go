package releasestore

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// Replace a synthetic observed root through the real storage encoder. This permits
// producer-invalid content with valid storage hashes, without using unobserved bridge reads.
func replaceObservedSnapshots(t *testing.T, db *gorm.DB, s *Store, id string,
	members []types.WikiReleaseMemberSnapshot,
) {
	t.Helper()
	sc, err := s.spaces.Scope(7, "space-1")
	require.NoError(t, err)
	r, err := s.releases.GetRelease(context.Background(), sc, id)
	require.NoError(t, err)
	require.NoError(t, db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Exec("DELETE FROM enterprise_member_releases WHERE release_id=?", id).Error; err != nil {
			return err
		}
		if err := tx.Exec("DELETE FROM enterprise_member_preparations WHERE preparation_id=?", r.PreparationID).
			Error; err != nil {
			return err
		}
		if err := tx.Exec("DELETE FROM wiki_release_members WHERE release_id=?", id).Error; err != nil {
			return err
		}
		return s.storage.Put(context.Background(), tx, types.WikiReleaseMemberSetWrite{
			Scope: sc, ReleaseID: id, PreparationID: r.PreparationID, Members: members,
		})
	}))
}
