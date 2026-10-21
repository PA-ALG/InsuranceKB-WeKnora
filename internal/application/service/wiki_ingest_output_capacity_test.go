package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"strings"
	"syscall"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/api"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/sirupsen/logrus"
	logtest "github.com/sirupsen/logrus/hooks/test"
	"github.com/stretchr/testify/require"
)

type optionCapacityChat struct {
	templateCaptureChatModel
	capacity int
	check    func(context.Context, *chat.ChatOptions)
}

func (m *optionCapacityChat) MaxOutputTokens() int { return m.capacity }
func (m *optionCapacityChat) Chat(
	ctx context.Context, _ []chat.Message, opts *chat.ChatOptions,
) (*types.ChatResponse, error) {
	m.check(ctx, opts)
	return &types.ChatResponse{Content: "{}", FinishReason: "stop"}, nil
}

func TestWikiOutputCapacityThresholdAndPurposeIsolation(t *testing.T) {
	for _, capacity := range []int{0, 40000, 65535, 65536, 65537} {
		for _, prompt := range []string{
			agent.WikiCandidateSlugPrompt, agent.WikiChunkCitationPrompt, agent.WikiSummaryPrompt,
			agent.WikiPageModifyUserPrompt, agent.WikiKnowledgeExtractPrompt, agent.WikiTaxonomyPlanPrompt,
			agent.WikiDeduplicationPrompt, agent.WikiIndexIntroPrompt, agent.WikiIndexIntroUpdatePrompt, "other prompt",
		} {
			purpose := wikiPromptPurpose(prompt)
			t.Run(fmt.Sprintf("%d/%s", capacity, purpose), func(t *testing.T) {
				calls := 0
				check := func(ctx context.Context, opts *chat.ChatOptions) {
					calls++
					gotPurpose, _ := types.LLMCallMetadataFromContext(ctx)
					require.Equal(t, purpose, gotPurpose)
					want := 32768
					if capacity >= 65536 && (purpose == "wiki_candidate_slug" || purpose == "wiki_chunk_citation") {
						want = 65536
					}
					require.Equal(t, want, opts.MaxTokens)
					require.Equal(t, 0.3, opts.Temperature)
					require.NotNil(t, opts.Thinking)
					require.False(t, *opts.Thinking)
					require.True(t, types.ModelAutomaticRetryDisabled(ctx))
				}
				model := &optionCapacityChat{capacity: capacity, check: check}
				_, err := (&wikiIngestService{}).generateWithTemplate(context.Background(), model, prompt, nil)
				require.NoError(t, err)
				require.Equal(t, 1, calls)
			})
		}
	}
}

type privateTimeoutError struct{}

func (privateTimeoutError) Error() string   { return "PRIVATE-ERROR-TEXT" }
func (privateTimeoutError) Timeout() bool   { return true }
func (privateTimeoutError) Temporary() bool { return true }

func wikiWarningContext() (context.Context, *logtest.Hook) {
	log := logrus.New()
	log.SetOutput(io.Discard)
	hook := logtest.NewLocal(log)
	return context.WithValue(context.Background(), types.LoggerContextKey, logrus.NewEntry(log)), hook
}

func TestWikiTransportWarningReportsOnlySafeDetail(t *testing.T) {
	closed := &net.OpError{Op: "PRIVATE-OP", Net: "tcp", Err: syscall.ECONNRESET}
	for _, tc := range []struct {
		name   string
		cause  error
		detail string
	}{
		{"http", &api.HTTPError{StatusCode: 503, Body: "PRIVATE-BODY"}, "http 503"},
		{"timeout", privateTimeoutError{}, "timeout"},
		{"eof", io.EOF, "connection closed"},
		{"unexpected eof", io.ErrUnexpectedEOF, "connection closed"},
		{"reset", closed, "connection closed"},
		{"pipe", syscall.EPIPE, "connection closed"},
		{"other", errors.New("PRIVATE-ERROR-TEXT"), "other"},
		{"nil response", nil, "other"},
		{"http precedence", errors.Join(privateTimeoutError{},
			&api.HTTPError{StatusCode: 429, Body: "PRIVATE-BODY"}), "http 429"},
		{"timeout in later branch", errors.Join(closed, privateTimeoutError{}), "timeout"},
		{"closed in later branch", errors.Join(errors.New("PRIVATE-ERROR-TEXT"), io.EOF), "connection closed"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ctx, hook := wikiWarningContext()
			cause := tc.cause
			if cause != nil {
				cause = &api.TransportError{Op: "PRIVATE-OP", Err: &url.Error{
					Op: "POST", URL: "https://example.invalid/PRIVATE-URL",
					Err: fmt.Errorf("PRIVATE-WRAPPER: %w", cause),
				}}
			}
			calls := 0
			model := &windowChat{answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
				calls++
				return nil, cause
			}}
			_, err := (&wikiIngestService{}).generateWithTemplate(ctx, model, agent.WikiChunkCitationPrompt,
				map[string]string{"ChunksXML": "PRIVATE-REQUEST", "CandidatesText": "PRIVATE-CANDIDATE"})
			require.Equal(t, wikiOutcomeUnknown, wikiFailureOutcome(err))
			require.Equal(t, 1, calls)
			want := "wiki ingest: call failed stage=wiki_chunk_citation outcome=OUTCOME_UNKNOWN " +
				"cause=transport error detail=" + tc.detail
			warnings := 0
			for _, entry := range hook.AllEntries() {
				require.NotContains(t, entry.Message, "PRIVATE-")
				require.NotContains(t, fmt.Sprint(entry.Data), "PRIVATE-")
				if strings.Contains(entry.Message, "wiki ingest: call failed") {
					warnings++
					require.Equal(t, logrus.WarnLevel, entry.Level)
					require.Equal(t, want, entry.Message)
				}
			}
			require.Equal(t, 1, warnings)
		})
	}
}

func TestWikiNonTransportWarningKeepsItsExistingFormat(t *testing.T) {
	for _, tc := range []struct {
		name, outcome, category string
		cause                   error
	}{
		{"deadline", wikiOutcomeUnknown, "deadline exceeded", context.DeadlineExceeded},
		{"cancelled", wikiOutcomeNotRun, "context canceled", context.Canceled},
		{"generation", wikiOutcomeFailed, "generation failure", errors.New("PRIVATE-ERROR-TEXT")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ctx, hook := wikiWarningContext()
			_, err := (&wikiIngestService{}).runWikiRequest(ctx, "unused", false, "wiki_candidate_slug",
				func(context.Context, *wikiLLMRequest) (wikiTemplateResult, error) {
					return wikiTemplateResult{}, &wikiStageFailure{
						Stage: "wiki_candidate_slug", Outcome: tc.outcome, Cause: tc.cause,
					}
				})
			require.Error(t, err)
			entries := hook.AllEntries()
			require.Len(t, entries, 1)
			want := "wiki ingest: call failed stage=wiki_candidate_slug outcome=" + tc.outcome + " cause=" + tc.category
			require.Equal(t, want, entries[0].Message)
		})
	}
}
