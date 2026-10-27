// QA1 acceptance (protected, written by Claude): every raw passage names the products whose
// published members cite its material, and the Agent notice allows "没有" only on an explicit
// field (Spec docs/design/slices/QA1-问答来源标注与范围说明.md §2.2–§2.3, §4.2). Synthetic data in
// the shape of #286 r2 J056/J057: two products whose terms files share one file name. RED until QA1.
package chatsource_test

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

const (
	classic = "甲保险（经典版）"
	plus    = "乙保险（悦享版）"
)

// labelReader serves s1/rel-1: k1 is cited by the classic product's claim; k2 by the plus
// product's claim and by a page of the classic product; k4 by nothing.
type labelReader struct{ err error }

func (r labelReader) ReleaseByID(_ context.Context, tenantID uint64, spaceID, releaseID string) (release.Release, error) {
	if r.err != nil {
		return release.Release{}, r.err
	}
	if tenantID != tenant || spaceID != "s1" || releaseID != "rel-1" {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	source := func(id string) map[string]any {
		return map[string]any{
			"quote": "条款原文", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1},
			"source_ref": "source:v1:" + id + ":1:" + strings.Repeat("cd", 32),
		}
	}
	claim := func(subject, predicate string, evidence map[string]any) release.Member {
		return publishedMember("claim", subject+"/"+predicate, map[string]any{
			"subject_ref": subject, "predicate": predicate, "state": "present", "value": "30日",
			"origin": "SOURCE_SUPPORTED", "review": map[string]any{"mode": "machine"},
			"evidence": []map[string]any{evidence},
		})
	}
	entity := func(id, label, name string) release.Member {
		return publishedMember("entity", "entity/"+id, map[string]any{
			"entity_id": id, "entity_type": "product", "names": []string{name}, "classification_labels": []string{label},
		})
	}
	return release.Release{ID: "rel-1", Epoch: 1, Members: []release.Member{
		publishedMember("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v1",
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
				"groups": []map[string]any{
					{"group_key": "a", "display_name": "a", "classification_labels": []string{"a"}},
					{"group_key": "b", "display_name": "b", "classification_labels": []string{"b"}},
				},
			}},
		}),
		entity("P2", "b", plus),
		entity("P1", "a", classic),
		claim("P1", "rescission", source("k1")),
		claim("P2", "rescission", source("k2")),
		publishedMember("wiki_page", "wiki/P1/overview", map[string]any{
			"page_key": "overview", "entity_refs": []string{"P1"}, "title": "概览", "page_type": "entity",
			"summary": "概览", "content": "概览", "origin": "MODEL_GENERATED",
			"evidence": []map[string]any{source("k2")},
		}),
	}}, nil
}

// labelFixture adds k4 (pinned, searchable, cited by nothing) to the shared fixture.
func labelFixture(err error) (*chatsource.Resolver, spaces, *heads, pins, attempts) {
	s, h, p, a := fixture()
	p.byRelease["s1/rel-1"] = append(p.byRelease["s1/rel-1"], chatsource.Pin{KnowledgeID: "k4", ParseAttempt: 1})
	a.current["k4"] = 1
	return chatsource.NewResolver(s, h, p, a).WithPublished(knowledge.NewService(labelReader{err: err})), s, h, p, a
}

func rawResult(id, knowledgeID, title string) *types.SearchResult {
	return &types.SearchResult{ID: id, KnowledgeID: knowledgeID, KnowledgeBaseID: "raw-1", KnowledgeTitle: title,
		Metadata: map[string]string{"keep": "yes"}}
}

func keys(m map[string][]string) []string {
	out := []string{}
	for key := range m {
		out = append(out, key)
	}
	sort.Strings(out)
	return out
}

func TestRawMaterialsCarryTheProductsThatCiteThem(t *testing.T) {
	r, _, _, _, _ := labelFixture(nil)
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	require.Equal(t, []string{"k1", "k2", "k4"}, keys(turn.RawEntities), "one entry per searchable raw material")
	require.Equal(t, []string{classic}, turn.RawEntities["k1"])
	require.Equal(t, []string{classic, plus}, turn.RawEntities["k2"], "navigation order")
	require.Empty(t, turn.RawEntities["k4"])

	first, second := rawResult("c1", "k1", "保险条款.pdf"), rawResult("c2", "k2", "保险条款.pdf")
	uncited := rawResult("c4", "k4", "附加条款.pdf")
	shared := map[string]string{"keep": "yes"}
	first.Metadata = shared
	turn.Label([]*types.SearchResult{first, second, uncited})
	turn.Label([]*types.SearchResult{first, uncited}) // the same pointers in a second result list
	require.Equal(t, classic+" · 保险条款.pdf", first.KnowledgeTitle, "labelled once")
	require.Equal(t, classic+"、"+plus+" · 保险条款.pdf", second.KnowledgeTitle)
	require.Equal(t, "所属产品未识别 · 附加条款.pdf", uncited.KnowledgeTitle)
	require.Equal(t, map[string]string{
		"keep": "yes", "source_tier": "raw_text", "release_id": "rel-1", "entity_names": classic,
	}, first.Metadata)
	require.Equal(t, "", uncited.Metadata["entity_names"])
	require.Equal(t, map[string]string{"keep": "yes"}, shared, "shared metadata is copied, not mutated")
}

