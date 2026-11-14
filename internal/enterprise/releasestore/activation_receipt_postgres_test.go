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

	// A fresh reader must still run the existing member integrity checks on the fixed Release.
	changed := db.Exec("UPDATE wiki_release_members SET member_digest = ? WHERE release_id = ?", "bad-digest", r1.ID)
	require.NoError(t, changed.Error)
	require.EqualValues(t, 1, changed.RowsAffected)
	cold := any(New(db, testSpaces(t))).(lookup)
	_, err = cold.ActivationByNonce(ctx, a.TenantID, a.SpaceID, a.Nonce, a.DecisionDigest)
	require.ErrorContains(t, err, "digest")
	require.Equal(t, int64(2), storageCount(t, db, "wiki_release_receipts"))
}

func TestPostgresActivationReceiptRejectsMismatchedManifest(t *testing.T) {
	for _, field := range []string{"decision_id", "bundle_digest"} {
		t.Run(field, func(t *testing.T) {
			db := openSchema(t)
			ctx := context.Background()
			s := service(New(db, testSpaces(t)))
			c, err := s.Receive(ctx, principal, "space-1", rawBundle(t, "", "receipt/test", `{"value":1}`))
			require.NoError(t, err)
			d, err := s.Decide(ctx, principal, "space-1", c.ID, approve)
			require.NoError(t, err)
			r, err := s.ActivateReceipt(ctx, principal, "space-1", c.ID, d.ID)
			require.NoError(t, err)
			cold := service(New(db, testSpaces(t)))
			read, err := cold.ActivationReceipt(ctx, principal, "space-1", c.ID, d.ID)
			require.NoError(t, err)
			require.Equal(t, r, read)

			changed := db.Exec(`UPDATE wiki_release_preparations
SET manifest = jsonb_set(manifest, ARRAY[?]::text[], '"unrelated"')
WHERE preparation_id = (SELECT preparation_id FROM wiki_releases WHERE release_id = ?)`, field, r.ID)
			require.NoError(t, changed.Error)
			require.EqualValues(t, 1, changed.RowsAffected)
			_, err = cold.ActivationReceipt(ctx, principal, "space-1", c.ID, d.ID)
			require.Error(t, err)
			require.Equal(t, int64(1), storageCount(t, db, "wiki_release_receipts"))
		})
	}
}
