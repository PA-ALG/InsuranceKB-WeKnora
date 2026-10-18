package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

func candidateWindows(n int) []wikiDocumentWindow {
	windows := make([]wikiDocumentWindow, n)
	for i := range windows {
		windows[i].content = fmt.Sprintf("WINDOW[%d] substantive source", i)
	}
	return windows
}

func candidateWindowIndex(messages []chat.Message, n int) int {
	text := promptText(messages)
	for i := 0; i < n; i++ {
		if strings.Contains(text, fmt.Sprintf("WINDOW[%d]", i)) {
			return i
		}
	}
	return -1
}

func candidateAnswer(items ...extractedItem) *types.ChatResponse {
	raw, _ := json.Marshal(combinedExtraction{Entities: items})
	return &types.ChatResponse{Content: string(raw), FinishReason: "stop"}
}

func TestWindowCandidateMergeKeepsFirstEmptyFields(t *testing.T) {
	windows := candidateWindows(2)
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		if candidateWindowIndex(messages, 2) == 0 {
			return candidateAnswer(extractedItem{Slug: "entity/shared", Aliases: []string{" first ", "", "first"}}), nil
		}
		return candidateAnswer(
			extractedItem{
				Slug:        "entity/shared",
				Name:        "Later",
				Description: "Later description",
				Details:     "Later details",
				Aliases:     []string{"second", " first", "First"},
			},
		), nil
	}}
	entities, _, _, err := (&wikiIngestService{}).extractCandidateSlugs(
		context.Background(), model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
	)
	if err != nil || len(entities) != 1 {
		t.Fatalf("entities=%+v err=%v", entities, err)
	}
	got := entities[0]
	if got.Name != "" || got.Description != "" || got.Details != "" ||
		!equalStrings(got.Aliases, []string{"first", "second", "First"}) {
		t.Fatalf("first item/alias policy changed: %+v", got)
	}
}

func TestWindowCandidateCanonicalMappingKeepsLocalOwnership(t *testing.T) {
	windows := candidateWindows(3)
	model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		switch candidateWindowIndex(messages, 3) {
		case 0:
			return candidateAnswer(
				extractedItem{Slug: "entity/alpha", Name: "Same title"},
				extractedItem{Slug: "entity/head", Name: "Head"},
			), nil
		case 1:
			return candidateAnswer(
				extractedItem{Slug: "entity/beta", Name: "Same title"},
				extractedItem{Slug: "entity/tail", Name: "Tail"},
			), nil
		default:
			return candidateAnswer(), nil
		}
	}}
	entities, _, _, err := (&wikiIngestService{}).extractCandidateSlugs(
		context.Background(), model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
	)
	if err != nil || len(entities) != 3 {
		t.Fatalf("entities=%+v err=%v", entities, err)
	}
	if !strings.Contains(windows[1].candidates, "entity/alpha") ||
		strings.Contains(windows[1].candidates, "entity/beta") ||
		strings.Contains(windows[1].candidates, "entity/head") {
		t.Fatalf("bad tail candidates: %s", windows[1].candidates)
	}
	if strings.Contains(windows[0].candidates, "entity/tail") || windows[2].candidates != "" {
		t.Fatalf("candidate ownership leaked: %+v", windows)
	}
	for _, item := range entities {
		if len(item.SourceChunks) != 0 {
			t.Fatal("candidate ownership must not fabricate evidence")
		}
	}
}

