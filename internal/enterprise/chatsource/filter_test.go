package chatsource_test

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type chunkRows struct {
	rows []*types.Chunk
	err  error
}

func (c chunkRows) ListChunksByID(context.Context, uint64, []string) ([]*types.Chunk, error) {
	return c.rows, c.err
}

func TestFilterChecksRealChunkAndFixedReleaseWithoutMutatingResults(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a)
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1"), kb("plain")})
	require.NoError(t, err)
	h.active["s1"] = "new-release"
	results := []*types.SearchResult{
		{ID: "good", KnowledgeID: "k1", KnowledgeBaseID: "raw-1", Metadata: map[string]string{"keep": "yes"}},
		{ID: "changed", KnowledgeID: "k2", KnowledgeBaseID: "raw-1"},
		{ID: "foreign", KnowledgeID: "k1", KnowledgeBaseID: "raw-1"},
		{ID: "spoof", KnowledgeID: "k2", KnowledgeBaseID: "raw-1"},
		{ID: "missing", KnowledgeID: "k1", KnowledgeBaseID: "raw-1"},
		{ID: "unselected", KnowledgeID: "k9", KnowledgeBaseID: "raw-2"},
		{ID: "ordinary", KnowledgeID: "plain", KnowledgeBaseID: "plain"},
	}
	chunks := chunkRows{rows: []*types.Chunk{
		{ID: "good", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2},
		{ID: "changed", TenantID: tenant, KnowledgeID: "k2", KnowledgeBaseID: "raw-1", ParseAttempt: 2},
		{ID: "foreign", TenantID: 99, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2},
		{ID: "spoof", TenantID: tenant, KnowledgeID: "other", KnowledgeBaseID: "raw-1", ParseAttempt: 1},
	}}
	got, err := r.Filter(context.Background(), tenant, turn, chunks, results)
	require.NoError(t, err)
	require.Len(t, got, 2)
	require.Equal(t, "good", got[0].ID)
	require.Equal(t, "rel-1", got[0].Metadata["release_id"])
	require.Equal(t, "ordinary", got[1].ID)
	require.Equal(t, map[string]string{"keep": "yes"}, results[0].Metadata)
	require.Equal(t, 1, h.reads["s1"])
	delete(p.byRelease, "s1/rel-1") // retired release: sources removed, no Active reread
	got, err = r.Filter(context.Background(), tenant, turn, chunks, results)
	require.NoError(t, err)
	require.Len(t, got, 1)
	require.Equal(t, "ordinary", got[0].ID)
}

func TestFilterRechecksCurrentAttemptsAndPropagatesDependencyFailure(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a)
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	results := []*types.SearchResult{{ID: "good", KnowledgeID: "k1", KnowledgeBaseID: "raw-1"}}
	chunks := chunkRows{rows: []*types.Chunk{{ID: "good", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2}}}
	a.current["k1"] = 3
	got, err := r.Filter(context.Background(), tenant, turn, chunks, results)
	require.NoError(t, err)
	require.Empty(t, got)
	boom := errors.New("offline dependency failure")
	got, err = r.Filter(context.Background(), tenant, turn, chunkRows{err: boom}, results)
	require.ErrorIs(t, err, boom)
	require.Empty(t, got)
	_, err = r.Filter(context.Background(), tenant, turn, nil, results)
	require.Error(t, err)
	p.err = boom
	r = resolver(s, h, p, a)
	got, err = r.Filter(context.Background(), tenant, turn, chunks, results)
	require.ErrorIs(t, err, boom)
	require.Empty(t, got)
}
