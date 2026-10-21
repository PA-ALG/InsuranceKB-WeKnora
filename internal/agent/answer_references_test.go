package agent

// Q2b acceptance (protected, written by Claude): an agent turn records the sources its final
// answer actually cites, in first-citation order, so the saved message carries
// knowledge_references like a quick answer does (Spec docs/design/slices/Q2b-Agent回答引用.md §4).
// RED until Q2b: AgentState.KnowledgeRefs is never filled.

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	agenttools "github.com/Tencent/WeKnora/internal/agent/tools"
	"github.com/Tencent/WeKnora/internal/modelcontext"
	"github.com/Tencent/WeKnora/internal/types"
)

func answerReferenceEngine(t *testing.T, answer string) *AgentEngine {
	t.Helper()
	model := &mockChat{responses: []mockResponse{{chunks: []types.StreamResponse{{
		ResponseType: types.ResponseTypeAnswer, Content: answer, Done: true, FinishReason: "stop",
	}}}}}
	engine := newTestEngine(t, model)
	engine.toolRegistry = agenttools.NewToolRegistry()
	for _, ref := range []modelcontext.ChunkReference{
		{ChunkID: "release:rel-1:E/field", DocumentTitle: "E · field"},                                   // c1
		{ChunkID: "chunk-raw", KnowledgeID: "doc-1", KnowledgeBaseID: "raw-kb", DocumentTitle: "条款"},     // c2
		{ChunkID: "chunk-unused", KnowledgeID: "doc-2", KnowledgeBaseID: "raw-kb", DocumentTitle: "说明书"}, // c3
	} {
		engine.modelContext.RegisterChunk(ref)
	}
	return engine
}

func refIDs(state *types.AgentState) []string {
	out := []string{}
	for _, ref := range state.KnowledgeRefs {
		out = append(out, ref.ID)
	}
	return out
}

func TestAnAgentAnswerRecordsTheSourcesItCitesInOrder(t *testing.T) {
	engine := answerReferenceEngine(t, `等待期90日<ref id="c1"/>，意外无等待期<ref id="c2"/>，再述<ref id="c1"/>。`)
	state, err := engine.Execute(context.Background(), "session", "message", "等待期多久", nil)
	require.NoError(t, err)
	require.Equal(t, []string{"release:rel-1:E/field", "chunk-raw"}, refIDs(state))
}

func TestAnAnswerWithoutCitationsRecordsNoSources(t *testing.T) {
	engine := answerReferenceEngine(t, "等待期90日。")
	state, err := engine.Execute(context.Background(), "session", "message", "等待期多久", nil)
	require.NoError(t, err)
	require.Empty(t, state.KnowledgeRefs)
}
