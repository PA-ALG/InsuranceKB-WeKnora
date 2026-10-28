package chatsource_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// failingAfter answers the first n reads from the store and fails every later one.
type failingAfter struct {
	store chunkStore
	n     int
}

func (f failingAfter) ListChunksByID(ctx context.Context, tenantID uint64, ids []string) ([]*types.Chunk, error) {
	if *f.store.reads >= f.n {
		return nil, errors.New("storage down")
	}
	return f.store.ListChunksByID(ctx, tenantID, ids)
}

func TestAReadFailureInsideAChainKeepsTheSelectionAsItWas(t *testing.T) {
	store := newChunkStore()
	store.chain("k2", 1, 40, "本公司按基本保险金额的", "百分之二十给付", "轻症疾病保险金。")
	ctx, r, cm := neighbourTurn(t, named)
	cm.MergeResult = []*types.SearchResult{store.selected("k2-40", 0.9)}
	// The selected passages and the first next passage are read; the second next read fails.
	got := topK(ctx, t, r.WithChunks(failingAfter{store: store, n: 2}), cm, 1)
	require.Equal(t, []string{"k2-40"}, got, "nothing half-followed")
}

func TestAFollowedPassageStaysNextToItsOwnPassageAmongEqualScores(t *testing.T) {
	store := newChunkStore()
	store.chain("k2", 1, 40, "本公司按基本保险金额的", "百分之二十给付。")
	store.chain("k2", 1, 60, "等待期为九十日。")
	// k1 belongs to no product here and fills with the same score.
	store.chain("k1", 2, 3, "本附加条款未尽事宜适用主险条款。")
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}})
	ctx, r, cm, _, _ := attributionTurn(t, s1, release.Release{}, false, named)
	cm.MergeResult = []*types.SearchResult{
		store.selected("k2-60", 0.7), store.selected("k1-3", 0.7), store.selected("k2-40", 0.7),
	}
	require.Equal(t, []string{"k1-3", "k2-40", "k2-41", "k2-60"}, topK(ctx, t, r.WithChunks(store), cm, 3),
		"k2-41 follows k2-40 directly")
}
