package service

import (
	"context"
	"errors"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"testing"
)

type failingWikiModel struct {
	templateCaptureChatModel
	failure error
	calls   int
}

func (m *failingWikiModel) Chat(context.Context, []chat.Message, *chat.ChatOptions) (*types.ChatResponse, error) {
	m.calls++
	return nil, m.failure
}

// Provider text cannot establish whether a request was sent or processed.
// None of these errors may trigger wrapper/SDK replay.
func TestWikiModelErrorsDoNotAuthorizeAutomaticReplay(t *testing.T) {
	for _, msg := range []string{"status 504", "status 429", "status 401", "connection reset", "unexpected EOF", "context deadline exceeded"} {
		t.Run(msg, func(t *testing.T) {
			model := &failingWikiModel{failure: errors.New(msg)}
			_, err := (&wikiIngestService{}).generateWithTemplate(context.Background(), model, "input", nil)
			if model.calls != 1 || wikiFailureOutcome(err) != wikiOutcomeUnknown {
				t.Fatalf("calls=%d err=%v", model.calls, err)
			}
		})
	}
}

func TestWikiCancelledBeforeDispatchIsNotRun(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	model := &failingWikiModel{}
	_, err := (&wikiIngestService{}).generateWithTemplate(ctx, model, "input", nil)
	if model.calls != 0 || wikiFailureOutcome(err) != wikiOutcomeNotRun {
		t.Fatalf("calls=%d err=%v", model.calls, err)
	}
}

// TestIsTransientLLMError_RateLimit403 covers gateways that report QPM/QPS
// throttling as HTTP 403 with a rate-limit body instead of 429 (e.g. a MaaS
// gateway returning code 0x04030020, "调用频率（qpm）超限"). These carry the
// provider-embedded response body "API request failed with status 403: {...}",
// and only body-rated limit wording classifies them as transient — a plain
// authorization 403 must stay permanent.
func TestIsTransientLLMError_RateLimit403(t *testing.T) {
	ctx := context.Background()
	cases := []struct {
		name string
		msg  string
		want bool
	}{
		{"qpm gateway", `API request failed with status 403: {"code":"0x04030020","message":"调用频率（qpm）超限"}`, true},
		{"qps gateway", `API request failed with status 403: {"message":"qps exceeded"}`, true},
		{"rate limit", "API request failed with status 403: rate limit reached", true},
		{"too many requests", "API request failed with status 403: too many requests", true},
		{"throttled", "API request failed with status 403: request throttled", true},
		{"chinese frequency", "API request failed with status 403: 请求过于频繁，请稍后重试", true},
		{"busy", "API request failed with status 403: 服务繁忙", true},
		{"try again later", "API request failed with status 403: please try again later", true},
		{"slow down", "API request failed with status 403: slow down your requests", true},
		// Authorization-shaped 403s stay permanent.
		{"unauthorized", "API request failed with status 403: invalid api key", false},
		{"forbidden", "API request failed with status 403: forbidden", false},
		{"permission denied", "API request failed with status 403: permission denied", false},
		{"quota exhausted", "API request failed with status 403: forbidden (quota exhausted)", false},
		{"unknown body", `API request failed with status 403: {"error":"something else"}`, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := isTransientLLMError(ctx, errors.New(tc.msg)); got != tc.want {
				t.Errorf("isTransientLLMError(%q) = %v, want %v", tc.msg, got, tc.want)
			}
		})
	}
}
