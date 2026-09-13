package embedding

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
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
