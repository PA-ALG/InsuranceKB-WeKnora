// QA1 acceptance added after review #371 (protected, written by Claude; Spec
// docs/design/slices/QA1-问答来源标注与范围说明.md §2.1, §3.2): a page counts as a source for all
// its entity_refs (R2), equal display names appear once (R5), and the page scope note names
// exactly what the exact-ID page filter used (R3). RED until the review fixes land.
package knowledge_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// refsReader has no navigation, so entities keep member order: B, A, then two entities that
// share one display name.
type refsReader struct{}

func (refsReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	if tenantID != tenant || spaceID != space || releaseID != "rel-r" {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return release.Release{ID: "rel-r", Epoch: 2, Members: []release.Member{
		entity("B", []string{"gb"}, "乙保险（悦享版）"),
		entity("A", []string{"ga"}, "甲保险（经典版）"),
		entity("C1", []string{"gc"}, "同名产品"),
		entity("C2", []string{"gc"}, "同名产品"),
		member("wiki_page", "wiki/A/overview", map[string]any{
			"page_key": "overview", "entity_refs": []string{"A", "Z", "B", "A"}, "title": "概览",
			"page_type": "entity", "summary": "概览", "content": "概览", "origin": "MODEL_GENERATED",
			"evidence": []map[string]any{cites("k7", "条款原文")},
		}),
		claim("C1", "grace", "present", "30日", cites("k8", "30日")),
		claim("C2", "grace", "present", "30日", cites("k8", "30日")),
	}}, nil
}

func TestSourceEntitiesCountEveryEntityAPageRefersTo(t *testing.T) {
	got, err := knowledge.NewService(refsReader{}).SourceEntities(context.Background(), tenant, space, "rel-r")
	require.NoError(t, err)
	require.Equal(t, []string{"乙保险（悦享版）", "甲保险（经典版）"}, got["k7"],
		"all entity_refs in order, the unknown Z skipped, A once")
	require.Equal(t, []string{"同名产品"}, got["k8"], "equal display names appear once")
}

func TestPageScopeNoteNamesWhatTheExactPageFilterUsed(t *testing.T) {
	text, data := rendered(t, "knowledge_search_pages", `{"query":"年龄错误","entity_id":"b"}`)
	require.Empty(t, data["results"], "pages filter by the exact ID")
	require.Contains(t, text, "检索范围：b的延伸阅读页面")
	require.NotContains(t, text, "乙保险（悦享版）的延伸阅读页面")

	text, _ = rendered(t, "knowledge_search_fields", `{"query":"宽限期","entity_id":"b"}`)
	require.Contains(t, text, "检索范围：乙保险（悦享版）的已发布字段", "fields match IDs as EntityFields does")
}
