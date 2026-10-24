package service

// S7d-2c-3a review R1: a knowledge base left out of the turn is left out of everything the model
// sees, not only out of the tools — its generated profile, its ID and a suggested question taken
// from it never reach the system prompt or any message.

import (
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent/tools"
	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

const custodyMarker = "unreleased-custody-profile-marker"

func modelSaw(model *q1aCaptureChat) string {
	parts := []string{model.lastSystemPrompt}
	for _, message := range model.messages {
		parts = append(parts, message.Content)
	}
	return strings.Join(parts, "\n")
}

func promptTurn(t *testing.T, kbIDs ...string) string {
	t.Helper()
	ctx, quick, _, kbs := q1aFixture()
	kbs.rawWiki = true
	kbs.profile = &types.KnowledgeBaseProfile{Gist: custodyMarker}
	svc := &agentService{
		cfg: quick.cfg, knowledgeBaseService: kbs, knowledgeService: &q1aDocs{},
		chunkService: quick.chunkService, chatSources: quick.chatSources,
		managedKBs: &scopeClassifier{roles: map[string]managed.Role{
			"legacy-wiki": {Kind: managed.KindWiki, State: managed.StatePending},
		}},
	}
	config := &types.AgentConfig{
		KnowledgeBases: kbIDs,
		QuestionOrigin: &types.QuestionOrigin{KnowledgeBaseID: "legacy-wiki", KnowledgeID: "legacy-doc"},
		AllowedTools:   []string{tools.ToolSearchKnowledge, tools.ToolWikiSearch},
	}
	for _, id := range kbIDs {
		config.SearchTargets = append(config.SearchTargets, &types.SearchTarget{
			Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: id, TenantID: 7,
		})
	}
	model := &q1aCaptureChat{}
	engine, err := svc.CreateAgentEngine(ctx, config, model, nil, nil, "session", "message")
	require.NoError(t, err)
	_, err = engine.Execute(ctx, "session", "message", "question", nil)
	require.NoError(t, err)
	require.Equal(t, []string{"legacy-wiki"}, config.KnowledgeBases[:1], "the saved config is not rewritten")
	return modelSaw(model)
}

// Knowledge-base and document IDs reach the model only as request-local handles (b1, d1), so the
// checks below count bound knowledge bases instead of looking for raw IDs.
func TestAnExcludedManagedWikiNeverReachesTheModel(t *testing.T) {
	seen := promptTurn(t, "legacy-wiki")
	require.NotContains(t, seen, custodyMarker)
	require.NotContains(t, seen, "<knowledge_base ")
	require.NotContains(t, seen, "unreleased secret title", "nor its documents")
	require.NotContains(t, seen, "<question_origin", "nor a suggested question taken from it")
}

func TestAMixedTurnKeepsOnlyTheUnmanagedKnowledgeBase(t *testing.T) {
	seen := promptTurn(t, "legacy-wiki", "plain")
	require.Equal(t, 1, strings.Count(seen, "<knowledge_base "), "only the unmanaged knowledge base is bound")
	require.NotContains(t, seen, "<question_origin")
}
