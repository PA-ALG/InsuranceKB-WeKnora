package embedding

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

type embeddingDispatchRecorderStub struct {
	mu           sync.Mutex
	specs        []types.ModelDispatchSpec
	results      []types.ModelDispatchResult
	reserveError error
}

func (r *embeddingDispatchRecorderStub) ReserveModelDispatch(
	_ context.Context, spec types.ModelDispatchSpec,
) (types.ModelDispatchReservation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.reserveError != nil {
		return nil, r.reserveError
	}
	r.specs = append(r.specs, spec)
	return &embeddingDispatchReservationStub{parent: r}, nil
}

type embeddingDispatchReservationStub struct {
	parent      *embeddingDispatchRecorderStub
	dispatching bool
}

func (r *embeddingDispatchReservationStub) MarkDispatching(context.Context) error {
	r.dispatching = true
	return nil
}

func (r *embeddingDispatchReservationStub) RecordModelDispatch(
	_ context.Context, result types.ModelDispatchResult,
) error {
	if !r.dispatching {
		return errors.New("not dispatching")
	}
	r.parent.mu.Lock()
	defer r.parent.mu.Unlock()
	r.parent.results = append(r.parent.results, result)
	return nil
}

type failFirstEmbeddingTransport struct {
	calls int
	next  http.RoundTripper
}

func (t *failFirstEmbeddingTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	t.calls++
	if t.calls == 1 {
		return nil, errors.New("fixture connection reset")
	}
	return t.next.RoundTrip(req)
}

func TestOpenAIEmbedderJournalsEveryRealTransportRetry(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":[{"embedding":[0.1,0.2],"index":0}]}`))
	}))
	defer server.Close()
	embedder, err := NewOpenAIEmbedder("key", server.URL, "qwen", 511, 2, "qwen-id", nil)
	if err != nil {
		t.Fatal(err)
	}
	transport := &failFirstEmbeddingTransport{next: http.DefaultTransport}
	embedder.httpClient = &http.Client{Transport: transport}
	embedder.maxRetries = 1
	recorder := &embeddingDispatchRecorderStub{}
	ctx := types.WithModelDispatchRecorder(context.Background(), recorder)
	ctx = types.WithLLMCallMetadata(ctx, "document_embedding", "")
	if _, err := embedder.BatchEmbed(ctx, []string{"real input"}); err != nil {
		t.Fatal(err)
	}
	if len(recorder.specs) != 2 || len(recorder.results) != 2 || transport.calls != 2 {
		t.Fatalf("specs=%d results=%d transport=%d, want 2 each", len(recorder.specs), len(recorder.results), transport.calls)
	}
	if recorder.specs[0].TransportRetryIndex != 0 || recorder.specs[1].TransportRetryIndex != 1 ||
		recorder.results[0].Outcome != "TRANSPORT_ERROR" || recorder.results[1].HTTPStatus != http.StatusOK {
		t.Fatalf("unexpected dispatch audit: specs=%#v results=%#v", recorder.specs, recorder.results)
	}
}

func TestOpenAIEmbedderJournalFailurePreventsProviderDispatch(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls++
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()
	embedder, err := NewOpenAIEmbedder("key", server.URL, "qwen", 511, 2, "qwen-id", nil)
	if err != nil {
		t.Fatal(err)
	}
	recorder := &embeddingDispatchRecorderStub{reserveError: types.ErrModelDispatchJournalUnavailable}
	ctx := types.WithModelDispatchRecorder(context.Background(), recorder)
	ctx = types.WithLLMCallMetadata(ctx, "document_embedding", "")
	if _, err := embedder.BatchEmbed(ctx, []string{"input"}); !errors.Is(err, types.ErrModelDispatchJournalUnavailable) {
		t.Fatalf("BatchEmbed error = %v", err)
	}
	if calls != 0 {
		t.Fatalf("provider received %d calls after journal failure", calls)
	}
}

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
	return &http.Response{StatusCode: http.StatusOK, Status: "200 OK", Body: io.NopCloser(strings.NewReader(r.body)), Header: make(http.Header), Request: req}, nil
}

func TestOpenAIEmbeddingExplicitPolicyDisablesTransportRetry(t *testing.T) {
	failure := errors.New("fixture connection reset")
	for _, disabled := range []bool{true, false} {
		t.Run(fmt.Sprint(disabled), func(t *testing.T) {
			transport := &noRetryEmbeddingTransport{err: failure}
			e := &OpenAIEmbedder{baseURL: "https://embedding.invalid/v1", modelName: "fixture", httpClient: &http.Client{Transport: transport}, maxRetries: 1}
			recorder := &embeddingDispatchRecorderStub{}
			ctx := types.WithModelDispatchRecorder(context.Background(), recorder)
			if disabled {
				ctx = types.WithModelAutomaticRetryDisabled(ctx)
			}
			_, err := e.BatchEmbed(ctx, []string{"input"})
			want := 2
			if disabled {
				want = 1
			}
			if transport.calls != want || len(recorder.specs) != want || len(recorder.results) != want {
				t.Fatalf("transport=%d reservations=%d results=%d, want %d", transport.calls, len(recorder.specs), len(recorder.results), want)
			}
			if !errors.Is(err, failure) {
				t.Fatalf("lost original transport error: %v", err)
			}
			for i, spec := range recorder.specs {
				if spec.TransportRetryIndex != i || recorder.results[i].Outcome != "TRANSPORT_ERROR" {
					t.Fatalf("invalid transport audit: %#v %#v", recorder.specs, recorder.results)
				}
			}
		})
	}
}

func TestOpenAIEmbeddingExplicitPolicyDisablesEmptyResultReplay(t *testing.T) {
	for _, disabled := range []bool{true, false} {
		for _, empty := range []bool{true, false} {
			t.Run(fmt.Sprintf("disabled=%v/empty=%v", disabled, empty), func(t *testing.T) {
				body := `{"data":[{"embedding":[0.1],"index":0}]}`
				if empty {
					body = `{"data":[]}`
				}
				transport := &noRetryEmbeddingTransport{body: body}
				e := &OpenAIEmbedder{baseURL: "https://embedding.invalid/v1", modelName: "fixture", httpClient: &http.Client{Transport: transport}, maxRetries: 3}
				ctx := context.Background()
				if disabled {
					ctx = types.WithModelAutomaticRetryDisabled(ctx)
				}
				got, err := e.Embed(ctx, "input")
				want := 1
				if empty && !disabled {
					want = 3
				}
				if transport.calls != want {
					t.Fatalf("dispatches=%d, want %d", transport.calls, want)
				}
				if empty {
					if err == nil || err.Error() != "no embedding returned" {
						t.Fatalf("empty result must stay explicit error: %v", err)
					}
				} else if err != nil || len(got) != 1 {
					t.Fatalf("successful embedding changed: %v %v", got, err)
				}
			})
		}
	}
}
