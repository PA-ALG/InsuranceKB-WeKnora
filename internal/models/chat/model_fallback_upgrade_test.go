package chat

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/api"
	"github.com/Tencent/WeKnora/internal/models/api/anthropicmessages"
	"github.com/Tencent/WeKnora/internal/models/api/googlegenai"
	"github.com/Tencent/WeKnora/internal/models/api/openaicompletions"
	"github.com/Tencent/WeKnora/internal/models/api/openairesponses"
	"github.com/Tencent/WeKnora/internal/types"
)

type fallbackProtocolFixture struct {
	name        string
	successBody string
	newClient   func(api.Endpoint) Chat
}

func fallbackProtocolFixtures() []fallbackProtocolFixture {
	return []fallbackProtocolFixture{
		{
			name:        "openai_completions",
			successBody: `{"choices":[{"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}`,
			newClient: func(endpoint api.Endpoint) Chat {
				return openaicompletions.New(openaicompletions.Config{
					Endpoint: endpoint,
					Settings: api.DefaultOpenAICompletions(),
				})
			},
		},
		{
			name: "openai_responses",
			successBody: `{"status":"completed","output":[{"type":"message","content":[` +
				`{"type":"output_text","text":"ok"}]}]}`,
			newClient: func(endpoint api.Endpoint) Chat {
				return openairesponses.New(openairesponses.Config{
					Endpoint: endpoint,
					Settings: api.DefaultOpenAIResponses(),
				})
			},
		},
		{
			name: "anthropic_messages",
			successBody: `{"type":"message","content":[{"type":"text","text":"ok"}],` +
				`"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}`,
			newClient: func(endpoint api.Endpoint) Chat {
				return anthropicmessages.New(anthropicmessages.Config{
					Endpoint: endpoint,
					Settings: api.DefaultAnthropicMessages(),
				})
			},
		},
		{
			name: "google_generate_content",
			successBody: `{"candidates":[{"content":{"role":"model","parts":[{"text":"ok"}]},` +
				`"finishReason":"STOP"}]}`,
			newClient: func(endpoint api.Endpoint) Chat {
				return googlegenai.New(googlegenai.Config{
					Endpoint: endpoint,
					Settings: api.DefaultGoogleGenerativeAI(),
				})
			},
		},
	}
}

func TestUPGNativeMultimodalFallbackHonorsRetryPolicy(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, fixture := range fallbackProtocolFixtures() {
		t.Run(fixture.name, func(t *testing.T) {
			for _, mode := range []string{"ordinary", "disabled chat", "disabled stream"} {
				t.Run(mode, func(t *testing.T) {
					var mu sync.Mutex
					var bodies []string
					server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						mu.Lock()
						defer mu.Unlock()
						body, _ := io.ReadAll(r.Body)
						bodies = append(bodies, string(body))
						w.Header().Set("Content-Type", "application/json")
						if len(bodies) == 1 {
							w.WriteHeader(http.StatusBadRequest)
							_, _ = w.Write([]byte(`{"error":{"message":"image not supported"}}`))
							return
						}
						_, _ = w.Write([]byte(fixture.successBody))
					}))
					defer server.Close()
					client := fixture.newClient(api.Endpoint{
						BaseURL: server.URL, Model: "fixture-model", ModelID: "fixture-row", Client: server.Client(),
					})
					ctx := types.WithLLMCallMetadata(context.Background(), "document_summary", "")
					if mode != "ordinary" {
						ctx = types.WithModelAutomaticRetryDisabled(ctx)
					}
					messages := []Message{{
						Role: "user", Content: "source", Images: []string{"data:image/png;base64,aGVsbG8="},
					}}
					var err error
					if mode == "disabled stream" {
						_, err = client.ChatStream(ctx, messages, &ChatOptions{})
					} else {
						_, err = client.Chat(ctx, messages, &ChatOptions{})
					}
					mu.Lock()
					defer mu.Unlock()
					if mode == "ordinary" {
						if err != nil || len(bodies) != 2 {
							t.Fatalf("HTTP sends=%d want=2 err=%v", len(bodies), err)
						}
						if bodies[0] == bodies[1] {
							t.Fatal("fallback did not strip the image payload")
						}
					} else if err == nil || len(bodies) != 1 {
						t.Fatalf("disabled fallback: HTTP sends=%d want=1 err=%v", len(bodies), err)
					}
				})
			}
		})
	}
}
