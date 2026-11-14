package releasestore

import (
	"context"
	"crypto/sha256"
	"fmt"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func TestPostgresActivationReceiptFollowsExactCommitAfterHeadMoves(t *testing.T) {
	db := openSchema(t)
	store := New(db, testSpaces(t))
	ctx := context.Background()
	a := activation(t, store, "first-receipt")
	a.DecisionDigest = fmt.Sprintf("%x", sha256.Sum256([]byte("decision")))
	r1, err := store.Activate(ctx, a)
	require.NoError(t, err)
	b := activation(t, store, "later-release")
	r2, err := store.Activate(ctx, b)
	require.NoError(t, err)
	require.NotEqual(t, r1.ID, r2.ID)

	type lookup interface {
		ActivationByNonce(context.Context, uint64, string, string, string) (release.Release, error)
	}
	receipts, ok := any(store).(lookup)
	require.True(t, ok, "store needs exact receipt lookup")
	found, err := receipts.ActivationByNonce(ctx, a.TenantID, a.SpaceID, a.Nonce, a.DecisionDigest)
	require.NoError(t, err)
	require.Equal(t, r1, found)
	_, err = receipts.ActivationByNonce(ctx, a.TenantID, "space-2", a.Nonce, a.DecisionDigest)
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorReleaseNotFound, failure.Code)
	_, err = receipts.ActivationByNonce(ctx, a.TenantID, a.SpaceID, a.Nonce, "wrong-authorization")
	require.Error(t, err)
	head, err := store.Head(ctx, a.TenantID, a.SpaceID)
	require.NoError(t, err)
	require.Equal(t, r2.ID, head.ReleaseID)
	require.Equal(t, int64(2), storageCount(t, db, "wiki_release_receipts"))
}
