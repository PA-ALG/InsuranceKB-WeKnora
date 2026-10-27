package service

import (
	"context"
	"errors"
	"strings"
	"testing"

	chatpipeline "github.com/Tencent/WeKnora/internal/application/service/chat_pipeline"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/event"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// The shared acceptance fixture owns the production parallel search registration.
func q2aProductionFixture() (context.Context, *sessionService, *q1aKBs) {
	return q2aFixture()
}

func TestQ2aDeniedRawIsSilentAndPublishedStillAnswers(t *testing.T) {
	for _, mode := range []string{"restricted_key", "unavailable"} {
		t.Run(mode, func(t *testing.T) {
			ctx, svc, kbs := q2aProductionFixture()
			if mode == "restricted_key" {
				ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{
					KnowledgeBaseIDs: types.StringArray{"q-wiki"},
				})
			} else {
				kbs.singleErr = errors.New("private raw lookup denied")
			}
			run := askQ2aEdges(ctx, t, svc, "Product field", "q-chat")
			require.Empty(t, kbs.seen)
			require.Len(t, run.prompted, 1)
			require.Equal(t, "release", run.prompted[0].Metadata["source_tier"])
			require.NotContains(t, run.rendered, "q-raw")
		})
	}
}

func TestQ2aNoHitsAvoidModelAndPromptEvenWithModelFallback(t *testing.T) {
	ctx, svc, kbs := q2aProductionFixture()
	kbs.rows = nil
	svc.cfg.Conversation.FallbackStrategy = string(types.FallbackStrategyModel)
	svc.cfg.Conversation.FallbackPrompt = "model fallback {{query}}"
	capture := &q1aCaptureChat{}
	svc.modelService.(*stubModelService).chatModel = capture
	chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil)
	chatpipeline.NewPluginChatCompletionStream(svc.eventManager, svc.modelService)
	run := askQ2aEdges(ctx, t, svc, "unrelated question", "q-chat")
	require.NotNil(t, run.answer)
	require.Equal(t, chatsource.NotFoundAnswer, run.answer.Content)
	require.True(t, run.answer.IsFallback)
	require.Empty(t, run.rendered)
	require.Empty(t, capture.messages)
}

func TestQ2aFinalModelContextKeepsTiersAfterSecondFilter(t *testing.T) {
	for _, dropRaw := range []bool{false, true} {
		t.Run(map[bool]string{false: "retained", true: "reparsed"}[dropRaw], func(t *testing.T) {
			ctx, svc, _ := q2aProductionFixture()
			capture := &q1aCaptureChat{}
			svc.modelService.(*stubModelService).chatModel = capture
			svc.cfg.Conversation.Summary.ContextTemplate = "{{contexts}} {{query}}"
			chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil)
			if dropRaw {
				svc.eventManager.Register(q1aPipeline{
					events: []types.EventType{types.INTO_CHAT_MESSAGE},
					on: func(_ types.EventType, _ *types.ChatManage) {
						svc.chunkService.(*q1aChunks).repo.rows = nil
					},
				})
			}
			chatpipeline.NewPluginChatCompletionStream(svc.eventManager, svc.modelService)
			run := askQ2aEdges(ctx, t, svc, "Product field", "q-chat")
			require.NotEmpty(t, capture.messages)
			system := capture.messages[0].Content
			require.Contains(t, system, "不用常识回答具体产品事实")
			var text strings.Builder
			for _, m := range capture.messages {
				text.WriteString(m.Content)
			}
			require.Contains(t, text.String(), "已发布知识（审核过）")
			if dropRaw {
				require.NotContains(t, text.String(), "fixed material")
				require.Len(t, run.refs, 1)
			} else {
				require.Contains(t, text.String(), "原文检索（未经编译审核）")
				require.Less(t, strings.Index(text.String(), "已发布知识（审核过）"),
					strings.Index(text.String(), "fixed material"))
			}
		})
	}
}

