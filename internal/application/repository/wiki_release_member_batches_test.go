package repository

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// A release larger than one statement's bind parameters still activates (#563 batch 6,
// 2026-11-13): the live Space stopped at 7280 members, since PostgreSQL allows 65535
// parameters per statement and each member row binds nine. SQLite's limit is lower, so
// the same release size fails here unless members are written in batches.
func TestActivateWritesAReleaseLargerThanOneStatementInBatches(t *testing.T) {
	db, err := gorm.Open(sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.WikiReleaseHead{}, &types.WikiRelease{}, &types.WikiReleaseMember{},
		&types.WikiReleaseReceipt{},
	))
	repo := NewWikiReleaseRepository(db)
	scope := types.WikiReleaseScope{TenantID: 1, SpaceID: "space-b6", RawKBID: "raw-b6", WikiKBID: "wiki-b6"}
	at := time.Date(2026, 11, 13, 19, 0, 0, 0, time.UTC)
	const size = 8000 // 72000 parameters in one statement
	members := make([]types.WikiReleaseMemberSnapshot, 0, size)
	for i := range size {
		slug := fmt.Sprintf("claim/p%04d", i)
		members = append(members, types.WikiReleaseMemberSnapshot{
			Kind: "claim", LogicalSlug: slug, RevisionID: "rev-" + slug,
			MemberDigest: fmt.Sprintf("sha256:%064d", i), Title: slug, Content: "value",
			Payload: []byte(`{"state":"present"}`),
		})
	}
	release := &types.WikiRelease{
		ID: "release-b6", WikiReleaseScope: scope, CandidateDigest: "c", ManifestDigest: "m",
		PreparationID: "prep-b6", CreatedAt: at, ActivatedAt: at,
	}

	receipt, err := repo.Activate(context.Background(), WikiReleaseActivationWrite{
		Release: release, Members: members, Nonce: "nonce-b6", AuthorizationDigest: "a",
		ActivatedBy: "test", ActivatedAt: at, ActivationReceiptID: "receipt-b6",
	})

	require.NoError(t, err)
	require.Equal(t, uint64(1), receipt.ActivationEpoch)
	var stored int64
	require.NoError(t, db.Model(&types.WikiReleaseMember{}).Where("release_id = ?", "release-b6").Count(&stored).Error)
	require.Equal(t, int64(size), stored)
}
