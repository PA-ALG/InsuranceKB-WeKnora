package service

import (
	"context"
	"errors"
	"io"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

type windowChat struct {
	templateCaptureChatModel
	answer func(context.Context, []chat.Message) (*types.ChatResponse, error)
}

func (m *windowChat) Chat(
	ctx context.Context, messages []chat.Message, _ *chat.ChatOptions,
) (*types.ChatResponse, error) {
	return m.answer(ctx, messages)
}

func TestWindowOutputTruncationRejectsEveryBody(t *testing.T) {
	for _, prompt := range []string{agent.WikiCandidateSlugPrompt, agent.WikiChunkCitationPrompt} {
		for _, body := range []string{`{"entities":[],"concepts":[]}`, `{"entities":[`, ""} {
			t.Run(wikiPromptPurpose(prompt)+"/"+body, func(t *testing.T) {
				calls := 0
				model := &windowChat{answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
					calls++
					return &types.ChatResponse{Content: body, FinishReason: "length"}, nil
				}}
				_, err := (&wikiIngestService{}).generateWithTemplate(context.Background(), model, prompt, nil)
				var stage *wikiStageFailure
				if !errors.As(err, &stage) || stage.Stage != wikiPromptPurpose(prompt) ||
					stage.Outcome != wikiOutcomeFailed ||
					!errors.Is(err, errWikiOutputTruncated) ||
					calls != 1 {
					t.Fatalf("calls=%d stage=%+v err=%v", calls, stage, err)
				}
			})
		}
	}
}

func TestWindowOutputOtherStopsAndUnknownRemainUnchanged(t *testing.T) {
	for _, reason := range []string{"stop", "max_tokens", "max_output_tokens", "Length", " length "} {
		model := &windowChat{answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
			return &types.ChatResponse{Content: "{}", FinishReason: reason}, nil
		}}
		got, err := (&wikiIngestService{}).generateWithTemplate(
			context.Background(), model, agent.WikiCandidateSlugPrompt, nil,
		)
		if err != nil || got != "{}" {
			t.Fatalf("reason=%q got=%q err=%v", reason, got, err)
		}
	}
	for _, response := range []*types.ChatResponse{nil, {Content: "partial", FinishReason: "length"}} {
		for _, transport := range []error{nil, io.EOF} {
			if response != nil && transport == nil {
				continue
			}
			model := &windowChat{
				answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
					return response, transport
				},
			}
			_, err := (&wikiIngestService{}).generateWithTemplate(
				context.Background(), model, agent.WikiChunkCitationPrompt, nil,
			)
			if wikiFailureOutcome(err) != wikiOutcomeUnknown || errors.Is(err, errWikiOutputTruncated) {
				t.Fatalf("err=%v", err)
			}
		}
	}
}

func TestWindowNewSlugEvidenceJoinsExistingCandidate(t *testing.T) {
	entities, _, uncited := mergeCitationsIntoItems(
		[]extractedItem{{Name: "Known", Slug: "entity/known"}}, nil,
		map[string][]string{"entity/known": {"head"}},
		[]newSlugFromCitation{{Name: "Known", Slug: "entity/known", SourceChunks: []string{"tail", "head"}}},
	)
	if len(entities) != 1 || !equalStrings(entities[0].SourceChunks, []string{"head", "tail"}) || uncited != 0 {
		t.Fatalf("items=%+v uncited=%d", entities, uncited)
	}
	entities, _, uncited = mergeCitationsIntoItems([]extractedItem{{Name: "Known", Slug: "entity/known"}}, nil, nil,
		[]newSlugFromCitation{{Name: "Known", Slug: "entity/known", SourceChunks: []string{"tail"}}})
	if !equalStrings(entities[0].SourceChunks, []string{"tail"}) || uncited != 0 {
		t.Fatalf("items=%+v uncited=%d", entities, uncited)
	}
}
