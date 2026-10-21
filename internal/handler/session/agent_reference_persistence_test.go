package session

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/event"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestQ2bAgentCompletionPersistsReferenceIdentityAndProvenance(t *testing.T) {
	refs := types.References{
		{
			ID: "release:historical:entity/field", KnowledgeTitle: "产品 · 等待期",
			Metadata: map[string]string{
				"source_tier": "release", "release_id": "historical", "space_id": "space",
				"logical_slug": "entity/field", "evidence_index": "0",
			},
		},
		{
			ID: "release:historical:wiki/entity/page", KnowledgeTitle: "产品说明",
			Metadata: map[string]string{
				"source_tier": "wiki_page", "release_id": "historical", "space_id": "space",
				"logical_slug": "wiki/entity/page", "evidence_index": "2",
			},
		},
		{
			ID: "raw-chunk", KnowledgeBaseID: "raw-kb", KnowledgeID: "doc", KnowledgeTitle: "条款",
			Metadata: map[string]string{"source_tier": "raw_text", "release_id": "historical"},
		},
	}
	for _, withRefs := range []bool{false, true} {
		t.Run(map[bool]string{false: "no citations", true: "cited sources"}[withRefs], func(t *testing.T) {
			messages := &imageCompletionMessages{}
			stream := &imageCompletionStream{}
			h := &Handler{messageService: messages, streamManager: stream}
			bus := event.NewEventBus()
			message := &types.Message{ID: "m", SessionID: "s", Role: "assistant"}
			ctx := types.WithExecutionTenant(context.Background(), 1)
			streamHandler := h.setupStreamHandler(ctx, "s", "m", "req", 1, time.Now(), message, bus)
			data := event.AgentCompleteData{MessageID: "m", FinalAnswer: "最终回答"}
			var want types.References
			if withRefs {
				want = refs
				for _, ref := range refs {
					data.KnowledgeRefs = append(data.KnowledgeRefs, ref)
				}
			}
			require.NoError(t, bus.Emit(ctx, event.Event{Type: event.EventAgentComplete, Data: data}))
			h.completeStreamAssistantMessage(ctx, &sseStreamContext{
				eventBus: bus, streamHandler: streamHandler, assistantMessage: message,
			}, "", "")
			require.NotNil(t, messages.saved)
			require.True(t, messages.saved.IsCompleted)
			require.Equal(t, want, messages.saved.KnowledgeReferences)
			// Exercise the existing database column codec and message API field.
			stored, err := messages.saved.KnowledgeReferences.Value()
			require.NoError(t, err)
			var restored types.References
			require.NoError(t, restored.Scan(stored))
			require.Equal(t, want, restored)
			encoded, err := json.Marshal(messages.saved)
			require.NoError(t, err)
			var payload struct {
				References types.References `json:"knowledge_references"`
			}
			require.NoError(t, json.Unmarshal(encoded, &payload))
			require.Equal(t, want, payload.References)
		})
	}
}
