package embedding

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/api"
	"github.com/Tencent/WeKnora/internal/models/api/openaiembeddings"
	"github.com/Tencent/WeKnora/internal/types"
)

type noRetryEmbeddingTransport struct {
	calls int
	err   error
	body  string
}

func (r *noRetryEmbeddingTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	r.calls++
	if r.err != nil {
		return nil, r.err
	}
	return &http.Response{
		StatusCode: http.StatusOK,
		Status:     "200 OK",
		Body:       io.NopCloser(strings.NewReader(r.body)),
		Header:     make(http.Header),
		Request:    req,
	}, nil
}

func TestOpenAIEmbeddingExplicitPolicyDisablesTransportRetry(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	failure := errors.New("fixture connection reset")
	for _, disabled := range []bool{true, false} {
		t.Run(fmt.Sprint(disabled), func(t *testing.T) {
			transport := &noRetryEmbeddingTransport{err: failure}
			e := retryTestEmbedder(transport, 1)
			ctx := context.Background()
			if disabled {
				ctx = types.WithModelAutomaticRetryDisabled(ctx)
			}
			_, err := e.BatchEmbed(ctx, []string{"input"})
			want := 2
			if disabled {
				want = 1
			}
			if transport.calls != want {
				t.Fatalf("transport=%d, want %d", transport.calls, want)
			}
			if !errors.Is(err, failure) {
				t.Fatalf("lost original transport error: %v", err)
			}
		})
	}
}

func TestOpenAIEmbeddingExplicitPolicyDisablesEmptyResultReplay(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, disabled := range []bool{true, false} {
		for _, empty := range []bool{true, false} {
			t.Run(fmt.Sprintf("disabled=%v/empty=%v", disabled, empty), func(t *testing.T) {
				body := `{"data":[{"embedding":[0.1],"index":0}]}`
				if empty {
					body = `{"data":[]}`
				}
				var calls atomic.Int32
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
					calls.Add(1)
					w.Header().Set("Content-Type", "application/json")
					_, _ = w.Write([]byte(body))
				}))
				defer server.Close()
				e := &protocolEmbedder{inner: openaiembeddings.New(openaiembeddings.Config{
					Endpoint: api.Endpoint{BaseURL: server.URL, Model: "fixture", Client: server.Client()},
					Retry:    api.RetryPolicy{MaxRetries: 3},
				})}
				ctx := context.Background()
				if disabled {
					ctx = types.WithModelAutomaticRetryDisabled(ctx)
				}
				got, err := e.Embed(ctx, "input")
				want := 1
				// The upstream protocol now rejects empty/mismatched vectors without replay.
				if int(calls.Load()) != want {
					t.Fatalf("HTTP sends=%d, want %d", calls.Load(), want)
				}
				if empty {
					if err == nil {
						t.Fatalf("empty result must stay explicit error: %v", err)
					}
				} else if err != nil || len(got) != 1 {
					t.Fatalf("successful embedding changed: %v %v", got, err)
				}
			})
		}
	}
}

func retryTestEmbedder(transport http.RoundTripper, retries int) *protocolEmbedder {
	return &protocolEmbedder{inner: openaiembeddings.New(openaiembeddings.Config{
		Endpoint: api.Endpoint{
			BaseURL: "https://127.0.0.1/v1",
			Model:   "fixture",
			Client:  &http.Client{Transport: transport},
		},
		Retry: api.RetryPolicy{MaxRetries: retries},
	})}
}

func TestOpenAIEmbedderHTTPTransportRetryAndPolicy(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, disabled := range []bool{false, true} {
		t.Run(fmt.Sprint(disabled), func(t *testing.T) {
			var calls atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				n := calls.Add(1)
				_, _ = io.Copy(io.Discard, r.Body)
				if n == 1 {
					conn, _, err := w.(http.Hijacker).Hijack()
					if err == nil {
						_ = conn.Close()
					}
					return
				}
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(`{"data":[{"embedding":[0.1,0.2],"index":0}]}`))
			}))
			defer server.Close()
			embedder, err := newRemoteEmbedder(Config{
				BaseURL: server.URL, Provider: "openai", ModelName: "qwen", ModelID: "qwen-id",
				Dimensions: 2, APIKey: "key",
			}, nil)
			if err != nil {
				t.Fatal(err)
			}
			embedder.(*protocolEmbedder).inner = openaiembeddings.New(openaiembeddings.Config{
				Endpoint: api.Endpoint{BaseURL: server.URL, Model: "qwen", ModelID: "qwen-id", Client: server.Client()},
				Retry:    api.RetryPolicy{MaxRetries: 1},
			})
			ctx := types.WithLLMCallMetadata(context.Background(), "document_embedding", "")
			if disabled {
				ctx = types.WithModelAutomaticRetryDisabled(ctx)
			}
			got, err := embedder.BatchEmbed(ctx, []string{"real input"})
			if disabled {
				var transportErr *api.TransportError
				if !errors.As(err, &transportErr) || calls.Load() != 1 {
					t.Fatalf("disabled retry: HTTP sends=%d err=%v", calls.Load(), err)
				}
			} else if err != nil || calls.Load() != 2 || len(got) != 1 || len(got[0]) != 2 {
				t.Fatalf("retry result: HTTP sends=%d vectors=%v err=%v", calls.Load(), got, err)
			}
		})
	}
}