func TestWindowCandidatePoolStableDespiteReverseCompletion(t *testing.T) {
	const n = 8
	windows := candidateWindows(n)
	started := make(chan int, n)
	finished := make(chan int, n)
	gates := make([]chan struct{}, n)
	for i := range gates {
		gates[i] = make(chan struct{})
	}
	var active, maxActive atomic.Int32
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		index := candidateWindowIndex(messages, n)
		if index < 0 {
			return nil, errors.New("missing window marker")
		}
		current := active.Add(1)
		defer active.Add(-1)
		for old := maxActive.Load(); current > old; old = maxActive.Load() {
			if maxActive.CompareAndSwap(old, current) {
				break
			}
		}
		started <- index
		select {
		case <-gates[index]:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
		finished <- index
		return candidateAnswer(
			extractedItem{
				Slug:        "entity/shared",
				Name:        fmt.Sprintf("Name %d", index),
				Description: fmt.Sprintf("first %d", index),
				Aliases:     []string{fmt.Sprintf("alias %d", index)},
			},
		), nil
	}}
	type result struct {
		items []extractedItem
		err   error
	}
	done := make(chan result, 1)
	go func() {
		e, _, _, err := (&wikiIngestService{}).extractCandidateSlugs(
			ctx, model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
		)
		done <- result{e, err}
	}()
	for group := 0; group < 2; group++ {
		var indices []int
		for j := 0; j < 4; j++ {
			select {
			case index := <-started:
				indices = append(indices, index)
			case <-ctx.Done():
				t.Fatal("candidate pool did not dispatch four peers")
			}
		}
		for j := len(indices) - 1; j >= 0; j-- {
			close(gates[indices[j]])
			select {
			case index := <-finished:
				if index != indices[j] {
					t.Fatalf("response order: got %d want %d", index, indices[j])
				}
			case <-ctx.Done():
				t.Fatal("released candidate did not finish")
			}
		}
	}
	got := <-done
	if got.err != nil || len(got.items) != 1 || got.items[0].Name != "Name 0" || got.items[0].Description != "first 0" {
		t.Fatalf("result changed with completion order: %+v", got)
	}
	want := make([]string, n)
	for i := range want {
		want[i] = fmt.Sprintf("alias %d", i)
	}
	if !equalStrings(got.items[0].Aliases, want) || maxActive.Load() != 4 {
		t.Fatalf("aliases=%v peak=%d", got.items[0].Aliases, maxActive.Load())
	}
}

func TestWindowCandidateMixedFailureAndParentCancellation(t *testing.T) {
	for _, cancelParent := range []bool{false, true} {
		t.Run(fmt.Sprintf("cancel=%v", cancelParent), func(t *testing.T) {
			windows := candidateWindows(7)
			started := make(chan int, 7)
			release := make(chan struct{})
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			var calls atomic.Int32
			model := &windowChat{
				answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
					index := candidateWindowIndex(messages, 7)
					calls.Add(1)
					started <- index
					select {
					case <-release:
					case <-ctx.Done():
						return nil, ctx.Err()
					}
					if index == 0 {
						return &types.ChatResponse{Content: "{}", FinishReason: "length"}, nil
					}
					if index == 1 {
						return nil, io.EOF
					}
					return candidateAnswer(
						extractedItem{Slug: fmt.Sprintf("entity/e%d", index), Name: fmt.Sprintf("N%d", index)},
					), nil
				},
			}
			done := make(chan error, 1)
			go func() {
				e, c, items, err := (&wikiIngestService{}).extractCandidateSlugs(
					ctx, model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
				)
				if len(e)+len(c)+len(items) > 0 {
					done <- errors.New("partial candidates escaped")
					return
				}
				done <- err
			}()
			timer := time.NewTimer(10 * time.Second)
			defer timer.Stop()
			for i := 0; i < 4; i++ {
				select {
				case <-started:
				case <-timer.C:
					t.Fatal("pool did not dispatch four peers")
				}
			}
			if cancelParent {
				cancel()
			} else {
				close(release)
			}
			var err error
			select {
			case err = <-done:
			case <-timer.C:
				t.Fatal("candidate pool stuck")
			}
			var stage *wikiStageFailure
			if !errors.As(err, &stage) || stage.Stage != "wiki_candidate_slug" || stage.Outcome != wikiOutcomeUnknown {
				t.Fatalf("err=%v", err)
			}
			if cancelParent && calls.Load() != 4 {
				t.Fatalf("sent after cancellation: %d", calls.Load())
			}
			if !cancelParent && (calls.Load() != 7 || !errors.Is(err, errWikiOutputTruncated)) {
				t.Fatalf("lost peers or error chain: calls=%d err=%v", calls.Load(), err)
			}
		})
	}
}

