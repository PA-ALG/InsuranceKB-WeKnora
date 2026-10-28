// QA2c acceptance (protected, written by Claude): in a quick answer that names products, a selected
// passage of a named product that stops mid-sentence is followed by the next passages of the same
// material and parse attempt until a sentence ends, at most three per turn, with no new search or
// model call (Spec docs/design/slices/QA2c-邻段补全与q22定位.md §2, q23 of #398). The chunk store is
// in memory; each case runs RetrievalScope, the real native FILTER_TOP_K plugin and the restore.
// RED until QA2c.
package chatsource_test

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// chunkStore is a tenant-scoped chunk repository; reads counts its calls.
type chunkStore struct {
	rows  map[string]*types.Chunk
	reads *int
	err   error
}

func newChunkStore() chunkStore { return chunkStore{rows: map[string]*types.Chunk{}, reads: new(int)} }

func (c chunkStore) ListChunksByID(_ context.Context, tenantID uint64, ids []string) ([]*types.Chunk, error) {
	*c.reads++
	if c.err != nil {
		return nil, c.err
	}
	out := []*types.Chunk{}
	for _, id := range ids {
		if row, ok := c.rows[id]; ok && row.TenantID == tenantID {
			out = append(out, row)
		}
	}
	return out, nil
}

// chain stores consecutive chunks "<knowledgeID>-<index>" of one material at its pinned attempt
// (k1@2, k2@1 in the fixture), linked through their previous and next chunk IDs.
func (c chunkStore) chain(knowledgeID string, attempt int64, start int, texts ...string) {
	id := func(i int) string { return fmt.Sprintf("%s-%d", knowledgeID, i) }
	for i, text := range texts {
		row := &types.Chunk{
			ID: id(start + i), TenantID: tenant, KnowledgeID: knowledgeID, KnowledgeBaseID: "raw-1",
			Content: text, ChunkIndex: start + i, ParseAttempt: attempt, IsEnabled: true,
			ChunkType: types.ChunkTypeText,
		}
		if i > 0 {
			row.PreChunkID = id(start + i - 1)
		}
		if i < len(texts)-1 {
			row.NextChunkID = id(start + i + 1)
		}
		c.rows[row.ID] = row
	}
}

// selected is the passage of a stored chunk as retrieval returns it.
func (c chunkStore) selected(id string, score float64) *types.SearchResult {
	row := c.rows[id]
	return textPassage(id, row.KnowledgeID, row.ChunkIndex, score, row.Content)
}

// neighbourTurn: A0 owns k2, B1 owns k1; the question names A0.
func neighbourTurn(t *testing.T, question string) (context.Context, *chatsource.Resolver, *types.ChatManage) {
	t.Helper()
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}, "B1": {"k1"}})
	ctx, r, cm, _, _ := attributionTurn(t, s1, release.Release{}, false, question)
	return ctx, r, cm
}

const named = "A0保险因重大过失未告知有什么后果"

func TestAMidSentencePassageIsFollowedUntilTheSentenceEnds(t *testing.T) {
	store := newChunkStore()
	store.chain("k2", 1, 132, "投保人因重大过失未履行前款规定的如实告知义务", "，对保险事故的发生有严重影响的，",
		"本公司不承担保险责任。", "第十条 本公司应当在三十日内作出核定。")
	store.chain("k1", 2, 7, "投保人因重大过失未履行如实告知义务")
	ctx, r, cm := neighbourTurn(t, named)
	cm.MergeResult = []*types.SearchResult{store.selected("k1-7", 0.9), store.selected("k2-132", 0.8)}
	got := topK(ctx, t, r.WithChunks(store), cm, 1)
	require.Equal(t, []string{"k2-132", "k2-133", "k2-134"}, got,
		"followed beyond the top-k cut until a sentence ends; B1's passage is never selected")
	parent := cm.MergeResult[0]
	for _, next := range cm.MergeResult[1:] {
		require.Equal(t, store.rows[next.ID].Content, next.Content)
		require.Equal(t, parent.Score, next.Score)
		require.Equal(t, parent.KnowledgeTitle, next.KnowledgeTitle)
		require.Equal(t, "raw-1", next.KnowledgeBaseID)
		require.Equal(t, "k2", next.KnowledgeID)
		require.Equal(t, types.MatchTypeNearByChunk, next.MatchType)
	}

	// The followed passages are delivered and labelled with the product like any raw passage.
	require.NoError(t, chatsource.FilterPipeline(ctx, r, store, cm))
	raw := []*types.SearchResult{}
	for _, row := range cm.MergeResult {
		if row.KnowledgeBaseID == "raw-1" {
			raw = append(raw, row)
		}
	}
	require.Equal(t, []string{"k2-132", "k2-133", "k2-134"}, order(raw))
	require.NotEmpty(t, raw[0].Metadata["entity_names"])
	for _, row := range raw[1:] {
		require.Equal(t, raw[0].Metadata["entity_names"], row.Metadata["entity_names"])
		require.Equal(t, raw[0].KnowledgeTitle, row.KnowledgeTitle)
	}
}

func TestAtMostThreePassagesAreFollowedPerTurnInScoreOrder(t *testing.T) {
	store := newChunkStore()
	store.chain("k2", 1, 10, "甲款第一句", "甲款第二句", "甲款第三句", "甲款第四句", "甲款完。")
	store.chain("k2", 1, 30, "乙款第一句", "乙款完。")
	ctx, r, cm := neighbourTurn(t, named)
	cm.MergeResult = []*types.SearchResult{store.selected("k2-30", 0.8), store.selected("k2-10", 0.9)}
	require.Equal(t, []string{"k2-10", "k2-11", "k2-12", "k2-13", "k2-30"}, topK(ctx, t, r.WithChunks(store), cm, 2))
}

