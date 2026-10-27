package knowledge_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
)

func TestBlankSearchesAddNoScopeNote(t *testing.T) {
	for _, name := range []string{"knowledge_search_fields", "knowledge_search_pages"} {
		_, data := rendered(t, name, `{"query":"  "}`)
		require.Empty(t, data["results"], name)
		require.Empty(t, data["notes"], name)
	}
}

func TestEntityFiltersNormalizeTheIDAndPagesNameAnUnknownOne(t *testing.T) {
	got, total, err := knowledge.NewService(scopeReader{}).
		SearchFields(context.Background(), tenant, space, scoped, "宽限期", "b", 0)
	require.NoError(t, err)
	require.Equal(t, 1, total, "IDs match as EntityFields matches them")
	require.Equal(t, "B/grace", got[0].Slug)

	text, data := rendered(t, "knowledge_search_pages", `{"query":"年龄错误","entity_id":"Z9"}`)
	require.Empty(t, data["results"])
	require.Contains(t, text, "检索范围：Z9的延伸阅读页面", "an unknown page filter is named, not dropped")
}

func TestAFilteredSearchCountsAndNamesOnlyThatEntity(t *testing.T) {
	query := scopeTool(t, "knowledge_search_fields")
	result, err := query.Execute(toolContext(), json.RawMessage(`{"query":"续保","entity_id":"A"}`))
	require.NoError(t, err)
	notes := result.Data["notes"].([]string)
	require.Len(t, notes, 1)
	require.Contains(t, notes[0], "检索范围：甲保险（经典版）的已发布字段")
	require.Contains(t, notes[0], "命中 22 条，显示 20 条")
}
