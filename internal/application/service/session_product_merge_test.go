package service

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// twoProductReader pins q-release: "Product" (E) cites q-doc, "Rival" (F) cites f-doc.
type twoProductReader struct{}

func (twoProductReader) ReleaseByID(_ context.Context, tenant uint64, _ string, id string) (release.Release, error) {
	if tenant != 7 || id != "q-release" {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseAccessDenied}
	}
	product := func(entity, name, knowledgeID string) []release.Member {
		return []release.Member{
			{Kind: "entity", LogicalSlug: "entity/" + entity, AccessScope: "space", Payload: json.RawMessage(
				`{"entity_id":"` + entity + `","names":["` + name + `"]}`)},
			{Kind: "claim", LogicalSlug: entity + "/field", AccessScope: "space", Payload: json.RawMessage(
				`{"subject_ref":"` + entity + `","predicate":"field","state":"present","value":"v",` +
					`"origin":"SOURCE_SUPPORTED","evidence":[{"quote":"v",` +
					`"locator":{"kind":"PDF_TEXT_SPAN","page":1},` +
					`"source_ref":"source:v1:` + knowledgeID + `:2:` + strings.Repeat("ab", 32) + `"}]}`)},
		}
	}
	members := append(product("E", "Product", "q-doc"), product("F", "Rival", "f-doc")...)
	return release.Release{ID: id, Members: members}, nil
}

// QA2c through the quick-answer stage loop with the real native merge and top-k plugins: the
// rival's longer, higher-ranked copy of the clause no longer removes the named product's own, and
// the own passage, cut mid-sentence, is completed by its next passage.
func TestQA2cQuickAnswerStagesKeepTheOwnCopyAndFinishItsSentence(t *testing.T) {
	const clause = "被保险人在0至3周岁期间发生双耳失聪"
	ctx, svc, _ := q2aFixture()
	repo := &q1aChunkRepo{rows: []*types.Chunk{
		{
			ID: "own", TenantID: 7, KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", ParseAttempt: 2, IsEnabled: true,
			ChunkType: types.ChunkTypeText, ChunkIndex: 40, Content: clause, NextChunkID: "own-next",
		},
		{
			ID: "own-next", TenantID: 7, KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", ParseAttempt: 2,
			IsEnabled: true, ChunkType: types.ChunkTypeText, ChunkIndex: 41, Content: "的，本公司不承担保险责任。",
		},
	}}
	svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(twoProductReader{})).WithChunks(repo)
	ctx, targets, err := chatsource.ResolveAnswer(ctx, svc.chatSources, 7, types.SearchTargets{{
		Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7,
	}})
	require.NoError(t, err)
	cm := &types.ChatManage{}
	cm.Query, cm.RewriteQuery, cm.SearchTargets, cm.RerankTopK = "Product clause", "Product clause", targets, 1
	cm.RerankResult = []*types.SearchResult{
		{
			ID: "rival", KnowledgeID: "f-doc", KnowledgeBaseID: "q-raw", Score: 0.9, ChunkIndex: 54,
			ChunkType: types.ChunkTypeText, Content: clause + "的，本公司不承担保险责任。第五十八条 语言能力丧失。",
		},
		{
			ID: "own", KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw", Score: 0.5, ChunkIndex: 40,
			ChunkType: types.ChunkTypeText, Content: clause,
		},
	}
	svc.eventManager = chatpipeline.NewEventManager()
	chatpipeline.NewPluginMerge(svc.eventManager, nil, nil)
	chatpipeline.NewPluginFilterTopK(svc.eventManager)
	require.NoError(t, svc.KnowledgeQAByEvent(ctx, cm, []types.EventType{types.CHUNK_MERGE, types.FILTER_TOP_K}))
	require.Equal(t, []string{"own", "own-next"}, ids(cm.MergeResult))
	require.Equal(t, 1, cm.RerankTopK, "the caller's cap is restored")
}