type windowIdentityPages struct {
	wikiOutcomePages
	page *types.WikiPageLite
}

func (p *windowIdentityPages) FindSimilarPages(
	context.Context, string, string, []string, int,
) ([]*types.WikiPageLite, error) {
	return []*types.WikiPageLite{p.page}, nil
}

func TestWindowCandidateSingleWindowKeepsExistingDedupRendering(t *testing.T) {
	windows := candidateWindows(1)
	pages := &windowIdentityPages{
		page: &types.WikiPageLite{Slug: "concept/shared", Title: "Shared", PageType: types.WikiPageTypeConcept},
	}
	model := &windowChat{answer: func(context.Context, []chat.Message) (*types.ChatResponse, error) {
		return candidateAnswer(extractedItem{Slug: "entity/raw", Name: "Shared"}), nil
	}}
	entities, concepts, _, err := (&wikiIngestService{wikiService: pages}).extractCandidateSlugs(
		context.Background(), model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
	)
	if err != nil || len(entities) != 1 || entities[0].Slug != "concept/shared" ||
		windows[0].candidates != renderCandidateSlugsXML(entities, concepts) {
		t.Fatalf(
			"single-window rendering changed: candidates=%q entities=%+v err=%v", windows[0].candidates, entities, err,
		)
	}
}

func TestWindowCandidateSemanticDedupRunsOnceWithExplicitMapping(t *testing.T) {
	windows := candidateWindows(3)
	pages := &windowIdentityPages{
		page: &types.WikiPageLite{Slug: "entity/canonical", Title: "Established", PageType: types.WikiPageTypeEntity},
	}
	var dedupCalls atomic.Int32
	model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		purpose, _ := types.LLMCallMetadataFromContext(ctx)
		if purpose == "wiki_deduplication" {
			dedupCalls.Add(1)
			return &types.ChatResponse{
				Content: `{"merges":{"entity/a":"entity/canonical","entity/b":"entity/canonical"}}`,
			}, nil
		}
		i := candidateWindowIndex(messages, 3)
		if i == 1 {
			return candidateAnswer(extractedItem{Slug: "entity/b", Name: "Second"}), nil
		}
		return candidateAnswer(extractedItem{Slug: "entity/a", Name: "First"}), nil
	}}
	entities, _, _, err := (&wikiIngestService{wikiService: pages}).extractCandidateSlugs(
		context.Background(), model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
	)
	if err != nil || dedupCalls.Load() != 1 || len(entities) != 1 || entities[0].Slug != "entity/canonical" {
		t.Fatalf("dedup calls=%d entities=%+v err=%v", dedupCalls.Load(), entities, err)
	}
	for i, w := range windows {
		if !strings.Contains(w.candidates, "entity/canonical") || strings.Contains(w.candidates, "entity/a,") ||
			strings.Contains(w.candidates, "entity/b,") {
			t.Fatalf("window %d: %s", i, w.candidates)
		}
	}
}

func TestWindowIdentityMappingCapturesEveryOriginalBeforeCoalescing(t *testing.T) {
	mapping := map[string]string{}
	items := []extractedItem{
		{Slug: "entity/a", Name: "First"},
		{Slug: "entity/b", Name: "Second"},
		{Slug: "entity/c", Name: "Second"},
	}
	entities := (&wikiIngestService{}).stabilizeExtractedIdentities(
		context.Background(),
		"kb",
		types.WikiPageTypeEntity,
		items,
		map[string]string{"entity/a": "entity/merged", "entity/b": "entity/merged"},
		map[string]string{"entity/c": "entity/exact"},
		wikiOutcomeBatchContext(),
		mapping,
	)
	if len(entities) != 2 || mapping["entity/a"] != "entity/merged" || mapping["entity/b"] != "entity/merged" ||
		mapping["entity/c"] != "entity/exact" {
		t.Fatalf("mapping=%v entities=%+v", mapping, entities)
	}
}
