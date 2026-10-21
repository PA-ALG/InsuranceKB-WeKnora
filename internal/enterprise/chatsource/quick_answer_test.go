package chatsource_test

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type answerDirectory struct {
	spaces
	pairs map[string][2]string
}

func (s answerDirectory) KnowledgeBases(id uint64, space string) (string, string, bool) {
	pair, ok := s.pairs[space]
	return pair[0], pair[1], ok && id == tenant
}
func allowRaw(context.Context, string) bool { return true }

func TestAnswerAutoRawUsesFixedReleaseAcrossSpaces(t *testing.T) {
	s, h, p, a := fixture()
	s["wiki-2"] = s["wiki-1"]
	v := s["wiki-2"]
	v.space = "s2"
	s["wiki-2"] = v
	d := answerDirectory{s, map[string][2]string{"s1": {"raw-1", "wiki-1"}, "s2": {"raw-2", "wiki-2"}}}
	r := chatsource.NewResolver(d, h, p, a).WithPublished(knowledge.NewService(&publishedReader{}))
	authorize := func(_ context.Context, _ string) bool { h.active["s1"] = "new-head"; return true }
	ctx, targets, err := chatsource.ResolveAnswer(context.Background(), r, tenant,
		types.SearchTargets{kb("wiki-1"), kb("plain"), kb("wiki-2"), kb("wiki-1")}, authorize)
	require.NoError(t, err)
	require.Len(t, targets, 3)
	require.Equal(t, "plain", targets[0].KnowledgeBaseID)
	require.Equal(t, []string{"k1", "k2"}, targets[1].KnowledgeIDs)
	require.Equal(t, []string{"k9"}, targets[2].KnowledgeIDs)
	turn, _ := chatsource.TurnFromContext(ctx)
	require.Equal(t, map[string]int{"s1": 1, "s2": 1}, h.reads)
	require.Equal(t, map[string]string{"s1": "rel-1", "s2": "rel-2"}, turn.Releases)
	require.Equal(t, map[string]int64{"k1": 2, "k2": 1, "k9": 1}, turn.RawAttempts)
	require.Equal(t, map[string]string{"k1": "s1", "k2": "s1", "k9": "s2"}, turn.RawKnowledge)
}

func TestAnswerAutoRawOmissionsDoNotBroadenOrFail(t *testing.T) {
	for _, scenario := range []string{
		"denied", "missing_authorizer", "missing_directory", "cross_space",
		"wrong_wiki", "empty", "reparsed", "explicit_subset",
	} {
		t.Run(scenario, func(t *testing.T) {
			s, h, p, a := fixture()
			var directory chatsource.Spaces = answerDirectory{s, map[string][2]string{"s1": {"raw-1", "wiki-1"}}}
			authorize := allowRaw
			targets := types.SearchTargets{kb("wiki-1")}
			switch scenario {
			case "denied":
				authorize = func(context.Context, string) bool { return false }
			case "missing_authorizer":
				authorize = nil
			case "missing_directory":
				directory = s
			case "cross_space":
				directory = answerDirectory{s, map[string][2]string{"s1": {"raw-2", "wiki-1"}}}
			case "wrong_wiki":
				directory = answerDirectory{s, map[string][2]string{"s1": {"raw-1", "unknown"}}}
			case "empty":
				p.byRelease["s1/rel-1"] = nil
			case "reparsed":
				a.current = map[string]int64{}
			case "explicit_subset":
				raw := kb("raw-1")
				raw.Type = types.SearchTargetTypeKnowledge
				raw.KnowledgeIDs = []string{"k2"}
				raw.TagIDs = []string{"selected"}
				targets = append(targets, raw)
			}
			r := chatsource.NewResolver(directory, h, p, a).WithPublished(knowledge.NewService(&publishedReader{}))
			ctx, got, err := chatsource.ResolveAnswer(context.Background(), r, tenant, targets, authorize)
			require.NoError(t, err)
			require.True(t, chatsource.IsEnterpriseAnswer(ctx))
			if scenario == "explicit_subset" {
				require.Len(t, got, 1)
				require.Equal(t, []string{"k2"}, got[0].KnowledgeIDs)
				require.Equal(t, []string{"selected"}, got[0].TagIDs)
			} else {
				require.Empty(t, got)
			}
			if scenario == "empty" || scenario == "reparsed" {
				_, _, err = chatsource.ResolveAnswer(context.Background(), r, tenant,
					types.SearchTargets{kb("wiki-1"), kb("raw-1")}, authorize)
				require.Equal(t, chatsource.ErrorSourcesUnavailable, code(t, err))
			}
		})
	}
}

func TestAnswerMarkerDoesNotAffectSearchOrAgentTurns(t *testing.T) {
	s, h, p, a := fixture()
	r := resolver(s, h, p, a)
	ctx, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("plain")})
	require.NoError(t, err)
	require.False(t, chatsource.IsEnterpriseAnswer(ctx))
	ctx, _, err = chatsource.ResolveQuick(context.Background(), r, tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	require.False(t, chatsource.IsEnterpriseAnswer(ctx))
	ctx, _, err = chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	require.True(t, chatsource.IsEnterpriseAnswer(ctx))
}

func TestAnswerPassageLabelsWikiPagesOnlyForQuickAnswers(t *testing.T) {
	r, _ := published()
	ctx, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")})
	require.NoError(t, err)
	page := &types.SearchResult{Metadata: map[string]string{"source_tier": "wiki_page"}}
	require.Equal(t, "模型整理（未逐条审核）\npage", chatsource.AnswerPassage(ctx, page, "page"))
	turn, _ := chatsource.TurnFromContext(ctx)
	agentCtx := chatsource.WithTurn(context.Background(), turn, tenant)
	require.Equal(t, "page", chatsource.AnswerPassage(agentCtx, page, "page"))
	require.Empty(t, chatsource.AnswerRules(agentCtx))
}