func TestQ2aOrdinaryModelFallbackRemainsAvailable(t *testing.T) {
	ctx, svc, _, _ := q1aFixture()
	capture := &q1aCaptureChat{}
	svc.modelService.(*stubModelService).chatModel = capture
	cm := &types.ChatManage{}
	cm.Query = "ordinary question"
	cm.FallbackStrategy = types.FallbackStrategyModel
	cm.FallbackPrompt = "ordinary fallback {{query}}"
	cm.EventBus = event.NewEventBus().AsEventBusInterface()
	svc.handleFallbackResponse(ctx, cm)
	require.NotEmpty(t, capture.messages)
	require.NotContains(t, capture.messages[0].Content, "不用常识回答具体产品事实")
	require.Contains(t, capture.messages[len(capture.messages)-1].Content, "ordinary question")
}

func TestQ2aRawAdmissionTargets(t *testing.T) {
	ctx, svc, _ := q2aProductionFixture()
	targets, err := svc.buildSearchTargets(ctx, 7, []string{"q-raw"}, nil, nil)
	require.NoError(t, err)
	require.Len(t, targets, 1)
	called := false
	selected := types.SearchTargets{{
		Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "q-wiki", TenantID: 7,
	}}
	_, resolved, err := chatsource.ResolveAnswer(ctx, svc.chatSources, 7, selected,
		func(ctx context.Context, raw string) bool {
			called = true
			got, err := svc.buildSearchTargets(ctx, 7, []string{raw}, nil, nil)
			require.NoError(t, err)
			require.Len(t, got, 1)
			return err == nil && len(got) == 1
		})
	require.NoError(t, err)
	require.True(t, called)
	require.Len(t, resolved, 1)
}

func TestQ2aProductionSearchUsesOnlyPinnedRawAndOriginalModel(t *testing.T) {
	for _, query := range []string{"Product field", "unrelated question"} {
		t.Run(query, func(t *testing.T) {
			ctx, svc, kbs := q2aProductionFixture()
			svc.knowledgeBaseService = q2aModelKBs{kbs}
			run := askQ2aEdges(ctx, t, svc, query, "")
			require.Len(t, kbs.seen, 1)
			require.Equal(t, []string{"q-doc"}, kbs.seen[0].KnowledgeIDs)
			require.Equal(t, "q-chat", run.model)
			if query == "Product field" {
				require.Len(t, run.prompted, 2)
				require.Equal(t, "release", run.prompted[0].Metadata["source_tier"])
			} else {
				require.Len(t, run.prompted, 1)
			}
			raw := run.prompted[len(run.prompted)-1]
			require.Equal(t, "q-current", raw.ID)
			require.Equal(t, "raw_text", raw.Metadata["source_tier"])
			require.Nil(t, run.answer)
		})
	}
}

func TestQ2aSecondFilterEmptyStopsTheModel(t *testing.T) {
	ctx, svc, _ := q2aProductionFixture()
	capture := &q1aCaptureChat{}
	svc.modelService.(*stubModelService).chatModel = capture
	svc.cfg.Conversation.Summary.ContextTemplate = "{{contexts}} {{query}}"
	chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil)
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.INTO_CHAT_MESSAGE},
		on: func(_ types.EventType, cm *types.ChatManage) {
			require.Contains(t, cm.UserContent, "fixed material")
			svc.chunkService.(*q1aChunks).repo.rows = nil
		},
	})
	chatpipeline.NewPluginChatCompletionStream(svc.eventManager, svc.modelService)
	run := askQ2aEdges(ctx, t, svc, "unrelated question", "q-chat")
	require.Empty(t, capture.messages)
	require.Empty(t, run.refs)
	require.NotNil(t, run.answer)
	require.Equal(t, chatsource.NotFoundAnswer, run.answer.Content)
	require.True(t, run.answer.IsFallback)
}

