package knowledge_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func termEdgeMembers(terms any) []release.Member {
	return []release.Member{
		member("navigation", "navigation/terms", map[string]any{
			"question_terms": terms, "overview_fields": []string{"summary"},
		}),
		profile("first", [2]string{"metric", "指标标题"}, [2]string{"detail", "办理要求"},
			[2]string{"summary", "保障摘要"}, [2]string{"unpublished", "未发布标题"}),
		profile("second", [2]string{"summary", "项目概览"}, [2]string{"metric", "指标标题"}),
		entity("PX", []string{"first"}, "青岚指标变化计划", "青岚ＡＢ版"),
		entity("PY", []string{"second"}, "远山方案"),
		claim("PX", "summary", "unknown", nil), claim("PX", "detail", "present", "材料齐备"),
		claim("PX", "metric", "present", "数值一"),
		claim("PY", "metric", "absent_explicitly", nil), claim("PY", "summary", "present", "说明二"),
	}
}

func termEdgeAsk(t *testing.T, members []release.Member, question string, limit int) []string {
	t.Helper()
	fields, err := knowledge.NewService(membersReader(members)).QuestionFields(
		context.Background(), tenant, space, pinned, question, limit)
	require.NoError(t, err)
	return slugs(fields)
}

func TestQuestionTermsNormalizeAndRejectInvalidGroups(t *testing.T) {
	for _, tc := range []struct {
		name, question string
		groups         [][]string
		matched        bool
	}{
		{"nfkc whitespace punctuation", "ＰＸ a-b 变，化", [][]string{{"Ａ Ｂ", "变、化"}}, true},
		{"all three terms", "PX 数值变化比较", [][]string{{"数值", "变化", "比较"}}, true},
		{"alternative after invalid", "PX 数值变化", [][]string{{"数", "变化"}, {"数值", "变化"}}, true},
		{"missing term", "PX 数值", [][]string{{"数值", "变化"}}, false},
		{"empty group", "PX 随便问", [][]string{{}}, false},
		{"nil group", "PX 随便问", [][]string{nil}, false},
		{"punctuation only", "PX 变化", [][]string{{"，！", "变化"}}, false},
		{"too short after normalization", "PX 数变化", [][]string{{"数，", "变化"}}, false},
		{"four terms", "PX 数值变化比较条件", [][]string{{"数值", "变化", "比较", "条件"}}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			want := []string{"PX/summary"}
			if tc.matched {
				want = []string{"PX/metric"}
			}
			require.Equal(t, want, termEdgeAsk(t, termEdgeMembers(map[string]any{"metric": tc.groups}), tc.question, 0))
		})
	}
}

func TestQuestionTermsKeepPublishedScopeOrderAndLimit(t *testing.T) {
	terms := map[string]any{
		"metric": [][]string{{"共同问法"}, {"共同问法"}}, "detail": [][]string{{"共同问法"}},
		"unpublished": [][]string{{"其他问法"}}, "absent_key": [][]string{{"其他问法"}},
	}
	members := termEdgeMembers(terms)
	require.Equal(t, []string{"PX/metric", "PX/detail", "PY/metric"}, termEdgeAsk(t, members, "共同问法", 0))
	require.Equal(t, []string{"PX/metric", "PX/detail"}, termEdgeAsk(t, members, "共同问法", 2))
	require.Equal(t, []string{"PY/metric"}, termEdgeAsk(t, members, "PY 共同问法", 0))
	require.Equal(t, []string{"PX/summary"}, termEdgeAsk(t, members, "PX 其他问法", 0),
		"an unpublished key cannot turn off the ordinary product overview")
	require.Empty(t, termEdgeAsk(t, members, "其他问法", 0))
	// The reader omitted PX's metric: a vocabulary entry cannot materialize it.
	visible := []release.Member{}
	for _, item := range members {
		if item.LogicalSlug != "PX/metric" {
			visible = append(visible, item)
		}
	}
	require.Equal(t, []string{"PX/detail"}, termEdgeAsk(t, visible, "PX 共同问法", 0))
}

