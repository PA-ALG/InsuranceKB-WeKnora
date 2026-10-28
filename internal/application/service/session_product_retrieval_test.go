package service

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type productSourceReader struct{}

func (productSourceReader) ReleaseByID(ctx context.Context, tenant uint64, space, id string) (release.Release, error) {
	reader := &publishedReader{}
	result, err := reader.ReleaseByID(ctx, tenant, space, id)
	if err != nil {
		return result, err
	}
	result.Members[1].Payload = json.RawMessage(`{"subject_ref":"E","predicate":"field","state":"present",` +
		`"value":"20 days","origin":"SOURCE_SUPPORTED","evidence":[{"quote":"20 days",` +
		`"locator":{"kind":"PDF_TEXT_SPAN","page":3},"source_ref":"source:v1:q-doc:2:` +
		strings.Repeat("ab", 32) + `"}]}`)
	return result, nil
}

func TestQA2ProductionParallelSearchCopiesTheExpandedScope(t *testing.T) {
	ctx, svc, kbs := q2aFixture()
	svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(productSourceReader{}))
	svc.knowledgeBaseService = q2aModelKBs{kbs}
	var afterSearch types.SearchTargets
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.CHUNK_MERGE},
		on: func(_ types.EventType, cm *types.ChatManage) {
			afterSearch = append(types.SearchTargets(nil), cm.SearchTargets...)
		},
	})
	run := askQ2aEdges(ctx, t, svc, "Product field", "")
	require.Len(t, kbs.seen, 2, "one global and one product search through the real parallel plugin")
	for _, call := range kbs.seen {
		require.Equal(t, []string{"q-doc"}, call.KnowledgeIDs)
		require.Equal(t, 10, call.MatchCount)
	}
	require.Len(t, afterSearch, 1, "stage-local targets are restored before merge")
	require.Equal(t, "q-chat", run.model)
	require.Equal(t, []string{"release:q-release:E/field", "q-current"}, ids(run.prompted),
		"native deduplication and both pinned-parse filters still run")
}

type productStageFailure struct {
	event types.EventType
	see   func(*types.ChatManage)
	err   error
}

func (p productStageFailure) ActivationEvents() []types.EventType { return []types.EventType{p.event} }

func (p productStageFailure) OnEvent(
	_ context.Context, _ types.EventType, cm *types.ChatManage, _ func() *chatpipeline.PluginError,
) *chatpipeline.PluginError {
	p.see(cm)
	return &chatpipeline.PluginError{Err: p.err}
}

func TestQA2StageFailureRestoresRetrievalInputs(t *testing.T) {
	for _, event := range []types.EventType{types.CHUNK_SEARCH, types.CHUNK_RERANK, types.FILTER_TOP_K} {
		t.Run(string(event), func(t *testing.T) {
			ctx, svc, _ := q2aFixture()
			svc.chatSources = svc.chatSources.WithPublished(knowledge.NewService(productSourceReader{}))
			ctx, targets, err := chatsource.ResolveAnswer(ctx, svc.chatSources, 7, types.SearchTargets{{
				Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-raw", TenantID: 7,
			}})
			require.NoError(t, err)
			cm := &types.ChatManage{}
			cm.Query, cm.RewriteQuery = "other", "Product field"
			cm.SearchTargets, cm.RerankTopK = targets, 1
			cm.SearchResult = []*types.SearchResult{{ID: "a"}, {ID: "b"}, {ID: "c"}}
			if event == types.FILTER_TOP_K {
				cm.RerankTopK = 5
				cm.MergeResult = []*types.SearchResult{
					{ID: "a", KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw"},
					{ID: "b", KnowledgeID: "q-doc", KnowledgeBaseID: "q-raw"},
				}
			}
			originalTopK := cm.RerankTopK
			boom := errors.New("offline stage failure")
			observed := false
			svc.eventManager = chatpipeline.NewEventManager()
			svc.eventManager.Register(productStageFailure{event: event, err: boom, see: func(cm *types.ChatManage) {
				observed = true
				switch event {
				case types.CHUNK_SEARCH:
					require.Len(t, cm.SearchTargets, 2)
				case types.CHUNK_RERANK:
					require.Equal(t, 3, cm.RerankTopK)
				case types.FILTER_TOP_K:
					require.Equal(t, 2, cm.RerankTopK)
				}
			}})
			require.ErrorIs(t, svc.KnowledgeQAByEvent(ctx, cm, []types.EventType{event}), boom)
			require.True(t, observed)
			require.Equal(t, targets, cm.SearchTargets)
			require.Equal(t, originalTopK, cm.RerankTopK)
		})
	}
}
