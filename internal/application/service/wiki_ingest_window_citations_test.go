package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestWindowCitationCandidatesAndHandlesStayLocal(t *testing.T) {
	windows := []wikiDocumentWindow{
		{content: "HEAD source", candidates: "entity/head", chunks: []*types.Chunk{windowChunk("head", 0, "HEAD source")}},
		{content: "TAIL source", candidates: "entity/tail", chunks: []*types.Chunk{windowChunk("tail", 1, "TAIL source")}},
		{content: "EMPTY source", chunks: []*types.Chunk{windowChunk("empty", 2, "EMPTY source")}},
	}
	var chunks []*types.Chunk
	for _, w := range windows {
		chunks = append(chunks, w.chunks...)
	}
	var mu sync.Mutex
	var prompts []string
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		text := promptText(messages)
		mu.Lock()
		prompts = append(prompts, text)
		mu.Unlock()
		if strings.Contains(text, "EMPTY source") {
			return &types.ChatResponse{Content: `{"citations":{},"new_slugs":[{"slug":"entity/head","name":"Head","source_chunks":["c000"]}]}`}, nil
		}
		slug := "entity/head"
		if strings.Contains(text, "TAIL source") {
			slug = "entity/tail"
		}
		return &types.ChatResponse{Content: fmt.Sprintf(`{"citations":{%q:["c000"]},"new_slugs":[]}`, slug)}, nil
	}}
	result := (&wikiIngestService{}).classifyChunkCitations(context.Background(), model, "entity/head entity/tail", chunks, "en", wikiOutcomeBatchContext(), nil, windows)
	if result.Err() != nil || len(prompts) != 3 || len(result.BatchErrors) != 3 {
		t.Fatalf("prompts=%d result=%+v err=%v", len(prompts), result, result.Err())
	}
	for _, prompt := range prompts {
		if strings.Contains(prompt, "HEAD source") && strings.Contains(prompt, "entity/tail") {
			t.Fatal("head received another window's candidate")
		}
		if strings.Contains(prompt, "TAIL source") && strings.Contains(prompt, "entity/head") {
			t.Fatal("tail received another window's candidate")
		}
		if strings.Contains(prompt, "EMPTY source") && (strings.Contains(prompt, "entity/head") || strings.Contains(prompt, "entity/tail")) {
			t.Fatal("empty window received global candidates")
		}
	}
	entities, _, uncited := mergeCitationsIntoItems([]extractedItem{{Slug: "entity/head", Name: "Head"}, {Slug: "entity/tail", Name: "Tail"}}, nil, result.Citations, result.NewSlugs)
	if uncited != 0 || !equalStrings(entities[0].SourceChunks, []string{"head", "empty"}) || !equalStrings(entities[1].SourceChunks, []string{"tail"}) {
		t.Fatalf("evidence=%+v uncited=%d", entities, uncited)
	}
}

func TestWindowCitationRejectsAnotherWindowsHandle(t *testing.T) {
	windows := []wikiDocumentWindow{
		{content: "FIRST source", candidates: "entity/first", chunks: []*types.Chunk{windowChunk("first", 0, "FIRST source")}},
		{content: "SECOND source", candidates: "entity/second", chunks: []*types.Chunk{windowChunk("second", 1, "SECOND source")}},
	}
	chunks := append(append([]*types.Chunk{}, windows[0].chunks...), windows[1].chunks...)
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		if strings.Contains(promptText(messages), "SECOND source") {
			return &types.ChatResponse{Content: `{"citations":{"entity/second":["c001"]}}`}, nil
		}
		return &types.ChatResponse{Content: `{"citations":{"entity/first":["c000"]}}`}, nil
	}}
	result := (&wikiIngestService{}).classifyChunkCitations(context.Background(), model, "entity/first entity/second", chunks, "en", wikiOutcomeBatchContext(), nil, windows)
	if wikiFailureOutcome(result.Err()) != wikiOutcomeFailed || len(result.BatchErrors) != 2 || result.BatchErrors[0] != nil || result.BatchErrors[1] == nil {
		t.Fatalf("cross-window handle accepted: %+v", result)
	}
	if !equalStrings(result.Citations["entity/first"], []string{"first"}) {
		t.Fatalf("successful peer lost: %+v", result)
	}
}

