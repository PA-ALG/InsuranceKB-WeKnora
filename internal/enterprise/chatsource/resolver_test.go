package chatsource_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestResolverRejectsForeignEnterpriseButKeepsOrdinarySharing(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a)
	foreign := kb("raw-1")
	turn, err := r.Resolve(context.Background(), 99, types.SearchTargets{kb("plain"), foreign})
	require.Equal(t, "RELEASE_ACCESS_DENIED", code(t, err))
	require.Equal(t, chatsource.Turn{}, turn)
	turn, err = r.Resolve(context.Background(), 99, types.SearchTargets{kb("plain")})
	require.NoError(t, err)
	require.Equal(t, "plain", turn.Targets[0].KnowledgeBaseID)
}

func TestResolverRejectsEnterpriseKBWithMissingOrForgedOwner(t *testing.T) {
	for _, owner := range []uint64{0, 99} {
		t.Run(fmt.Sprint(owner), func(t *testing.T) {
			s, h, p, a := fixture()
			r := resolver(s, h, p, a)
			for _, id := range []string{"raw-1", "wiki-1"} {
				target := kb(id)
				target.TenantID = owner
				turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("plain"), target})
				require.Equal(t, "RELEASE_ACCESS_DENIED", code(t, err))
				require.Equal(t, chatsource.Turn{}, turn)
			}
			plain := kb("plain")
			plain.TenantID = owner
			turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{plain})
			require.NoError(t, err)
			require.Equal(t, types.SearchTargets{plain}, turn.Targets)
		})
	}
}

func TestResolverConflictPinsUnavailableAndMetadataCopy(t *testing.T) {
	s, h, p, a := fixture()
	p.byRelease["s1/rel-1"] = append(p.byRelease["s1/rel-1"], chatsource.Pin{KnowledgeID: "k1", ParseAttempt: 3})
	turn, err := resolver(s, h, p, a).Resolve(context.Background(), tenant,
		types.SearchTargets{kb("wiki-1"), kb("wiki-1"), kb("raw-1")})
	require.NoError(t, err)
	require.Equal(t, []string{"s1"}, turn.WikiSpaces)
	require.Equal(t, map[string]int64{"k2": 1}, turn.RawAttempts)
	require.Equal(t, []string{"k2"}, turn.Targets[0].KnowledgeIDs)
	meta := map[string]string{"keep": "yes"}
	result := &types.SearchResult{KnowledgeID: "k2", Metadata: meta}
	turn.Label([]*types.SearchResult{nil, result})
	require.Equal(t, map[string]string{"keep": "yes"}, meta)
	require.Equal(t, "raw_text", result.Metadata["source_tier"])
}

func TestFilterDropsUnselectedMaterialFromKnownEnterpriseKB(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a)
	selected := kb("raw-1")
	selected.Type, selected.KnowledgeIDs = types.SearchTargetTypeKnowledge, []string{"k2"}
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{selected})
	require.NoError(t, err)
	results := []*types.SearchResult{{ID: "unselected", KnowledgeID: "k1", KnowledgeBaseID: "raw-1"}}
	chunks := chunkRows{rows: []*types.Chunk{{ID: "unselected", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2}}}
	got, err := r.Filter(context.Background(), tenant, turn, chunks, results)
	require.NoError(t, err)
	require.Empty(t, got)
}

func TestResolverNilDependenciesFailClosed(t *testing.T) {
	s, h, p, a := fixture()
	for _, r := range []*chatsource.Resolver{
		nil, chatsource.NewResolver(nil, h, p, a), chatsource.NewResolver(s, nil, p, a),
		chatsource.NewResolver(s, h, nil, a), chatsource.NewResolver(s, h, p, nil),
	} {
		turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
		require.Error(t, err)
		require.Equal(t, chatsource.Turn{}, turn)
	}
}
