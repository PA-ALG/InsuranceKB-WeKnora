package chatsource

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestTurnContextIsRequestLocalAndWikiOnlyQuickQAIsExplicit(t *testing.T) {
	base := context.Background()
	_, ok := TurnFromContext(base)
	require.False(t, ok)
	ctx := WithTurn(base, Turn{Releases: map[string]string{"space": "release"}})
	got, ok := TurnFromContext(ctx)
	require.True(t, ok)
	require.Equal(t, "release", got.Releases["space"])
	_, ok = TurnFromContext(base)
	require.False(t, ok)
	require.Contains(t, KnowledgeNotice(Turn{WikiSpaces: []string{"space"}}), "已发布知识优先")
	require.Empty(t, KnowledgeNotice(Turn{}))
}

func TestAgentTurnWithNoResolverKeepsOrdinaryScope(t *testing.T) {
	config := &types.AgentConfig{SearchTargets: types.SearchTargets{{KnowledgeBaseID: "plain"}}}
	_, got, _, err := AgentTurn(context.Background(), nil, config)
	require.NoError(t, err)
	require.Same(t, config, got)
}
