// S6e acceptance: native Wiki pages of one pinned release as a third, model-written chat source
// (Spec docs/design/slices/S6e-问答读取延伸阅读页面.md §2, §4). Protected file: written by Claude.
//
// Pages are found by every query term in title, aliases, summary or link-free content; title hits
// come first, then product order, concepts before entity pages, then title. Pages whose identity
// or provenance is wrong are never found. A page becomes a citable wiki_page row only through a
// valid evidence entry, keeping its original index. RED until S6e adds SearchPages and the tool.
package knowledge_test

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/modelcontext"
)

type pageReader struct{ reads []read }

func (r *pageReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	r.reads = append(r.reads, read{tenantID, spaceID, releaseID})
	if tenantID != tenant || spaceID != space || releaseID != pinned {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return pageFixture(), nil
}

func quote(text string, page int) map[string]any {
	return map[string]any{
		"quote": text, "source_ref": "source:v1:k1:1:abc", "file_sha256": "abc", "access_scope": "space",
		"locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": page, "start": 0, "end": 1},
	}
}

func wikiPage(slugEntity, key, title string, changes map[string]any) release.Member {
	payload := map[string]any{
		"page_key": key, "entity_refs": []string{slugEntity}, "title": title,
		"page_type": strings.Split(key, "/")[0], "summary": title + "的说明。", "content": title + "正文。",
		"aliases": []string{}, "evidence": []any{}, "origin": "MODEL_GENERATED",
		"generator": "weknora-native-wiki", "model": "deepseek-v4-flash",
	}
	for k, v := range changes {
		payload[k] = v
	}
	return member("wiki_page", "wiki/"+slugEntity+"/"+key, payload)
}

func pageFixture() release.Release {
	longTail := "安佑福的等待期为90日。" + strings.Repeat("条", 900)
	return release.Release{ID: pinned, Epoch: 3, Members: []release.Member{
		entity("1828", []string{"critical"}, "丙安佑福（全能版）重大疾病保险"),
		entity("M1", []string{"medical"}, "甲医疗保险（尊享版）", "甲医疗"),
		wikiPage("1828", "entity/an-you-fu", "安佑福", map[string]any{"content": longTail}),
		wikiPage("1828", "concept/bao-xian-ze-ren", "保险责任", map[string]any{
			"content":  "## 保险责任\n\n等待期后确诊重大疾病，给付重大疾病保险金。",
			"evidence": []any{quote("", 2), quote("给付重大疾病保险金", 6)},
		}),
		wikiPage("1828", "concept/deng-dai-qi", "等待期", map[string]any{
			"aliases": []string{"观察期"},
			"content": "# 等待期\n\n被保险人在等待期内确诊，不承担保险责任。见 [[wiki/1828/concept/yi-wai|意外]]。\n\n" +
				"意外伤害导致的无等待期。",
			"evidence": []any{quote("等待期为90日", 3), quote("被保险人", 0), quote("意外无等待期", 5)},
		}),
		wikiPage("M1", "concept/deng-dai-qi", "等待期", map[string]any{"content": "甲医疗等待期30日。"}),
		// Never found: wrong slug for its page key, not model-written, a summary page, and a slug
		// naming a product its entity_refs do not list.
		member("wiki_page", "wiki/1828/concept/wrong-slug", map[string]any{
			"page_key": "concept/other", "entity_refs": []string{"1828"}, "title": "等待期别页", "page_type": "concept",
			"content": "等待期。", "origin": "MODEL_GENERATED",
		}),
		wikiPage("1828", "concept/human", "等待期人工", map[string]any{"origin": "SOURCE_SUPPORTED"}),
		wikiPage("1828", "summary/doc", "等待期摘要", map[string]any{"page_type": "summary"}),
		member("wiki_page", "wiki/9999/concept/deng-dai-qi", map[string]any{
			"page_key": "concept/deng-dai-qi", "entity_refs": []string{"1828"}, "title": "等待期", "page_type": "concept",
			"content": "等待期。", "origin": "MODEL_GENERATED",
		}),
	}}
}

func pageService() (*knowledge.Service, *pageReader) {
	r := &pageReader{}
	return knowledge.NewService(r), r
}

func pageSlugs(pages []knowledge.Page) []string {
	out := []string{}
	for _, page := range pages {
		out = append(out, page.Slug)
	}
	return out
}

func TestPagesAreFoundByTermsWithTitleHitsFirstThenProductAndPageType(t *testing.T) {
	s, r := pageService()
	pages, total, err := s.SearchPages(context.Background(), tenant, space, pinned, "等待期", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{
		"wiki/1828/concept/deng-dai-qi", "wiki/M1/concept/deng-dai-qi",
		"wiki/1828/concept/bao-xian-ze-ren", "wiki/1828/entity/an-you-fu",
	}, pageSlugs(pages))
	require.Equal(t, 4, total)
	require.Equal(t, []read{{tenant, space, pinned}}, r.reads)
	require.Equal(t, "丙安佑福（全能版）重大疾病保险", pages[0].EntityName)
	require.Equal(t, pinned, pages[0].ReleaseID)

	alias, _, err := s.SearchPages(context.Background(), tenant, space, pinned, "观察期", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"wiki/1828/concept/deng-dai-qi"}, pageSlugs(alias))

	limited, total, err := s.SearchPages(context.Background(), tenant, space, pinned, "等待期", "", 2)
	require.NoError(t, err)
	require.Len(t, limited, 2)
	require.Equal(t, 4, total)
}

