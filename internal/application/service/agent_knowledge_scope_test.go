package service

// S7d-2c-3a acceptance (protected, written by Claude): an Agent turn reads natively only the
// knowledge bases that are neither an enterprise Space nor managed by a release. A managed one
// (an old 830/G3 Head, its RAW KB) is left out of the turn instead of being pinned, and an
// unknown custody fails the turn closed (Spec docs/design/slices/S7d-2c-3a-问答不再固定旧830版本.md §4).
// RED until S7d-2c-3a: resolveAgentKnowledgeScope and agentService.managedKBs do not exist.

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type scopeClassifier struct {
	roles map[string]managed.Role
	err   error
	asked []string
}

func (c *scopeClassifier) Classify(_ context.Context, _ uint64, kbID string) (managed.Role, error) {
	c.asked = append(c.asked, kbID)
	if c.err != nil {
		return managed.Role{}, c.err
	}
	if role, ok := c.roles[kbID]; ok {
		return role, nil
	}
	return managed.Role{Kind: managed.KindNone, State: managed.StateUnmanaged}, nil
}

func scopeTargets(ids ...string) *types.AgentConfig {
	config := &types.AgentConfig{}
	for _, id := range ids {
		config.SearchTargets = append(config.SearchTargets, &types.SearchTarget{
			Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: id, TenantID: 7,
		})
	}
	return config
}

func scopeService(classifier managed.Classifier) (context.Context, *agentService) {
	ctx, quick, _, kbs := q1aFixture()
	kbs.rawWiki = true // every knowledge base of the fixture has the native wiki on
	return ctx, &agentService{
		cfg: quick.cfg, knowledgeBaseService: quick.knowledgeBaseService,
		chatSources: quick.chatSources, managedKBs: classifier,
	}
}

func targetIDs(targets types.SearchTargets) []string {
	ids := make([]string, 0, len(targets))
	for _, target := range targets {
		ids = append(ids, target.KnowledgeBaseID)
	}
	return ids
}

func TestManagedKnowledgeBasesAreLeftOutOfTheTurn(t *testing.T) {
	classifier := &scopeClassifier{roles: map[string]managed.Role{
		"legacy-wiki": {Kind: managed.KindWiki, State: managed.StateActive},
		"legacy-raw":  {Kind: managed.KindRaw, State: managed.StateActive},
	}}
	ctx, svc := scopeService(classifier)

	scope, err := svc.resolveAgentKnowledgeScope(ctx, scopeTargets("legacy-wiki", "legacy-raw", "plain", "q-wiki"))
	require.NoError(t, err)
	require.Equal(t, []string{"plain"}, targetIDs(scope.searchTargets))
	require.Equal(t, []string{"plain"}, scope.wikiKBIDs)
	require.ElementsMatch(t, []string{"legacy-wiki", "legacy-raw"}, scope.excluded)
	require.NotContains(t, classifier.asked, "q-wiki", "an enterprise Space is never classified here")
}

func TestUnknownCustodyFailsTheTurnClosed(t *testing.T) {
	ctx, svc := scopeService(&scopeClassifier{err: errors.New("custody unavailable")})
	_, err := svc.resolveAgentKnowledgeScope(ctx, scopeTargets("plain"))
	require.Error(t, err)

	ctx, svc = scopeService(nil)
	_, err = svc.resolveAgentKnowledgeScope(ctx, scopeTargets("plain"))
	require.Error(t, err, "without a classifier no native read is allowed")
}

func TestEnterpriseOnlyTurnsNeedNoClassifier(t *testing.T) {
	ctx, svc := scopeService(nil)
	scope, err := svc.resolveAgentKnowledgeScope(ctx, scopeTargets("q-wiki", "q-raw"))
	require.NoError(t, err)
	require.Empty(t, scope.searchTargets)
	require.Empty(t, scope.wikiKBIDs)
	require.Empty(t, scope.excluded)
}
