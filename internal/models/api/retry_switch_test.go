package api

// S7e-1 acceptance (protected, written by Claude): the automatic-retry switch keeps its behaviour
// once the dispatch journal is removed (Spec docs/design/slices/S7e-1-清理旧830残留代码.md §3 items
// 7–8). These tests describe current behaviour and pass before and after the removal.

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

// switchTransport counts sends; it fails every send, or answers the first one with a redirect.
type switchTransport struct {
	calls    int
	fail     error
	redirect bool
}

func (s *switchTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	s.calls++
	if r.Body != nil {
		_, _ = io.Copy(io.Discard, r.Body)
		_ = r.Body.Close()
	}
	if s.fail != nil {
		return nil, s.fail
	}
	if s.redirect && s.calls == 1 {
		return &http.Response{
			StatusCode: http.StatusTemporaryRedirect,
			Header:     http.Header{"Location": []string{"https://127.0.0.1/moved"}},
			Body:       io.NopCloser(strings.NewReader("")),
			Request:    r,
		}, nil
	}
	return &http.Response{
		StatusCode: http.StatusOK,
		Header:     http.Header{"Content-Type": []string{"application/json"}},
		Body:       io.NopCloser(strings.NewReader(`{}`)),
		Request:    r,
	}, nil
}

func switchEndpoint(tr *switchTransport) Endpoint {
	return Endpoint{
		BaseURL: "https://127.0.0.1",
		Model:   "remote",
		ModelID: "row",
		Client:  &http.Client{Transport: tr},
	}
}

func switchBody() map[string]any {
	return map[string]any{"input": []string{"text"}}
}

func TestRetrySwitchSendsOnceWhenDisabled(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	tr := &switchTransport{fail: errors.New("connection reset")}
	ep := switchEndpoint(tr)
	ctx := types.WithModelAutomaticRetryDisabled(context.Background())
	err := ep.PostJSONWithRetry(ctx, ep.Resolve("/embeddings"), switchBody(), nil, RetryPolicy{MaxRetries: 2}, "s7e")
	var transport *TransportError
	if !errors.As(err, &transport) || tr.calls != 1 {
		t.Fatalf("disabled retry: calls=%d err=%v", tr.calls, err)
	}
}

func TestRetrySwitchRetriesTransportFailuresWhenEnabled(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	tr := &switchTransport{fail: errors.New("connection reset")}
	ep := switchEndpoint(tr)
	err := ep.PostJSONWithRetry(
		context.Background(), ep.Resolve("/embeddings"), switchBody(), nil, RetryPolicy{MaxRetries: 2}, "s7e",
	)
	var transport *TransportError
	if !errors.As(err, &transport) || tr.calls != 3 {
		t.Fatalf("enabled retry: calls=%d err=%v", tr.calls, err)
	}
}

func TestRetrySwitchDoesNotFollowRedirectsWhenDisabled(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	tr := &switchTransport{redirect: true}
	ep := switchEndpoint(tr)
	ctx := types.WithModelAutomaticRetryDisabled(context.Background())
	err := ep.PostJSON(ctx, ep.Resolve("/embeddings"), switchBody(), nil)
	var httpErr *HTTPError
	if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusTemporaryRedirect || tr.calls != 1 {
		t.Fatalf("redirect replayed the body: calls=%d err=%v", tr.calls, err)
	}
}

func TestRedirectsAreFollowedWhenRetryIsEnabled(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	tr := &switchTransport{redirect: true}
	ep := switchEndpoint(tr)
	err := ep.PostJSON(context.Background(), ep.Resolve("/embeddings"), switchBody(), nil)
	if err != nil || tr.calls != 2 {
		t.Fatalf("redirect not followed: calls=%d err=%v", tr.calls, err)
	}
}