func TestWindowCitationSkipsOnlyDocumentEmptyOrMarkupWindows(t *testing.T) {
	windows := []wikiDocumentWindow{
		{content: "![scan](image)", chunks: []*types.Chunk{windowChunk("image", 0, "![scan](image)")}},
		{content: "actual source", candidates: "entity/actual", chunks: []*types.Chunk{windowChunk("actual", 1, "actual source")}},
	}
	chunks := append(append([]*types.Chunk{}, windows[0].chunks...), windows[1].chunks...)
	var calls atomic.Int32
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		calls.Add(1)
		if strings.Contains(promptText(messages), "![scan]") {
			return nil, errors.New("markup-only window sent")
		}
		return &types.ChatResponse{Content: `{"citations":{}}`}, nil
	}}
	svc := &wikiIngestService{}
	result := svc.classifyChunkCitations(context.Background(), model, "", chunks, "en", wikiOutcomeBatchContext(), nil, windows)
	if result.Err() != nil || calls.Load() != 0 {
		t.Fatal("document without candidates must skip citation")
	}
	result = svc.classifyChunkCitations(context.Background(), model, "entity/actual", chunks, "en", wikiOutcomeBatchContext(), nil, windows)
	if result.Err() != nil || calls.Load() != 1 {
		t.Fatalf("calls=%d err=%v", calls.Load(), result.Err())
	}
}

func TestWindowCitationSinglePoolPreservesPeersAndCancellation(t *testing.T) {
	for _, cancelParent := range []bool{false, true} {
		t.Run(fmt.Sprintf("cancel=%v", cancelParent), func(t *testing.T) {
			windows := candidateWindows(7)
			var chunks []*types.Chunk
			for i := range windows {
				windows[i].chunks = []*types.Chunk{windowChunk(fmt.Sprintf("chunk-%d", i), i, windows[i].content+strings.Repeat("字", 12000))}
				windows[i].candidates = "entity/shared"
				chunks = append(chunks, windows[i].chunks...)
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			started := make(chan int, 7)
			release := make(chan struct{})
			var active, peak, calls atomic.Int32
			model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
				index := candidateWindowIndex(messages, 7)
				calls.Add(1)
				current := active.Add(1)
				defer active.Add(-1)
				for old := peak.Load(); current > old; old = peak.Load() {
					if peak.CompareAndSwap(old, current) {
						break
					}
				}
				started <- index
				select {
				case <-release:
				case <-ctx.Done():
					return nil, ctx.Err()
				}
				if index == 1 {
					return &types.ChatResponse{Content: "{", FinishReason: "length"}, nil
				}
				if index == 2 {
					return nil, io.EOF
				}
				return &types.ChatResponse{Content: `{"citations":{"entity/shared":["c000"]}}`}, nil
			}}
			done := make(chan citationClassificationOutcome, 1)
			go func() {
				done <- (&wikiIngestService{}).classifyChunkCitations(ctx, model, "entity/shared", chunks, "en", wikiOutcomeBatchContext(), nil, windows)
			}()
			timer := time.NewTimer(10 * time.Second)
			defer timer.Stop()
			for i := 0; i < 4; i++ {
				select {
				case <-started:
				case <-timer.C:
					t.Fatal("citation pool did not dispatch four peers")
				}
			}
			if cancelParent {
				cancel()
			} else {
				close(release)
			}
			var result citationClassificationOutcome
			select {
			case result = <-done:
			case <-timer.C:
				t.Fatal("citation pool stuck")
			}
			if len(result.BatchErrors) != 7 || wikiFailureOutcome(result.Err()) != wikiOutcomeUnknown || peak.Load() != 4 {
				t.Fatalf("peak=%d result=%+v err=%v", peak.Load(), result, result.Err())
			}
			if cancelParent {
				if calls.Load() != 4 {
					t.Fatalf("sent after cancellation: %d", calls.Load())
				}
				for i, err := range result.BatchErrors {
					want := wikiOutcomeUnknown
					if i >= 4 {
						want = wikiOutcomeNotRun
					}
					if wikiFailureOutcome(err) != want {
						t.Fatalf("batch=%d err=%v want=%s", i, err, want)
					}
				}
			} else if calls.Load() != 7 || !errors.Is(result.Err(), errWikiOutputTruncated) || !equalStrings(result.Citations["entity/shared"], []string{"chunk-0", "chunk-3", "chunk-4", "chunk-5", "chunk-6"}) {
				t.Fatalf("lost peers: calls=%d result=%+v", calls.Load(), result)
			}
		})
	}
}

