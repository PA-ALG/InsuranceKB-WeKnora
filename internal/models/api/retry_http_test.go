package api

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

// Preserve the request-count assertions formerly coupled to the dispatch journal.
func TestEndpointHTTPRetryPolicy(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, mode := range []string{"success", "http_error", "server_error", "transport_error"} {
		for _, disabled := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/disabled=%v", mode, disabled), func(t *testing.T) {
				var calls atomic.Int32
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					calls.Add(1)
					_, _ = io.Copy(io.Discard, r.Body)
					switch mode {
					case "transport_error":
						conn, _, err := w.(http.Hijacker).Hijack()
						if err == nil {
							_ = conn.Close()
						}
						return
					case "http_error":
						w.WriteHeader(http.StatusBadRequest)
					case "server_error":
						w.WriteHeader(http.StatusInternalServerError)
					}
					_, _ = w.Write([]byte(`{}`))
				}))
				defer server.Close()
				ep := Endpoint{BaseURL: server.URL, Client: server.Client()}
				ctx := context.Background()
				if disabled {
					ctx = types.WithModelAutomaticRetryDisabled(ctx)
				}
				err := ep.PostJSONWithRetry(ctx, ep.Resolve("/embeddings"),
					map[string]string{"input": "source"}, nil, RetryPolicy{MaxRetries: 1}, "embedding")
				want := int32(1)
				if mode == "transport_error" && !disabled {
					want = 2
				}
				if calls.Load() != want || (err == nil) != (mode == "success") {
					t.Fatalf("HTTP sends=%d want=%d err=%v", calls.Load(), want, err)
				}
				if mode == "transport_error" {
					var transportErr *TransportError
					if !errors.As(err, &transportErr) || transportErr.Op != "send request" {
						t.Fatalf("transport failure lost: %v", err)
					}
				}
				if mode == "http_error" || mode == "server_error" {
					wantStatus := http.StatusBadRequest
					if mode == "server_error" {
						wantStatus = http.StatusInternalServerError
					}
					var httpErr *HTTPError
					if !errors.As(err, &httpErr) || httpErr.StatusCode != wantStatus {
						t.Fatalf("HTTP failure lost: %v", err)
					}
				}
			})
		}
	}
}

func TestEndpointHTTPRedirectPolicyDoesNotMutateClient(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	for _, status := range []int{http.StatusTemporaryRedirect, http.StatusPermanentRedirect} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			var calls atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				_, _ = io.Copy(io.Discard, r.Body)
				if r.URL.Path == "/chat" {
					w.Header().Set("Location", "/redirected")
					w.WriteHeader(status)
					return
				}
				_, _ = w.Write([]byte(`{}`))
			}))
			defer server.Close()
			client := server.Client()
			redirectChecks := 0
			client.CheckRedirect = func(*http.Request, []*http.Request) error {
				redirectChecks++
				return nil
			}
			ep := Endpoint{BaseURL: server.URL, Client: client}
			ctx := types.WithModelAutomaticRetryDisabled(context.Background())
			err := ep.PostJSON(ctx, ep.Resolve("/chat"), map[string]string{"input": "source"}, nil)
			var httpErr *HTTPError
			if !errors.As(err, &httpErr) || httpErr.StatusCode != status || calls.Load() != 1 || redirectChecks != 0 {
				t.Fatalf("disabled redirect: sends=%d checks=%d err=%v", calls.Load(), redirectChecks, err)
			}
			// The same client's ordinary policy must still follow the redirect.
			err = ep.PostJSON(context.Background(), ep.Resolve("/chat"), map[string]string{"input": "source"}, nil)
			if err != nil || calls.Load() != 3 || redirectChecks != 1 {
				t.Fatalf("ordinary redirect: sends=%d checks=%d err=%v", calls.Load(), redirectChecks, err)
			}
		})
	}
}
