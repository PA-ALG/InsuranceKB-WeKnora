package service

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestCandidateOverflowCitationKeepsEmptyLeavesAndSkipsMarkup(t *testing.T) {
	for _, markup := range []bool{false, true} {
		for _, allEmpty := range []bool{false, true} {
			t.Run(fmt.Sprintf("markup=%v/all_empty=%v", markup, allEmpty), func(t *testing.T) {
				left := "EMPTY_LEAF substantive text"
				if markup {
					left = "![scan](resource://empty-leaf)"
				}
				chunks := []*types.Chunk{
					windowChunk("left", 0, left), windowChunk("right", 1, "KNOWN_LEAF substantive text"),
				}
				windows, _ := prepareWikiDocumentWindows(context.Background(), nil, 1, chunks)
				var mu sync.Mutex
				var candidates, citations []string
				model := &windowChat{
					answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
						purpose, _ := types.LLMCallMetadataFromContext(ctx)
						prompt := promptText(messages)
						mu.Lock()
						defer mu.Unlock()
						if purpose == wikiPromptPurpose(agent.WikiCandidateSlugPrompt) {
							candidates = append(candidates, prompt)
							if len(candidates) == 1 {
								return overflowResponse(), nil
							}
							if strings.Contains(prompt, "KNOWN_LEAF") && !allEmpty {
								return candidateAnswer(extractedItem{Slug: "entity/known", Name: "Known"}), nil
							}
							return candidateAnswer(), nil
						}
						citations = append(citations, prompt)
						return &types.ChatResponse{Content: `{"citations":{}}`, FinishReason: "stop"}, nil
					},
				}
				svc := &wikiIngestService{}
				batch := wikiOutcomeBatchContext()
				e, c, _, err := svc.extractCandidateSlugs(context.Background(), model, "kb", windows, "en", nil, batch)
				if err != nil {
					t.Fatal(err)
				}
				result := svc.classifyChunkCitations(
					context.Background(), model, renderCandidateSlugsXML(e, c), chunks, "en", batch, nil, windows,
				)
				wantCandidates, wantCitations := 3, 2
				if markup {
					wantCandidates, wantCitations = 2, 1
				}
				if allEmpty {
					wantCitations = 0
				}
				if result.Err() != nil || len(candidates) != wantCandidates || len(citations) != wantCitations {
					t.Fatalf("candidates=%d citations=%d err=%v", len(candidates), len(citations), result.Err())
				}
				for _, prompt := range citations {
					known := strings.Contains(prompt, "KNOWN_LEAF")
					if strings.Contains(prompt, "entity/known") != known {
						t.Fatal("leaf received another leaf's candidate")
					}
					if !known && !strings.Contains(prompt, "EMPTY_LEAF") {
						t.Fatal("markup leaf should never reach citation")
					}
				}
			})
		}
	}
}

func TestCandidateOverflowCanonicalMappingDeduplicatesWholeDocumentOnce(t *testing.T) {
	windows, _ := prepareWikiDocumentWindows(context.Background(), nil, 1, overflowChunks("first", "second"))
	pages := &windowIdentityPages{
		page: &types.WikiPageLite{Slug: "entity/canonical", Title: "Established", PageType: types.WikiPageTypeEntity},
	}
	var dedupCalls atomic.Int32
	var mu sync.Mutex
	var citations []string
	model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		purpose, _ := types.LLMCallMetadataFromContext(ctx)
		if purpose == "wiki_deduplication" {
			dedupCalls.Add(1)
			return &types.ChatResponse{
				Content: `{"merges":{"entity/a":"entity/canonical","entity/b":"entity/canonical"}}`,
			}, nil
		}
		if purpose == wikiPromptPurpose(agent.WikiChunkCitationPrompt) {
			mu.Lock()
			citations = append(citations, promptText(messages))
			mu.Unlock()
			return &types.ChatResponse{Content: `{"citations":{}}`}, nil
		}
		ids := chunkNumbers(promptText(messages))
		if len(ids) == 2 {
			return overflowResponse(), nil
		}
		if ids[0] == 0 {
			return candidateAnswer(extractedItem{Slug: "entity/a", Name: "First"}), nil
		}
		return candidateAnswer(extractedItem{Slug: "entity/b", Name: "Second"}), nil
	}}
	svc := &wikiIngestService{wikiService: pages}
	batch := wikiOutcomeBatchContext()
	e, c, _, err := svc.extractCandidateSlugs(context.Background(), model, "kb", windows, "en", nil, batch)
	if err != nil || dedupCalls.Load() != 1 || len(e) != 1 || e[0].Slug != "entity/canonical" {
		t.Fatalf("dedup calls=%d entities=%v err=%v", dedupCalls.Load(), e, err)
	}
	result := svc.classifyChunkCitations(
		context.Background(), model, renderCandidateSlugsXML(e, c), nil, "en", batch, nil, windows,
	)
	if result.Err() != nil || len(citations) != 2 {
		t.Fatalf("citations=%d err=%v", len(citations), result.Err())
	}
	for _, prompt := range citations {
		if !strings.Contains(prompt, "entity/canonical") ||
			strings.Contains(prompt, "entity/a,") || strings.Contains(prompt, "entity/b,") {
			t.Fatal("split leaf did not receive its canonical candidate")
		}
	}
}

func TestCandidateOverflowPreservesOriginalSummaryAndRetractionInput(t *testing.T) {
	chunks := overflowChunks("first substantial source passage", "second substantial source passage")
	original := reconstructContent(chunks)
	var summary string
	model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		purpose, _ := types.LLMCallMetadataFromContext(ctx)
		prompt := promptText(messages)
		switch purpose {
		case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
			if len(chunkNumbers(prompt)) == 2 {
				return overflowResponse(), nil
			}
			return candidateAnswer(extractedItem{Slug: "entity/known", Name: "Known"}), nil
		case wikiPromptPurpose(agent.WikiChunkCitationPrompt):
			return &types.ChatResponse{Content: `{"citations":{"entity/known":["c000"]}}`}, nil
		default:
			summary = prompt
			return &types.ChatResponse{Content: "SUMMARY: Current\nCurrent summary"}, nil
		}
	}}
	batch := wikiOutcomeBatchContext()
	batch.SummaryContentByKnowledgeID = func(context.Context, string) string { return "PRIOR_CONTRIBUTION" }
	svc := &wikiIngestService{
		chunkRepo: &windowChunks{chunks: chunks}, knowledgeSvc: wikiOutcomeKnowledge{},
		wikiService: &windowRetractionPages{},
	}
	_, updates, err := svc.mapOneDocument(
		context.Background(), model, WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"},
		WikiPendingOp{KnowledgeID: "source"}, batch,
	)
	if err != nil || !strings.Contains(summary, original) {
		t.Fatalf("summary must still see the original root: err=%v", err)
	}
	seen := map[string]string{}
	for _, update := range updates {
		if update.Type == "retract" || update.Type == "retractStale" {
			seen[update.Type] = update.RetractDocContent
		}
	}
	if seen["retract"] != "PRIOR_CONTRIBUTION" || seen["retractStale"] != original {
		t.Fatalf("retraction context changed: %v", seen)
	}
}