func TestPageSearchNeedsEveryTermIgnoresLinkTargetsAndCanBeLimitedToAProduct(t *testing.T) {
	s, _ := pageService()
	both, _, err := s.SearchPages(context.Background(), tenant, space, pinned, "等待期 意外", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"wiki/1828/concept/deng-dai-qi"}, pageSlugs(both))

	target, total, err := s.SearchPages(context.Background(), tenant, space, pinned, "yi-wai", "", 0)
	require.NoError(t, err)
	require.Empty(t, target, "a link target is markup, not page text")
	require.Zero(t, total)

	m1, _, err := s.SearchPages(context.Background(), tenant, space, pinned, "等待期", "M1", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"wiki/M1/concept/deng-dai-qi"}, pageSlugs(m1))

	for _, args := range [][2]string{{"等待期", "9999"}, {"  ", ""}} {
		none, total, err := s.SearchPages(context.Background(), tenant, space, pinned, args[0], args[1], 0)
		require.NoError(t, err)
		require.Empty(t, none)
		require.Zero(t, total)
	}
}

func TestPageExcerptsAreMatchingLinkFreeParagraphsWithinTheLimit(t *testing.T) {
	s, _ := pageService()
	pages, _, err := s.SearchPages(context.Background(), tenant, space, pinned, "意外", "1828", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"wiki/1828/concept/deng-dai-qi"}, pageSlugs(pages))
	excerpt := pages[0].Excerpt
	require.Contains(t, excerpt, "不承担保险责任。见 意外。")
	require.Contains(t, excerpt, "意外伤害导致的无等待期。")
	require.NotContains(t, excerpt, "# 等待期", "a paragraph without a term is left out")
	require.NotContains(t, excerpt, "[[")
	require.NotContains(t, excerpt, "wiki/1828")
	require.Equal(t, []knowledge.Evidence{
		{Index: 0, Quote: "等待期为90日", Page: 3, SourceRef: "source:v1:k1:1:abc"},
		{Index: 2, Quote: "意外无等待期", Page: 5, SourceRef: "source:v1:k1:1:abc"},
	}, pages[0].Evidence)

	long, _, err := s.SearchPages(context.Background(), tenant, space, pinned, "安佑福", "1828", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"wiki/1828/entity/an-you-fu"}, pageSlugs(long))
	require.LessOrEqual(t, utf8.RuneCountInString(long[0].Excerpt), 801)
	require.True(t, strings.HasSuffix(long[0].Excerpt, "…"))
	require.True(t, strings.HasPrefix(long[0].Excerpt, "安佑福的等待期为90日。"))
}

func TestPageSearchReadsOnlyTheNamedRelease(t *testing.T) {
	s, r := pageService()
	_, _, err := s.SearchPages(context.Background(), tenant, space, "active", "等待期", "", 0)
	var typed *release.Error
	require.True(t, errors.As(err, &typed))
	require.Equal(t, release.ErrorInvalidRequest, typed.Code)
	require.Empty(t, r.reads)
}

func TestPageToolGivesModelWrittenRowsOnlyThroughValidEvidence(t *testing.T) {
	s, r := pageService()
	bound := map[string]string{space: pinned}
	require.Len(t, knowledge.NewTools(s, tenant, bound), 5)
	query := tool(t, s, "knowledge_search_pages", bound)
	bound[space] = "new-active"
	result, err := query.Execute(toolContext(), json.RawMessage(`{"query":"等待期","entity_id":"1828"}`))
	require.NoError(t, err)
	require.Equal(t, []read{{tenant, space, pinned}}, r.reads)

	rows := result.Data["results"].([]map[string]interface{})
	require.Len(t, rows, 2)
	require.Equal(t, "release:rel-3:wiki/1828/concept/deng-dai-qi", rows[0]["chunk_id"])
	require.Equal(t, map[string]string{
		"source_tier": "wiki_page", "space_id": space, "release_id": pinned,
		"logical_slug": "wiki/1828/concept/deng-dai-qi", "evidence_index": "0",
	}, rows[0]["metadata"])
	require.Equal(t, "丙安佑福（全能版）重大疾病保险 · 等待期", rows[0]["knowledge_title"])
	require.True(t, strings.HasPrefix(rows[0]["content"].(string), "模型整理（未逐条审核）："))
	require.Contains(t, rows[0]["content"], "引文：等待期为90日（第 3 页）")
	// The first evidence entry is invalid, so the row cites the next one by its own index.
	require.Equal(t, "1", rows[1]["metadata"].(map[string]string)["evidence_index"])

	notes := strings.Join(result.Data["notes"].([]string), "\n")
	require.Contains(t, notes, "安佑福")
	require.Contains(t, notes, "（无可回验出处，不作为出处）")

	rendered := modelcontext.NewRegistry(true).ModelToolResultForTool(query.Name(), result)
	require.Contains(t, rendered, "模型整理（未逐条审核）")
	require.NotContains(t, rendered, "已发布知识（审核过）")
	require.NotContains(t, rendered, "release:rel-3:")
}
