// SK-3 acceptance: quick answers put method fields first, marked as method knowledge and never
// labelled as reviewed product facts (Spec docs/design/slices/SK-3-销售方法阅读与问答.md §6.3).
// Protected file: written by Claude.
//
// A method hit keeps the pinned release identity (source_tier release, same handle and pin check)
// and adds knowledge_class method; its passage carries the profile's reading note instead of the
// reviewed label. Product hits are unchanged. Reuses the Q1b-2 fixture. RED until SK-3.
package chatsource_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

const readingNote = "销售方法（培训材料，非产品事实）：只用于怎么讲。"

type methodReader struct{ publishedReader }

func (r *methodReader) ReleaseByID(
	ctx context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	base, err := r.publishedReader.ReleaseByID(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return base, err
	}
	base.Members = append(base.Members,
		publishedMember("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v2",
			"question_intents": map[string]any{"method": [][]string{{"怎么讲"}}},
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
			}},
		}),
		publishedMember("presentation_profile", "presentation/sales_method", map[string]any{
			"profile_id": "sales_method", "entity_types": []string{"sales_method"}, "knowledge_class": "method",
			"reading_note": readingNote,
			"sections": []map[string]any{{"section_key": "method", "display_name": "销售方法", "fields": []map[string]any{
				{"field_key": "method_summary", "short_title": "方法摘要"},
			}}},
		}),
		publishedMember("entity", "entity/sm-1", map[string]any{
			"entity_id": "sm-1", "entity_type": "sales_method", "names": []string{"需求分析三步法"},
		}),
		publishedMember("claim", "sm-1/method_summary", map[string]any{
			"subject_ref": "sm-1", "predicate": "method_summary", "state": "present", "value": "先问需求再讲产品",
			"origin": "SOURCE_SUPPORTED", "review": map[string]any{"mode": "human"},
			"evidence": []map[string]any{{
				"quote": "先问需求", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 2},
				"source_ref": "source:v1:km1:1:abc",
			}},
		}),
	)
	return base, nil
}

func TestMethodHitsComeFirstMarkedAndWithoutTheReviewedLabel(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a).WithPublished(knowledge.NewService(&methodReader{}))
	ctx, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")})
	require.NoError(t, err)
	cm := &types.ChatManage{}
	cm.Query = "需求分析三步法怎么讲，安佑福的犹豫期呢"
	require.NoError(t, chatsource.FilterPipeline(ctx, r, noChunks{t}, cm))
	require.Len(t, cm.MergeResult, 2)

	method, product := cm.MergeResult[0], cm.MergeResult[1]
	require.Equal(t, "release:rel-1:sm-1/method_summary", method.ID)
	require.Equal(t, map[string]string{
		"source_tier": "release", "space_id": "s1", "release_id": "rel-1",
		"logical_slug": "sm-1/method_summary", "evidence_index": "0", "knowledge_class": "method",
	}, method.Metadata)
	require.Equal(t, "需求分析三步法 · 方法摘要", method.KnowledgeTitle)
	passage := chatsource.AnswerPassage(ctx, method, method.Content)
	require.Equal(t, method.Content, passage, "no tier line: the content opens with the profile's note")
	require.Contains(t, passage, readingNote)
	require.NotContains(t, passage, "已发布知识（审核过）")

	require.Equal(t, "release:rel-1:1828/cooling_off_period", product.ID)
	require.NotContains(t, product.Metadata, "knowledge_class")
	require.Equal(t, "已发布知识（审核过）\n"+product.Content, chatsource.AnswerPassage(ctx, product, product.Content))
}
