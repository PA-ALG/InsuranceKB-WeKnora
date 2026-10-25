package chat

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

func TestStandardSDKChatHTTPResponsesAndImageFallback(t *testing.T) {
	for _, mode := range []string{
		"success",
		"http_error",
		"transport_error",
		"image_retry",
	} {
		t.Run(mode, func(t *testing.T) {
			t.Setenv("SSRF_WHITELIST", "127.0.0.1")
			var mu sync.Mutex
			var bodies [][]byte
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				mu.Lock()
				defer mu.Unlock()
				body, _ := io.ReadAll(r.Body)
				bodies = append(bodies, body)
				if mode == "transport_error" {
					conn, _, err := w.(http.Hijacker).Hijack()
					if err == nil {
						_ = conn.Close()
					}
					return
				}
				w.Header().Set("Content-Type", "application/json")
				if mode == "http_error" || (mode == "image_retry" && len(bodies) == 1) {
					w.WriteHeader(400)
					message := "invalid request"
					if mode != "http_error" {
						message = "image not supported"
					}
					_, _ = fmt.Fprintf(w, `{"error":{"message":%q,"type":"invalid_request_error"}}`, message)
					return
				}
				_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"summary"}}]}`))
			}))
			defer server.Close()
			chat, err := NewRemoteChat(
				&ChatConfig{
					BaseURL:   server.URL,
					ModelName: "sdk-model",
					ModelID:   "sdk-id",
					Provider:  "openai",
					APIKey:    "test",
				},
			)
			if err != nil {
				t.Fatal(err)
			}
			messages := []Message{{Role: "user", Content: "source", Images: []string{"data:image/png;base64,aGVsbG8="}}}
			ctx := types.WithLLMCallMetadata(context.Background(), "document_summary", "")
			_, err = chat.Chat(ctx, messages, &ChatOptions{})
			mu.Lock()
			defer mu.Unlock()
			want := 1
			if mode == "image_retry" {
				want = 2
			}
			if len(bodies) != want {
				t.Fatalf("HTTP sends=%d want=%d", len(bodies), want)
			}
			if (mode == "success" || mode == "image_retry") != (err == nil) {
				t.Fatalf("unexpected error: %v", err)
			}
			if mode == "image_retry" && string(bodies[0]) == string(bodies[1]) {
				t.Fatal("retry did not strip images")
			}
		})
	}
}

func TestGeminiRawHTTPChatSendsOnce(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(
			[]byte(
				"{\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"summary\"}}]" +
					",\"usage\":{\"prompt_tokens\":3,\"completion_tokens\":1,\"total_tokens\":4}}",
			),
		)
	}))
	defer server.Close()
	chat, err := NewRemoteChat(
		&ChatConfig{
			BaseURL:   server.URL + "/openai",
			ModelName: "gemini",
			ModelID:   "gemini-id",
			Provider:  "gemini",
			APIKey:    "test",
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	ctx := types.WithLLMCallMetadata(context.Background(), "document_summary", "")
	if _, err := chat.Chat(ctx, []Message{{Role: "user", Content: "source"}}, &ChatOptions{}); err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 1 {
		t.Fatalf("HTTP sends=%d, want 1", calls.Load())
	}
}