func TestQuestionTermsNameOnlySupplementRequiresEveryMatchingAlternative(t *testing.T) {
	for _, tc := range []struct {
		name, question string
		groups         [][]string
		want           []string
	}{
		{
			"one name contains all terms", "青岚指标变化计划",
			[][]string{{"指标", "变化"}},
			[]string{"PX/metric", "PX/summary"},
		},
		{
			"outside alternative wins", "青岚指标变化计划 比例多少",
			[][]string{{"指标", "变化"}, {"比例多少"}},
			[]string{"PX/metric"},
		},
		{
			"alternative order irrelevant", "青岚指标变化计划 比例多少",
			[][]string{{"比例多少"}, {"指标", "变化"}},
			[]string{"PX/metric"},
		},
		{"terms cannot span aliases", "PX 指标 AB", [][]string{{"指标", "AB"}}, []string{"PX/metric"}},
		{
			"terms cannot span products", "PX PY 指标 远山",
			[][]string{{"指标", "远山"}},
			[]string{"PX/metric", "PY/metric"},
		},
		{"explicit title wins", "青岚指标变化计划 指标标题", [][]string{{"指标", "变化"}}, []string{"PX/metric"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			members := termEdgeMembers(map[string]any{"metric": tc.groups})
			require.Equal(t, tc.want, termEdgeAsk(t, members, tc.question, 0))
			require.Equal(t, tc.want[:1], termEdgeAsk(t, members, tc.question, 1))
		})
	}
	members := termEdgeMembers(map[string]any{"metric": [][]string{{"指标", "变化"}}})
	members[0] = member("navigation", "navigation/terms", map[string]any{
		"question_terms":  map[string]any{"metric": [][]string{{"指标", "变化"}}},
		"overview_fields": []string{"metric", "summary", "metric"},
	})
	require.Equal(t, []string{"PX/metric", "PX/summary"}, termEdgeAsk(t, members, "青岚指标变化计划", 0))
}

func TestQuestionTermsMalformedPayloadFailsClosed(t *testing.T) {
	for _, bad := range []any{
		"bad",
		[]any{},
		map[string]any{"metric": "bad"},
		map[string]any{"metric": []any{[]any{"数值", 7}}},
	} {
		fields, err := knowledge.NewService(membersReader(termEdgeMembers(bad))).QuestionFields(
			context.Background(), tenant, space, pinned, "PX 数值 指标标题", 0)
		require.Error(t, err)
		require.Empty(t, fields, "malformed vocabulary must not yield a partial answer")
	}
}

type termVersionReader struct {
	versions map[string][]release.Member
	reads    []read
}

func (r *termVersionReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	r.reads = append(r.reads, read{tenantID, spaceID, releaseID})
	members, ok := r.versions[releaseID]
	if !ok || tenantID != tenant || spaceID != space {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return release.Release{ID: releaseID, Members: members}, nil
}

func TestQuestionTermsStayWithinTheRequestedVersion(t *testing.T) {
	r := &termVersionReader{versions: map[string][]release.Member{
		"old": termEdgeMembers(nil),
		"new": termEdgeMembers(map[string]any{"metric": [][]string{{"问法词语"}}}),
	}}
	svc := knowledge.NewService(r)
	for _, version := range []string{"new", "old", "new"} {
		fields, err := svc.QuestionFields(context.Background(), tenant, space, version, "PX 问法词语", 0)
		require.NoError(t, err)
		want := []string{"PX/metric"}
		if version == "old" {
			want = []string{"PX/summary"}
		}
		require.Equal(t, want, slugs(fields))
		for _, field := range fields {
			require.Equal(t, version, field.ReleaseID)
		}
	}
	require.Equal(t, []read{{tenant, space, "new"}, {tenant, space, "old"}, {tenant, space, "new"}}, r.reads)
	for _, scope := range []read{{tenant + 1, space, "new"}, {tenant, "another-space", "new"}} {
		fields, err := svc.QuestionFields(
			context.Background(), scope.tenant, scope.space, scope.releaseID, "PX 问法词语", 0)
		require.Error(t, err)
		require.Empty(t, fields)
	}
	count := len(r.reads)
	_, err := svc.QuestionFields(context.Background(), tenant, space, "active", "问法词语", 0)
	require.Equal(t, release.ErrorInvalidRequest, code(t, err))
	require.Len(t, r.reads, count)
}