func TestQ2aEnterpriseRulesSurviveOverridesAndFAQKeepsPublishedFirst(t *testing.T) {
	ctx, svc, kbs := q2aProductionFixture()
	kbs.rows[0].ChunkType = string(types.ChunkTypeFAQ)
	capture := &q1aCaptureChat{}
	svc.modelService.(*stubModelService).chatModel = capture
	svc.cfg.Conversation.Summary.ContextTemplate = "{{contexts}} {{query}}"
	svc.eventManager.Register(q1aPipeline{
		events: []types.EventType{types.QUERY_UNDERSTAND},
		on: func(_ types.EventType, cm *types.ChatManage) {
			cm.FAQPriorityEnabled = true
			cm.SystemPromptOverride = "custom intent system"
		},
	})
	chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil)
	chatpipeline.NewPluginChatCompletionStream(svc.eventManager, svc.modelService)
	run := askQ2aEdges(ctx, t, svc, "Product field", "q-chat")
	require.Less(t, strings.Index(run.rendered, "已发布知识（审核过）"), strings.Index(run.rendered, "原文检索（未经编译审核）"))
	require.Contains(t, capture.messages[0].Content, "custom intent system")
	require.Contains(t, capture.messages[0].Content, "不用常识回答具体产品事实")
	last := capture.messages[len(capture.messages)-1].Content
	require.Less(t, strings.Index(last, "20 days"), strings.Index(last, "fixed material"))
}

func TestQ2aOrdinaryPipelineHasNoEnterpriseRules(t *testing.T) {
	ctx, svc, _, _ := q1aFixture()
	capture := &q1aCaptureChat{}
	svc.modelService.(*stubModelService).chatModel = capture
	chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil)
	chatpipeline.NewPluginChatCompletionStream(svc.eventManager, svc.modelService)
	cm := &types.ChatManage{}
	cm.Query = "ordinary"
	cm.EventBus = event.NewEventBus().AsEventBusInterface()
	cm.SummaryConfig.ContextTemplate = "{{contexts}} {{query}}"
	cm.MergeResult = []*types.SearchResult{{
		ID: "plain-result", Content: "ordinary content", Metadata: map[string]string{"source_tier": "release"},
	}}
	require.NoError(t, svc.KnowledgeQAByEvent(ctx, cm,
		[]types.EventType{types.INTO_CHAT_MESSAGE, types.CHAT_COMPLETION_STREAM}))
	require.NotEmpty(t, capture.messages)
	for _, msg := range capture.messages {
		require.NotContains(t, msg.Content, "企业 Space 快问快答规则")
		require.NotContains(t, msg.Content, "已发布知识（审核过）")
	}
}

func TestQ2aMCPQuickAnswerKeepsItsExistingScopeAndFallback(t *testing.T) {
	for _, query := range []string{"Product field", "unrelated question"} {
		t.Run(query, func(t *testing.T) {
			ctx, svc, kbs := q2aProductionFixture()
			ctx = types.WithPrincipal(ctx, types.MCPEndpointPrincipal(7, "endpoint"))
			ctx = context.WithValue(ctx, types.MCPEndpointContextKey, &types.MCPEndpoint{ID: "endpoint", TenantID: 7})
			capture := &q1aCaptureChat{}
			svc.modelService.(*stubModelService).chatModel = capture
			svc.cfg.Conversation.FallbackStrategy = string(types.FallbackStrategyModel)
			svc.cfg.Conversation.FallbackPrompt = "existing MCP fallback {{query}}"
			svc.cfg.Conversation.Summary.ContextTemplate = "{{contexts}} {{query}}"
			chatpipeline.NewPluginIntoChatMessage(svc.eventManager, nil)
			chatpipeline.NewPluginChatCompletionStream(svc.eventManager, svc.modelService)
			run := askQ2aEdges(ctx, t, svc, query, "q-chat")
			require.Empty(t, kbs.seen)
			require.NotEmpty(t, capture.messages)
			for _, message := range capture.messages {
				require.NotContains(t, message.Content, "企业 Space 快问快答规则")
			}
			if query == "Product field" {
				require.Len(t, run.prompted, 1)
				// QA1 §4.1: every surface now renders the same Chinese field text (formerly "present").
				require.Contains(t, run.prompted[0].Content, "Product · field：20 days")
			} else {
				require.Contains(t, capture.messages[0].Content, "existing MCP fallback")
			}
		})
	}
}
