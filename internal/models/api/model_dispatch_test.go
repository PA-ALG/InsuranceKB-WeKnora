package api

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

type dispatchRecorder struct {
	specs                          []types.ModelDispatchSpec
	results                        []types.ModelDispatchResult
	reserveErr, markErr, recordErr error
}

func (r *dispatchRecorder) ReserveModelDispatch(_ context.Context, s types.ModelDispatchSpec) (types.ModelDispatchReservation, error) {
	r.specs = append(r.specs, s)
	return r, r.reserveErr
}
func (r *dispatchRecorder) MarkDispatching(context.Context) error { return r.markErr }
func (r *dispatchRecorder) RecordModelDispatch(_ context.Context, rst types.ModelDispatchResult) error {
	r.results = append(r.results, rst)
	return r.recordErr
}

type dispatchTransport struct {
	bodies []string
	err    error
	status int
}

func (d *dispatchTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	b, _ := io.ReadAll(r.Body)
	d.bodies = append(d.bodies, string(b))
	if d.err != nil {
		return nil, d.err
	}
	return &http.Response{StatusCode: d.status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{}`)), Request: r}, nil
}

func TestUPGDispatchJournalSurvivesProtocolUpgrade(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, mode := range []string{"success", "http_error", "transport_error", "reserve_error", "mark_error", "record_error"} {
		t.Run(mode, func(t *testing.T) {
			rec := &dispatchRecorder{}
			tr := &dispatchTransport{status: 200}
			failure := errors.New("journal unavailable")
			switch mode {
			case "http_error":
				tr.status = 400
			case "transport_error":
				tr.err = errors.New("connection reset")
			case "reserve_error":
				rec.reserveErr = failure
			case "mark_error":
				rec.markErr = failure
			case "record_error":
				rec.recordErr = failure
			}
			ep := Endpoint{BaseURL: "https://127.0.0.1", DispatchOperation: "embedding", Model: "remote", ModelID: "row", Client: &http.Client{Transport: tr}}
			ctx := types.WithLLMCallMetadata(types.WithModelDispatchRecorder(context.Background(), rec), "document_embedding", "")
			err := ep.PostJSON(ctx, ep.Resolve("/embeddings"), map[string]any{"input": []string{"private source"}}, nil)
			want := 1
			if mode == "reserve_error" || mode == "mark_error" {
				want = 0
			}
			if len(tr.bodies) != want || len(rec.results) != want {
				t.Fatalf("sends=%d records=%d want=%d", len(tr.bodies), len(rec.results), want)
			}
			if (mode == "success") != (err == nil) {
				t.Fatalf("unexpected result: %v", err)
			}
			if strings.HasSuffix(mode, "_error") && (mode == "reserve_error" || mode == "mark_error" || mode == "record_error") && !errors.Is(err, types.ErrModelDispatchJournalUnavailable) {
				t.Fatalf("journal failure lost: %v", err)
			}
			if want == 0 {
				return
			}
			spec := rec.specs[0]
			if spec.ModelID != "row" || spec.ModelName != "remote" || spec.Operation != "embedding" || spec.Purpose != "document_embedding" || spec.RequestSHA256 != fmt.Sprintf("%x", sha256.Sum256([]byte(tr.bodies[0]))) {
				t.Fatalf("wrong safe identity: %#v", spec)
			}
			outcome := "HTTP_RESPONSE"
			status := tr.status
			if mode == "transport_error" {
				outcome = "TRANSPORT_ERROR"
				status = 0
			}
			if rec.results[0].Outcome != outcome || rec.results[0].HTTPStatus != status {
				t.Fatalf("wrong outcome: %#v", rec.results)
			}
		})
	}
}

func TestUPGDisabledRetryDoesNotReplayUnknownSend(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, disabled := range []bool{false, true} {
		t.Run(fmt.Sprint(disabled), func(t *testing.T) {
			rec := &dispatchRecorder{}
			tr := &dispatchTransport{err: errors.New("connection reset")}
			ep := Endpoint{BaseURL: "https://127.0.0.1", DispatchOperation: "embedding", Client: &http.Client{Transport: tr}}
			ctx := types.WithLLMCallMetadata(types.WithModelDispatchRecorder(context.Background(), rec), "document_embedding", "")
			if disabled {
				ctx = types.WithModelAutomaticRetryDisabled(ctx)
			}
			err := ep.PostJSONWithRetry(ctx, ep.Resolve("/embeddings"), map[string]string{"input": "source"}, nil, RetryPolicy{MaxRetries: 1}, "embedding")
			want := 2
			if disabled {
				want = 1
			}
			if err == nil || len(tr.bodies) != want || len(rec.results) != want {
				t.Fatalf("sends=%d records=%d want=%d err=%v", len(tr.bodies), len(rec.results), want, err)
			}
			for i, spec := range rec.specs {
				if spec.TransportRetryIndex != i {
					t.Fatalf("retry index=%d want %d", spec.TransportRetryIndex, i)
				}
			}
		})
	}
}

type redirectDispatchTransport struct {
	sends  int
	status int
}

func (d *redirectDispatchTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	d.sends++
	status := http.StatusOK
	header := make(http.Header)
	if d.sends == 1 {
		status = d.status
		header.Set("Location", "https://127.0.0.1/redirected")
	}
	return &http.Response{StatusCode: status, Header: header, Body: io.NopCloser(strings.NewReader(`{}`)), Request: r}, nil
}

func TestUPGRedirectCannotReplayGovernedModelRequest(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, status := range []int{http.StatusTemporaryRedirect, http.StatusPermanentRedirect} {
		for _, mode := range []string{"ordinary", "journal", "disabled"} {
			t.Run(fmt.Sprintf("%d/%s", status, mode), func(t *testing.T) {
				ctx := context.Background()
				recorder := &dispatchRecorder{}
				if mode == "journal" {
					ctx = types.WithModelDispatchRecorder(ctx, recorder)
				}
				if mode == "disabled" {
					ctx = types.WithModelAutomaticRetryDisabled(ctx)
				}
				transport := &redirectDispatchTransport{status: status}
				ep := Endpoint{BaseURL: "https://127.0.0.1", Client: &http.Client{Transport: transport}}
				err := ep.PostJSON(ctx, ep.Resolve("/chat"), map[string]string{"input": "source"}, nil)
				if mode == "ordinary" {
					if err != nil || transport.sends != 2 {
						t.Fatalf("ordinary redirect changed: sends=%d err=%v", transport.sends, err)
					}
					return
				}
				if err == nil || transport.sends != 1 {
					t.Fatalf("governed redirect replayed: sends=%d err=%v", transport.sends, err)
				}
				if mode == "journal" && (len(recorder.results) != 1 || recorder.results[0].HTTPStatus != status) {
					t.Fatalf("redirect result not recorded: %#v", recorder.results)
				}
			})
		}
	}
}
