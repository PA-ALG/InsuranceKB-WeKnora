package chatsource_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestLabelOnlyTouchesRawPassagesOfTheTurn(t *testing.T) {
	turn := chatsource.Turn{
		Releases: map[string]string{"s1": "rel-1"}, RawKnowledge: map[string]string{"k9": "s1"},
		RawEntities: map[string][]string{},
	}
	missing := &types.SearchResult{KnowledgeID: "k9", KnowledgeTitle: "条款.pdf"}
	published := &types.SearchResult{ID: "release:rel-1:P/x", KnowledgeTitle: "甲 · 宽限期",
		Metadata: map[string]string{"source_tier": "release"}}
	turn.Label([]*types.SearchResult{missing, published})
	require.Equal(t, "所属产品未识别 · 条款.pdf", missing.KnowledgeTitle, "a material missing from the map is unidentified")
	require.Equal(t, "", missing.Metadata["entity_names"])
	require.Equal(t, "甲 · 宽限期", published.KnowledgeTitle)
	require.NotContains(t, published.Metadata, "entity_names")
}
