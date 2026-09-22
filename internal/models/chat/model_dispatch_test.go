package chat

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

type chatDispatchRecorderStub struct {
	specs      []types.ModelDispatchSpec
	results    []types.ModelDispatchResult
	reserveErr error
	markErr    error
	recordErr  error
}

func (r *chatDispatchRecorderStub) ReserveModelDispatch(
	_ context.Context, spec types.ModelDispatchSpec,
) (types.ModelDispatchReservation, error) {
	r.specs = append(r.specs, spec)
	if r.reserveErr != nil {
		return nil, r.reserveErr
	}
	return &chatDispatchReservationStub{parent: r}, nil
}

type chatDispatchReservationStub struct {
	parent *chatDispatchRecorderStub
}

func (r *chatDispatchReservationStub) MarkDispatching(context.Context) error { return r.parent.markErr }
func (r *chatDispatchReservationStub) RecordModelDispatch(
	_ context.Context, result types.ModelDispatchResult,
) error {
	r.parent.results = append(r.parent.results, result)
	return r.parent.recordErr
}

func TestStandardSDKChatJournalsEachHTTPDispatch(t *testing.T) {
	for _, mode := range []string{"success", "http_error", "transport_error", "image_retry", "reserve_error", "mark_error", "record_error"} {
		t.Run(mode, func(t *testing.T) {
			t.Setenv("SSRF_WHITELIST", "127.0.0.1")
			var bodies [][]byte
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
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
				if mode == "http_error" || mode == "record_error" || (mode == "image_retry" && len(bodies) == 1) {
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
			chat, err := NewRemoteAPIChat(&ChatConfig{BaseURL: server.URL, ModelName: "sdk-model", ModelID: "sdk-id", Provider: "openai", APIKey: "test"})
			if err != nil {
				t.Fatal(err)
			}
			messages := []Message{{Role: "user", Content: "source", Images: []string{"data:image/png;base64,aGVsbG8="}}}
			_, _, raw, err := chat.buildOutbound(messages, &ChatOptions{}, false)
			if err != nil || raw {
				t.Fatalf("not standard SDK branch: %v %v", raw, err)
			}
			recorder := &chatDispatchRecorderStub{}
			failure := errors.New("image unsupported journal")
			switch mode {
			case "reserve_error":
				recorder.reserveErr = failure
			case "mark_error":
				recorder.markErr = failure
			case "record_error":
				recorder.recordErr = failure
			}
			ctx := types.WithLLMCallMetadata(types.WithModelDispatchRecorder(context.Background(), recorder), "document_summary", "")
			_, err = chat.Chat(ctx, messages, &ChatOptions{})
			want := 1
			if mode == "image_retry" {
				want = 2
			}
			if mode == "reserve_error" || mode == "mark_error" {
				want = 0
			}
			if len(bodies) != want {
				t.Fatalf("HTTP sends=%d want=%d", len(bodies), want)
			}
			journalFailure := mode == "reserve_error" || mode == "mark_error" || mode == "record_error"
			if journalFailure && !errors.Is(err, types.ErrModelDispatchJournalUnavailable) {
				t.Fatalf("journal failure not preserved: %v", err)
			}
			if (mode == "success" || mode == "image_retry") != (err == nil) {
				t.Fatalf("unexpected error: %v", err)
			}
			if len(recorder.results) != want {
				t.Fatalf("missing dispatch records: %#v", recorder.results)
			}
			for i, body := range bodies {
				spec := recorder.specs[i]
				if spec.RequestSHA256 != fmt.Sprintf("%x", sha256.Sum256(body)) || spec.TransportRetryIndex != i || spec.Operation != "document_summary" || spec.Purpose != "document_summary" || spec.ModelID != "sdk-id" || spec.ModelName != "sdk-model" {
					t.Fatalf("wrong dispatch spec: %#v", spec)
				}
				wantStatus, wantOutcome := 200, "HTTP_RESPONSE"
				if mode == "transport_error" {
					wantStatus, wantOutcome = 0, "TRANSPORT_ERROR"
				} else if mode == "http_error" || mode == "record_error" || (mode == "image_retry" && i == 0) {
					wantStatus = 400
				}
				if recorder.results[i].HTTPStatus != wantStatus || recorder.results[i].Outcome != wantOutcome {
					t.Fatalf("wrong result: %#v", recorder.results[i])
				}
			}
			if mode == "image_retry" && string(bodies[0]) == string(bodies[1]) {
				t.Fatal("retry did not strip images")
			}
		})
	}
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
