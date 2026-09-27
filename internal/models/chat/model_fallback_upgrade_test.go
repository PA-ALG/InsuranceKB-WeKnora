package chat

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/api"
	"github.com/Tencent/WeKnora/internal/models/api/anthropicmessages"
	"github.com/Tencent/WeKnora/internal/models/api/googlegenai"
	"github.com/Tencent/WeKnora/internal/models/api/openaicompletions"
	"github.com/Tencent/WeKnora/internal/models/api/openairesponses"
	"github.com/Tencent/WeKnora/internal/types"
)

type fallbackUpgradeTransport struct {
	bodies            []string
	successBody       string
	succeedAfterFirst bool
}

func (t *fallbackUpgradeTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	body, _ := io.ReadAll(req.Body)
	t.bodies = append(t.bodies, string(body))
	status := http.StatusBadRequest
	responseBody := `{"error":{"message":"image not supported"}}`
	if t.succeedAfterFirst && len(t.bodies) > 1 {
		status = http.StatusOK
		responseBody = t.successBody
	}
	return &http.Response{
		StatusCode: status,
		Status:     http.StatusText(status),
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader(responseBody)),
		Request:    req,
	}, nil
}

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

func newFallbackProtocolClient(
	fixture fallbackProtocolFixture,
	transport *fallbackUpgradeTransport,
) Chat {
	return fixture.newClient(api.Endpoint{
		BaseURL: "https://127.0.0.1",
		Model:   "fixture-model", ModelID: "fixture-row",
		DispatchOperation: "document_summary",
		Client:            &http.Client{Transport: transport},
	})
}

func fallbackUpgradeContext(recorder *chatDispatchRecorderStub, disabled bool) context.Context {
	ctx := types.WithModelDispatchRecorder(context.Background(), recorder)
	ctx = types.WithLLMCallMetadata(ctx, "document_summary", "")
	if disabled {
		ctx = types.WithModelAutomaticRetryDisabled(ctx)
	}
	return ctx
}

func fallbackUpgradeMessages() []Message {
	return []Message{{
		Role: "user", Content: "source",
		Images: []string{"data:image/png;base64,aGVsbG8="},
	}}
}

func TestUPGNativeMultimodalFallbackHonorsDispatchPolicy(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, fixture := range fallbackProtocolFixtures() {
		t.Run(fixture.name, func(t *testing.T) {
			t.Run("ordinary fallback has its own receipt", func(t *testing.T) {
				transport := &fallbackUpgradeTransport{
					successBody: fixture.successBody, succeedAfterFirst: true,
				}
				recorder := &chatDispatchRecorderStub{}
				client := newFallbackProtocolClient(fixture, transport)
				if _, err := client.Chat(
					fallbackUpgradeContext(recorder, false), fallbackUpgradeMessages(), &ChatOptions{},
				); err != nil {
					t.Fatal(err)
				}
				if len(transport.bodies) != 2 || len(recorder.specs) != 2 || len(recorder.results) != 2 {
					t.Fatalf("sends=%d specs=%d results=%d, want 2 each",
						len(transport.bodies), len(recorder.specs), len(recorder.results))
				}
				if recorder.specs[0].TransportRetryIndex != 0 || recorder.specs[1].TransportRetryIndex != 1 {
					t.Fatalf("fallback receipt indices = %d,%d, want 0,1",
						recorder.specs[0].TransportRetryIndex, recorder.specs[1].TransportRetryIndex)
				}
				if transport.bodies[0] == transport.bodies[1] {
					t.Fatal("fallback did not strip the image payload")
				}
			})

			for _, stream := range []bool{false, true} {
				name := "chat"
				if stream {
					name = "stream"
				}
				t.Run("disabled "+name+" sends once", func(t *testing.T) {
					transport := &fallbackUpgradeTransport{}
					recorder := &chatDispatchRecorderStub{}
					client := newFallbackProtocolClient(fixture, transport)
					ctx := fallbackUpgradeContext(recorder, true)
					var err error
					if stream {
						_, err = client.ChatStream(ctx, fallbackUpgradeMessages(), &ChatOptions{})
					} else {
						_, err = client.Chat(ctx, fallbackUpgradeMessages(), &ChatOptions{})
					}
					if err == nil {
						t.Fatal("disabled fallback unexpectedly succeeded")
					}
					if len(transport.bodies) != 1 || len(recorder.specs) != 1 || len(recorder.results) != 1 {
						t.Fatalf("sends=%d specs=%d results=%d, want 1 each",
							len(transport.bodies), len(recorder.specs), len(recorder.results))
					}
				})
			}

			t.Run("journal failure cannot fallback", func(t *testing.T) {
				transport := &fallbackUpgradeTransport{
					successBody: fixture.successBody, succeedAfterFirst: true,
				}
				recorder := &chatDispatchRecorderStub{recordErr: errors.New("receipt store unavailable")}
				client := newFallbackProtocolClient(fixture, transport)
				_, err := client.Chat(
					fallbackUpgradeContext(recorder, false), fallbackUpgradeMessages(), &ChatOptions{},
				)
				if !errors.Is(err, types.ErrModelDispatchJournalUnavailable) {
					t.Fatalf("journal failure lost: %v", err)
				}
				if len(transport.bodies) != 1 || len(recorder.specs) != 1 || len(recorder.results) != 1 {
					t.Fatalf("sends=%d specs=%d results=%d, want 1 each",
						len(transport.bodies), len(recorder.specs), len(recorder.results))
				}
			})
		})
	}
}