func TestOnlyANamedProductsPassageIsFollowed(t *testing.T) {
	store := newChunkStore()
	store.chain("k2", 1, 5, "等待期为九十日。")
	store.chain("k1", 2, 7, "本附加条款未尽事宜", "适用主险条款。")
	// k1 belongs to no product here: it may fill the answer but is not followed.
	s1 := attributed("rel-1", map[string][]string{"A0": {"k2"}})
	ctx, r, cm, _, _ := attributionTurn(t, s1, release.Release{}, false, named)
	cm.MergeResult = []*types.SearchResult{store.selected("k2-5", 0.9), store.selected("k1-7", 0.8)}
	require.Equal(t, []string{"k2-5", "k1-7"}, topK(ctx, t, r.WithChunks(store), cm, 2))
}

func TestAMergedGroupIsJudgedByItsDeliveredPrimaryPassage(t *testing.T) {
	store := newChunkStore()
	store.chain("k2", 1, 20, "本公司按基本保险金额的", "百分之二十给付轻症疾病保险金。")
	ctx, r, cm := neighbourTurn(t, named)
	// The native merge joined both passages; delivery keeps only the primary's own text.
	group := store.selected("k2-20", 0.9)
	group.Content += store.rows["k2-21"].Content
	group.SubChunkID = []string{"k2-21"}
	cm.MergeResult = []*types.SearchResult{group}
	require.Equal(t, []string{"k2-20", "k2-21"}, topK(ctx, t, r.WithChunks(store), cm, 1))
}

func TestAChainStopsAtAPassageItMayNotDeliver(t *testing.T) {
	for name, change := range map[string]func(*types.Chunk){
		"reparsed":             func(row *types.Chunk) { row.ParseAttempt = 2 },
		"deleted":              func(row *types.Chunk) { row.DeletedAt = gorm.DeletedAt{Valid: true} },
		"disabled":             func(row *types.Chunk) { row.IsEnabled = false },
		"another material":     func(row *types.Chunk) { row.KnowledgeID = "k1" },
		"another knowledge KB": func(row *types.Chunk) { row.KnowledgeBaseID = "raw-2" },
		"another chunk type":   func(row *types.Chunk) { row.ChunkType = types.ChunkTypeSummary },
		"missing":              func(row *types.Chunk) { row.TenantID = tenant + 1 },
	} {
		t.Run(name, func(t *testing.T) {
			store := newChunkStore()
			store.chain("k2", 1, 40, "本公司按基本保险金额的", "百分之二十给付。")
			change(store.rows["k2-41"])
			ctx, r, cm := neighbourTurn(t, named)
			cm.MergeResult = []*types.SearchResult{store.selected("k2-40", 0.9)}
			require.Equal(t, []string{"k2-40"}, topK(ctx, t, r.WithChunks(store), cm, 1))
		})
	}
}

func TestAnAlreadySelectedPassageIsNotRepeated(t *testing.T) {
	store := newChunkStore()
	store.chain("k2", 1, 40, "本公司按基本保险金额的", "百分之二十给付", "轻症疾病保险金。")
	ctx, r, cm := neighbourTurn(t, named)
	cm.MergeResult = []*types.SearchResult{store.selected("k2-40", 0.9), store.selected("k2-41", 0.5)}
	// k2-41 is already in the answer; its own continuation counts once.
	require.Equal(t, []string{"k2-40", "k2-41", "k2-42"}, topK(ctx, t, r.WithChunks(store), cm, 2))
}

func TestNoPassageIsFollowedWithoutANamedProductAReaderOrASuccessfulRead(t *testing.T) {
	store := newChunkStore()
	store.chain("k2", 1, 40, "本公司按基本保险金额的", "百分之二十给付。")

	ctx, r, cm := neighbourTurn(t, "重大过失未告知有什么后果")
	cm.MergeResult = []*types.SearchResult{store.selected("k2-40", 0.9)}
	require.Equal(t, []string{"k2-40"}, topK(ctx, t, r.WithChunks(store), cm, 1), "no product named")
	require.Zero(t, *store.reads, "no read without a named product")

	ctx, r, cm = neighbourTurn(t, named)
	cm.MergeResult = []*types.SearchResult{store.selected("k2-40", 0.9)}
	require.Equal(t, []string{"k2-40"}, topK(ctx, t, r, cm, 1), "no chunk reader configured")

	failing := newChunkStore()
	failing.rows, failing.err = store.rows, errors.New("storage down")
	ctx, r, cm = neighbourTurn(t, named)
	cm.MergeResult = []*types.SearchResult{store.selected("k2-40", 0.9)}
	require.Equal(t, []string{"k2-40"}, topK(ctx, t, r.WithChunks(failing), cm, 1), "a failed read follows nothing")
}

func TestSentenceEndsAreRecognisedInBothWidths(t *testing.T) {
	for _, end := range []string{"。", "！", "？", "；", "」", "”", "）", ".", "!", "?", ";", "\"", ")"} {
		store := newChunkStore()
		store.chain("k2", 1, 40, "本公司给付保险金"+end+" \n", "下一条。")
		ctx, r, cm := neighbourTurn(t, named)
		cm.MergeResult = []*types.SearchResult{store.selected("k2-40", 0.9)}
		require.Equal(t, []string{"k2-40"}, topK(ctx, t, r.WithChunks(store), cm, 1), "ends with %q", end)
	}
}