func TestWindowCitationTruncationProducesNoDocumentUpdates(t *testing.T) {
	var cites atomic.Int32
	model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		purpose, _ := types.LLMCallMetadataFromContext(ctx)
		switch purpose {
		case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
			return candidateAnswer(extractedItem{Name: "Known", Slug: "entity/known"}), nil
		case wikiPromptPurpose(agent.WikiChunkCitationPrompt):
			cites.Add(1)
			return &types.ChatResponse{Content: `{"citations":{}}`, FinishReason: "length"}, nil
		default:
			return &types.ChatResponse{Content: "SUMMARY: document\nSummary"}, nil
		}
	}}
	svc := &wikiIngestService{chunkRepo: longDocChunks{}, knowledgeSvc: wikiOutcomeKnowledge{}, wikiService: &wikiOutcomePages{}}
	result, updates, err := svc.mapOneDocument(context.Background(), model, WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"}, WikiPendingOp{KnowledgeID: "source"}, wikiOutcomeBatchContext())
	if result != nil || len(updates) != 0 || cites.Load() == 0 || !errors.Is(err, errWikiOutputTruncated) || wikiFailureOutcome(err) != wikiOutcomeFailed {
		t.Fatalf("result=%v updates=%d cites=%d err=%v", result, len(updates), cites.Load(), err)
	}
}

func TestWindowCitationRediscoveredEarlierEvidenceKeepsDocumentOrder(t *testing.T) {
	early := windowChunk("early", 0, "EARLY source paragraph")
	late := windowChunk("late", 1, "LATE source paragraph")
	chunks := []*types.Chunk{early, late}
	windows := []wikiDocumentWindow{
		{content: early.Content, chunks: []*types.Chunk{early}},
		{content: late.Content, candidates: "entity/a", chunks: []*types.Chunk{late}},
	}
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		if strings.Contains(promptText(messages), early.Content) {
			return &types.ChatResponse{Content: `{"citations":{},"new_slugs":[{"type":"entity","slug":"entity/a","name":"A","source_chunks":["c000","c000"]}]}`}, nil
		}
		return &types.ChatResponse{Content: `{"citations":{"entity/a":["c000","c000"]},"new_slugs":[]}`}, nil
	}}
	outcome := (&wikiIngestService{}).classifyChunkCitations(context.Background(), model, "entity/a", chunks, "en", wikiOutcomeBatchContext(), nil, windows)
	if err := outcome.Err(); err != nil {
		t.Fatal(err)
	}
	entities, _, uncited := mergeCitationsIntoItems([]extractedItem{{Slug: "entity/a", Name: "A"}}, nil, outcome.Citations, outcome.NewSlugs)
	if len(entities) != 1 || uncited != 0 || !equalStrings(entities[0].SourceChunks, []string{"early", "late"}) {
		t.Fatalf("rediscovered references must be unique and in document order: items=%+v uncited=%d", entities, uncited)
	}
	content := collectCitedChunkContent(entities[0].SourceChunks, map[string]string{"early": early.Content, "late": late.Content})
	if want := early.Content + "\n\n" + late.Content; content != want {
		t.Fatalf("materialized evidence order changed: got=%q want=%q", content, want)
	}
}