func TestQuickAnswerAutoRawMaterialsAreLabelledToo(t *testing.T) {
	r, s, h, p, a := labelFixture(nil)
	d := answerDirectory{s, map[string][2]string{"s1": {"raw-1", "wiki-1"}}}
	r = chatsource.NewResolver(d, h, p, a).WithPublished(knowledge.NewService(labelReader{}))
	ctx, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")}, allowRaw)
	require.NoError(t, err)
	turn, _ := chatsource.TurnFromContext(ctx)
	require.Equal(t, []string{"k1", "k2", "k4"}, keys(turn.RawEntities))
	require.Equal(t, []string{classic, plus}, turn.RawEntities["k2"])
}

func TestLabelsNeedThePublishedServiceAndSurviveALookupFailure(t *testing.T) {
	s, h, p, a := fixture()
	turn, err := chatsource.NewResolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	require.Nil(t, turn.RawEntities, "without published knowledge nothing is labelled")
	plain := rawResult("c1", "k1", "保险条款.pdf")
	turn.Label([]*types.SearchResult{plain})
	require.Equal(t, "保险条款.pdf", plain.KnowledgeTitle)
	require.NotContains(t, plain.Metadata, "entity_names")

	r, _, _, _, _ := labelFixture(errors.New("release store unavailable"))
	turn, err = r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err, "a label lookup failure does not fail the turn")
	require.Equal(t, []string{"k1", "k2", "k4"}, keys(turn.RawEntities))
	failed := rawResult("c1", "k1", "保险条款.pdf")
	turn.Label([]*types.SearchResult{failed})
	require.Equal(t, "所属产品未识别 · 保险条款.pdf", failed.KnowledgeTitle)
}

func TestWrappedSearchRowsNameTheirProduct(t *testing.T) {
	r, _, _, _, _ := labelFixture(nil)
	turn, err := r.Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	row := func(chunk, knowledgeID string) map[string]interface{} {
		return map[string]interface{}{
			"chunk_id": chunk, "knowledge_id": knowledgeID, "knowledge_base_id": "raw-1",
			"knowledge_title": "保险条款.pdf", "content": "两年后不得解除合同", "metadata": map[string]interface{}{},
		}
	}
	inner := nativeTool{&types.ToolResult{Success: true, Output: "native", Data: map[string]interface{}{
		"results": []map[string]interface{}{row("c1", "k1"), row("c2", "k2")}, "mode": "keyword",
	}}}
	chunks := chunkRows{rows: []*types.Chunk{
		{ID: "c1", TenantID: tenant, KnowledgeID: "k1", KnowledgeBaseID: "raw-1", ParseAttempt: 2},
		{ID: "c2", TenantID: tenant, KnowledgeID: "k2", KnowledgeBaseID: "raw-1", ParseAttempt: 1},
	}}
	got, err := chatsource.WrapTool(inner, r, turn, tenant, chunks).Execute(context.Background(), json.RawMessage(`{}`))
	require.NoError(t, err)
	rows := got.Data["results"].([]map[string]interface{})
	require.Equal(t, classic+" · 保险条款.pdf", rows[0]["knowledge_title"])
	require.Equal(t, classic, rows[0]["metadata"].(map[string]interface{})["entity_names"])
	require.Equal(t, classic+"、"+plus+" · 保险条款.pdf", rows[1]["knowledge_title"])
	require.Contains(t, got.Output, classic+" · 保险条款.pdf")
	require.Equal(t, "保险条款.pdf", inner.result.Data["results"].([]map[string]interface{})[0]["knowledge_title"],
		"the native rows are not mutated")
}

func TestQuickAnswerRawPassageNamesItsProduct(t *testing.T) {
	r, _, _, _, _ := labelFixture(nil)
	ctx, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	turn, _ := chatsource.TurnFromContext(ctx)
	labelled, uncited := rawResult("c1", "k1", "保险条款.pdf"), rawResult("c4", "k4", "附加条款.pdf")
	turn.Label([]*types.SearchResult{labelled, uncited})
	require.Equal(t, "原文检索（未经编译审核）｜所属产品："+classic+"\n正文", chatsource.AnswerPassage(ctx, labelled, "正文"))
	require.Equal(t, "原文检索（未经编译审核）｜所属产品未识别\n正文", chatsource.AnswerPassage(ctx, uncited, "正文"))
	unlabelled := &types.SearchResult{Metadata: map[string]string{"source_tier": "raw_text"}}
	require.Equal(t, "原文检索（未经编译审核）\n正文", chatsource.AnswerPassage(ctx, unlabelled, "正文"))
}

func TestNoticeAllowsSayingAbsentOnlyOnAnExplicitField(t *testing.T) {
	notice := chatsource.KnowledgeNotice(chatsource.Turn{WikiSpaces: []string{"s1"}})
	for _, want := range []string{
		"只有字段为“材料明确没有”时，才能说该产品没有这项规定",
		"搜索没有命中或页面没有结果，都不代表材料没有",
		"要说某个产品没有某项规定，先用 knowledge_get_fields 读取该产品的这一项",
		"回答中的每一条产品事实都必须在同一行带上支撑它的来源句柄",
	} {
		require.Contains(t, notice, want)
	}
	require.NotContains(t, notice, "unknown")
	require.NotContains(t, notice, "所属产品", "the raw rule only comes with raw materials")
	raw := chatsource.KnowledgeNotice(chatsource.Turn{WikiSpaces: []string{"s1"}, RawKnowledge: map[string]string{"k1": "s1"}})
	require.Contains(t, raw, "原文片段标题前标有所属产品，只能用于该产品")
	require.Contains(t, raw, "所属产品未识别的片段，不能当作任何具体产品的规定")
}
