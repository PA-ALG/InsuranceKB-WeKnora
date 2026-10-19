package chatsource_test

import (
	"context"
	"testing"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestOrdinaryTurnCannotReuseEnterpriseHistoryAsCurrentSources(t *testing.T) {
	for _, stage := range []string{"delivery", "analysis", "foreign-delivery", "foreign-analysis"} {
		t.Run(stage, func(t *testing.T) {
			s, h, p, a := fixture()
			r := chatsource.NewResolver(historyDirectory{s}, h, p, a)
			turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("plain")})
			require.NoError(t, err)
			require.Empty(t, turn.RawKnowledge)
			ctx := chatsource.WithTurn(context.Background(), turn, tenant)
			cm := &types.ChatManage{}
			cm.Query = "fixed material"
			cm.SearchResult = []*types.SearchResult{{ID: "plain", KnowledgeID: "ordinary", KnowledgeBaseID: "plain", Content: "ordinary body"}}
			cm.History = []*types.History{{KnowledgeReferences: types.References{
				{ID: "old", KnowledgeID: "k1", KnowledgeBaseID: "raw-1", Content: "fixed material", KnowledgeFilename: "material.csv", Score: 1},
			}}}
			if stage == "foreign-delivery" || stage == "foreign-analysis" {
				cm.History[0].KnowledgeReferences[0].KnowledgeBaseID = "foreign-raw"
			}
			plugin := chatpipeline.NewPluginMerge(chatpipeline.NewEventManager(), nil, nil)
			require.Nil(t, plugin.OnEvent(ctx, types.CHUNK_MERGE, cm, func() *chatpipeline.PluginError { return nil }))
			require.Len(t, cm.MergeResult, 2, "native merge injected the old enterprise reference")
			if stage == "analysis" || stage == "foreign-analysis" {
				restore := chatsource.AnalysisScope(ctx, r, types.DATA_ANALYSIS, cm)
				require.Len(t, cm.MergeResult, 1)
				require.Equal(t, "plain", cm.MergeResult[0].ID)
				restore()
			} else {
				rows := chunkRows{rows: []*types.Chunk{{ID: "old", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2}}}
				require.NoError(t, chatsource.FilterPipeline(ctx, r, rows, cm))
				require.Len(t, cm.MergeResult, 1)
				require.Equal(t, "plain", cm.MergeResult[0].ID)
			}
			require.Empty(t, h.reads, "an unselected enterprise Space never gains a new Active pin")
		})
	}
}

type historyDirectory struct{ spaces }

func (s historyDirectory) SpaceOf(owner uint64, kbID string) (string, chatsource.Role, bool) {
	if owner == 8 && kbID == "foreign-raw" {
		return "foreign-space", chatsource.RoleRaw, true
	}
	return s.spaces.SpaceOf(owner, kbID)
}
func (s historyDirectory) SpaceOwner(kbID string) (uint64, string, chatsource.Role, bool) {
	if kbID == "foreign-raw" {
		return 8, "foreign-space", chatsource.RoleRaw, true
	}
	space, role, ok := s.spaces.SpaceOf(tenant, kbID)
	return tenant, space, role, ok
}

func TestResolverUsesConfiguredOwnerForForeignEnterpriseTarget(t *testing.T) {
	s, h, p, a := fixture()
	r := chatsource.NewResolver(historyDirectory{s}, h, p, a)
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{{TenantID: tenant,
		KnowledgeBaseID: "foreign-raw", Type: types.SearchTargetTypeKnowledgeBase}})
	require.Equal(t, "RELEASE_ACCESS_DENIED", code(t, err))
	require.Empty(t, turn.Targets)
	require.Empty(t, h.reads)
}
