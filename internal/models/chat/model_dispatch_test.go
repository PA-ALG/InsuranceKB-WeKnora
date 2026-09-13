package chat

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

type chatDispatchRecorderStub struct {
	specs   []types.ModelDispatchSpec
	results []types.ModelDispatchResult
}

func (r *chatDispatchRecorderStub) ReserveModelDispatch(
	_ context.Context, spec types.ModelDispatchSpec,
) (types.ModelDispatchReservation, error) {
	r.specs = append(r.specs, spec)
	return &chatDispatchReservationStub{parent: r}, nil
}

type chatDispatchReservationStub struct {
	parent *chatDispatchRecorderStub
}

func (*chatDispatchReservationStub) MarkDispatching(context.Context) error { return nil }
func (r *chatDispatchReservationStub) RecordModelDispatch(
	_ context.Context, result types.ModelDispatchResult,
) error {
	r.parent.results = append(r.parent.results, result)
	return nil
}

func TestGeminiRawHTTPChatJournalsTheRealDispatch(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"summary"}}],"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}`))
	}))
	defer server.Close()
	previous := rawHTTPClient
	rawHTTPClient = server.Client()
	defer func() { rawHTTPClient = previous }()

	chat := newTestRemoteChat(t)
	chat.baseURL = server.URL
	chat.modelID = "gemini-id"
	chat.modelName = "gemini"
	chat.adapter = geminiProvider{}
	recorder := &chatDispatchRecorderStub{}
	ctx := types.WithModelDispatchRecorder(context.Background(), recorder)
	ctx = types.WithLLMCallMetadata(ctx, "document_summary", "")
	if _, err := chat.Chat(ctx, []Message{{Role: "user", Content: "source"}}, &ChatOptions{}); err != nil {
		t.Fatal(err)
	}
	if len(recorder.specs) != 1 || len(recorder.results) != 1 ||
		recorder.specs[0].Operation != "document_summary" ||
		recorder.results[0].Outcome != "HTTP_RESPONSE" || recorder.results[0].HTTPStatus != 200 {
		t.Fatalf("unexpected dispatch audit: specs=%#v results=%#v", recorder.specs, recorder.results)
	}
}
