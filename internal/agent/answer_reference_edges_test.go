package agent

import (
	"context"
	"encoding/json"
	"sync"
	"testing"

	agenttools "github.com/Tencent/WeKnora/internal/agent/tools"
	"github.com/Tencent/WeKnora/internal/event"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestQ2bCompletionRecordsOnlyFinalCitationsOnBothExitPaths(t *testing.T) {
	for _, limit := range []int{10, 0} {
		for _, cited := range []bool{false, true} {
			name := map[int]string{10: "normal", 0: "iteration limit"}[limit] +
				map[bool]string{false: "/uncited", true: "/cited"}[cited]
			t.Run(name, func(t *testing.T) {
				answer := "未找到来源。"
				if cited {
					answer = `条款<ref id="c2"/>，字段<ref id="c1"/>，条款<ref id="c2"/>。`
				}
				model := &mockChat{responses: []mockResponse{{chunks: []types.StreamResponse{{
					ResponseType: types.ResponseTypeAnswer, Content: answer, Done: true, FinishReason: "stop",
				}}}}}
				e := newTestEngine(t, model, withMaxIterations(limit))
				e.toolRegistry = agenttools.NewToolRegistry()
				e.modelContext.ModelToolResultForTool("knowledge_search_fields", &types.ToolResult{
					Success: true, Data: map[string]interface{}{
						"display_type": "search_results", "results": []map[string]interface{}{
							{
								"chunk_id": "release:pinned:entity/field", "knowledge_title": "字段",
								"metadata": map[string]string{"source_tier": "release", "release_id": "pinned"},
							},
							{
								"chunk_id": "raw-chunk", "knowledge_id": "doc", "knowledge_base_id": "raw-kb",
								"knowledge_title": "条款",
								"metadata": map[string]interface{}{
									"source_tier": "raw_text", "release_id": "pinned",
								},
							},
							{"chunk_id": "unused"},
						},
					},
				})
				var mu sync.Mutex
				var completions []event.AgentCompleteData
				e.eventBus.On(event.EventAgentComplete, func(_ context.Context, evt event.Event) error {
					mu.Lock()
					defer mu.Unlock()
					completions = append(completions, evt.Data.(event.AgentCompleteData))
					return nil
				})
				state, err := e.Execute(context.Background(), "s", "m", "产品事实", nil)
				require.NoError(t, err)
				require.True(t, state.IsComplete)
				require.Equal(t, 1, model.callCount, "recording must not add a model call")
				mu.Lock()
				defer mu.Unlock()
				require.Len(t, completions, 1)
				completion := completions[0]
				require.Equal(t, state.FinalAnswer, completion.FinalAnswer)
				require.Equal(t, "m", completion.MessageID)
				if !cited {
					require.Equal(t, answer, state.FinalAnswer)
					require.Empty(t, state.KnowledgeRefs)
					require.Empty(t, completion.KnowledgeRefs)
					return
				}
				require.Equal(t, []string{"raw-chunk", "release:pinned:entity/field"}, refIDs(state))
				require.Contains(t, state.FinalAnswer, `chunk_id="release:pinned:entity/field"`)
				require.Contains(t, state.FinalAnswer, `chunk_id="raw-chunk"`)
				require.NotContains(t, state.FinalAnswer, "<ref")
				require.Len(t, completion.KnowledgeRefs, 2)
				for i, ref := range state.KnowledgeRefs {
					require.Equal(t, "pinned", ref.Metadata["release_id"])
					require.Equal(t, ref, completion.KnowledgeRefs[i])
				}
				require.Equal(t, "raw_text", state.KnowledgeRefs[0].Metadata["source_tier"])
				require.Equal(t, "release", state.KnowledgeRefs[1].Metadata["source_tier"])
			})
		}
	}
}

type q2bReferenceTool struct {
	agenttools.BaseTool
	calls int
}

func (tool *q2bReferenceTool) Execute(context.Context, json.RawMessage) (*types.ToolResult, error) {
	tool.calls++
	return &types.ToolResult{Success: true, Data: map[string]interface{}{
		"display_type": "search_results", "results": []map[string]interface{}{{
			"chunk_id": "release:fixed:wiki/entity/page", "knowledge_title": "补充说明", "content": "产品事实",
			"metadata": map[string]string{
				"source_tier": "wiki_page", "release_id": "fixed", "space_id": "space",
				"logical_slug": "wiki/entity/page", "evidence_index": "2",
			},
		}},
	}}, nil
}

func TestQ2bRealToolRegistrationSurvivesNormalAndForcedCompletion(t *testing.T) {
	for _, limit := range []int{10, 1} {
		t.Run(map[int]string{10: "normal", 1: "forced"}[limit], func(t *testing.T) {
			tool := &q2bReferenceTool{BaseTool: agenttools.NewBaseTool(
				"knowledge_search_pages", "test knowledge source", json.RawMessage(`{"type":"object"}`),
			)}
			model := &mockChat{responses: []mockResponse{
				{chunks: []types.StreamResponse{{
					ToolCalls: []types.LLMToolCall{{
						ID: "source-call", Type: "function",
						Function: types.FunctionCall{Name: tool.Name(), Arguments: "{}"},
					}}, Done: true, FinishReason: "tool_calls",
				}}},
				{chunks: []types.StreamResponse{{
					ResponseType: types.ResponseTypeAnswer, Content: `回答<ref id="c1"/>`,
					Done: true, FinishReason: "stop",
				}}},
			}}
			e := newTestEngine(t, model, withMaxIterations(limit))
			e.toolRegistry = agenttools.NewToolRegistry()
			e.toolRegistry.RegisterTool(tool)
			state, err := e.Execute(context.Background(), "s", "m", "查询事实", nil)
			require.NoError(t, err)
			require.Equal(t, 1, tool.calls)
			require.Equal(t, 2, model.callCount)
			require.Equal(t, []string{"release:fixed:wiki/entity/page"}, refIDs(state))
			require.Equal(t, map[string]string{
				"source_tier": "wiki_page", "release_id": "fixed", "space_id": "space",
				"logical_slug": "wiki/entity/page", "evidence_index": "2",
			}, state.KnowledgeRefs[0].Metadata)
			require.Equal(t, `回答<kb doc="补充说明" chunk_id="release:fixed:wiki/entity/page" />`, state.FinalAnswer)
			if limit == 1 {
				require.Equal(t, "none", model.opts[1].ToolChoice)
				require.Empty(t, model.opts[1].Tools)
			}
		})
	}
}

func TestQ2bOrdinaryAgentKeepsPromptAnswerAndToolFlow(t *testing.T) {
	answer := `原有回答<ref id="c2"/>。`
	e := answerReferenceEngine(t, answer)
	state, err := e.Execute(context.Background(), "s", "m", "原问题", nil)
	require.NoError(t, err)
	require.Equal(t, `原有回答<kb doc="条款" chunk_id="chunk-raw" kb_id="raw-kb" />。`, state.FinalAnswer)
	require.Equal(t, []string{"chunk-raw"}, refIDs(state))
	require.Empty(t, state.KnowledgeRefs[0].Metadata)
	model := e.chatModel.(*mockChat)
	require.Equal(t, 1, model.callCount)
	for _, message := range model.calls[0] {
		require.NotContains(t, message.Content, "回答中的每一条产品事实都必须")
		require.NotContains(t, message.Content, "已发布知识优先")
	}
	for _, step := range state.RoundSteps {
		require.Empty(t, step.ToolCalls)
	}
}
