package service

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

type windowChunks struct {
	citedChunkRepo
	chunks []*types.Chunk
	reads  int
}

func (r *windowChunks) ListChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error) {
	return r.chunks, nil
}

func (r *windowChunks) ListChunksByParentIDs(ctx context.Context, tenant uint64, ids []string) ([]*types.Chunk, error) {
	r.reads++
	return r.citedChunkRepo.ListChunksByParentIDs(ctx, tenant, ids)
}

func windowChunk(id string, index int, text string) *types.Chunk {
	return &types.Chunk{ID: id, KnowledgeID: "source", ChunkIndex: index, ChunkType: types.ChunkTypeText, Content: text}
}

func TestWikiWindowsStableMembershipAndFilter(t *testing.T) {
	a := windowChunk("a", 1, "first")
	b := windowChunk("b", 1, "second")
	b.StartAt = 1
	c := windowChunk("c", 1, "third")
	c.StartAt = 1
	d := windowChunk("d", 2, "fourth")
	d.ChunkType = ""
	ignored := windowChunk("image", 0, "not text")
	ignored.ChunkType = types.ChunkTypeImageOCR
	input := []*types.Chunk{d, b, c, nil, ignored, a, windowChunk("empty", 0, "")}
	windows, _ := prepareWikiDocumentWindows(context.Background(), nil, 1, input)
	var ids []string
	for _, window := range windows {
		for _, c := range window.chunks {
			ids = append(ids, c.ID)
		}
	}
	if !equalStrings(ids, []string{"a", "b", "c", "d"}) {
		t.Fatalf("membership=%v", ids)
	}
	if input[0] != d || input[1] != b {
		t.Fatal("sorting mutated caller input")
	}
}

func TestWikiWindowsRebuiltRuneBudget(t *testing.T) {
	for _, tc := range []struct {
		name    string
		chunks  []*types.Chunk
		lengths []int
	}{
		{
			"exact",
			[]*types.Chunk{
				windowChunk("a", 0, strings.Repeat("中", 16383)),
				windowChunk("b", 1, strings.Repeat("文", 16384)),
			},
			[]int{32768},
		},
		{
			"separator exceeds",
			[]*types.Chunk{
				windowChunk("a", 0, strings.Repeat("中", 16384)),
				windowChunk("b", 1, strings.Repeat("文", 16384)),
			},
			[]int{16384, 16384},
		},
		{
			"oversize then tiny",
			[]*types.Chunk{windowChunk("a", 0, strings.Repeat("中", 32769)), windowChunk("b", 1, "尾")},
			[]int{32769, 1},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			windows, _ := prepareWikiDocumentWindows(context.Background(), nil, 1, tc.chunks)
			if len(windows) != len(tc.lengths) {
				t.Fatalf("windows=%d want=%d", len(windows), len(tc.lengths))
			}
			var seen []string
			for i, w := range windows {
				if n := utf8.RuneCountInString(w.content); n != tc.lengths[i] {
					t.Fatalf("window %d length=%d want=%d", i, n, tc.lengths[i])
				}
				for _, c := range w.chunks {
					seen = append(seen, c.ID)
				}
			}
			if !equalStrings(seen, []string{"a", "b"}) {
				t.Fatalf("lost/duplicate chunks: %v", seen)
			}
		})
	}
	a := windowChunk("a", 0, strings.Repeat("甲", 19600)+strings.Repeat("叠", 400))
	a.EndAt = 20000
	b := windowChunk("b", 1, strings.Repeat("叠", 400)+strings.Repeat("乙", 12600))
	b.StartAt = 19600
	b.EndAt = 32600
	windows, _ := prepareWikiDocumentWindows(context.Background(), nil, 1, []*types.Chunk{a, b})
	if len(windows) != 1 || utf8.RuneCountInString(windows[0].content) != 32600 {
		t.Fatalf("overlap must fit one reconstructed window: %+v", windows)
	}
}

func TestWikiWindowsEnrichmentReadOnceAndWindowLocal(t *testing.T) {
	const image = "resource://image"
	a := windowChunk("a", 0, "![scan]("+image+")")
	b := windowChunk("b", 1, "Other text ![scan]("+image+")")
	info := func(caption string) string {
		data, _ := json.Marshal([]types.ImageInfo{{URL: image, Caption: caption}})
		return string(data)
	}
	repo := &windowChunks{citedChunkRepo: citedChunkRepo{byParent: map[string][]*types.Chunk{
		"a": {imageChildChunk("child-a", "a", types.ChunkTypeImageCaption, info(strings.Repeat("长", 32768)), true)},
		"b": {imageChildChunk("child-b", "b", types.ChunkTypeImageCaption, info("WINDOW_B_CAPTION"), true)},
	}}}
	windows, _ := prepareWikiDocumentWindows(context.Background(), repo, 1, []*types.Chunk{a, b})
	if repo.reads != 1 || len(windows) != 2 {
		t.Fatalf("reads=%d windows=%d", repo.reads, len(windows))
	}
	if len(windows[0].chunks) != 1 || utf8.RuneCountInString(windows[0].content) <= 32768 {
		t.Fatal("enriched oversize chunk must stay intact and alone")
	}
	if !strings.Contains(windows[1].content, "WINDOW_B_CAPTION") || strings.Contains(windows[1].content, "长") {
		t.Fatal("another window's image description contaminated this window")
	}
	// Normal one-window content remains exactly the existing enrichment output.
	want := reconstructEnrichedContent(context.Background(), repo, 1, []*types.Chunk{b})
	single, _ := prepareWikiDocumentWindows(context.Background(), repo, 1, []*types.Chunk{b})
	if len(single) != 1 || single[0].content != want {
		t.Fatalf("single-window enrichment changed")
	}
}

func TestWikiWindowsMarkupFirstAndShortTailModelCalls(t *testing.T) {
	for _, tc := range []struct {
		name           string
		first, tail    string
		wantCandidates int
		wantSummary    string
	}{
		{"markup first", "![scan](" + strings.Repeat("x", 32768) + ")", "这里包含足够长的真实正文内容", 1, "这里包含足够长的真实正文内容"},
		{"short tail", strings.Repeat("文", 32768), "有效尾", 2, strings.Repeat("文", 32768)},
		{"insufficient whole document", "![scan](" + strings.Repeat("x", 32768) + ")", "字", 0, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var mu sync.Mutex
			var candidates, summaries []string
			model := &windowChat{
				answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
					purpose, _ := types.LLMCallMetadataFromContext(ctx)
					mu.Lock()
					defer mu.Unlock()
					switch purpose {
					case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
						candidates = append(candidates, promptText(messages))
						return &types.ChatResponse{Content: `{"entities":[],"concepts":[]}`}, nil
					case wikiPromptPurpose(agent.WikiSummaryPrompt):
						summaries = append(summaries, promptText(messages))
						return &types.ChatResponse{Content: "SUMMARY: text\nsummary"}, nil
					default:
						return nil, fmt.Errorf("unexpected purpose %s", purpose)
					}
				},
			}
			repo := &windowChunks{chunks: []*types.Chunk{windowChunk("a", 0, tc.first), windowChunk("b", 1, tc.tail)}}
			svc := &wikiIngestService{
				chunkRepo:    repo,
				knowledgeSvc: wikiOutcomeKnowledge{},
				wikiService:  &wikiOutcomePages{},
			}
			_, _, err := svc.mapOneDocument(
				context.Background(), model, WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"},
				WikiPendingOp{KnowledgeID: "source"}, wikiOutcomeBatchContext(),
			)
			if err != nil || len(candidates) != tc.wantCandidates {
				t.Fatalf("candidates=%d err=%v", len(candidates), err)
			}
			if tc.wantCandidates > 0 && (len(summaries) != 1 || !strings.Contains(summaries[0], tc.wantSummary)) {
				t.Fatal("summary must use first real-text window")
			}
			if tc.wantCandidates == 0 && len(summaries) != 0 {
				t.Fatal("empty whole document invoked summary")
			}
		})
	}
}

func TestWikiWindowsEnrichedContentBudgetIncludesCaptions(t *testing.T) {
	const image = "resource://budget-image"
	imageText := "![scan](" + image + ")"
	info, _ := json.Marshal([]types.ImageInfo{{URL: image, Caption: strings.Repeat("图", 2000)}})
	repo := &windowChunks{citedChunkRepo: citedChunkRepo{byParent: map[string][]*types.Chunk{
		"image": {imageChildChunk("caption", "image", types.ChunkTypeImageCaption, string(info), true)},
	}}}
	plain := windowChunk("plain", 0, strings.Repeat("正文", 16350))
	picture := windowChunk("image", 1, imageText)
	windows, _ := prepareWikiDocumentWindows(context.Background(), repo, 1, []*types.Chunk{plain, picture})
	if len(windows) != 2 || repo.reads != 1 {
		t.Fatalf("enrichment must split raw-fitting chunks: windows=%d reads=%d", len(windows), repo.reads)
	}
	for _, window := range windows {
		if utf8.RuneCountInString(window.content) > maxContentForWiki {
			t.Fatal("ordinary enriched window exceeded budget")
		}
	}
	// Fill the first chunk so the rebuilt newline + enriched image exactly hit the budget.
	imageLen := utf8.RuneCountInString(windows[1].content)
	plain.Content = strings.Repeat("界", maxContentForWiki-imageLen-1)
	windows, _ = prepareWikiDocumentWindows(context.Background(), repo, 1, []*types.Chunk{plain, picture})
	if len(windows) != 1 || utf8.RuneCountInString(windows[0].content) != maxContentForWiki {
		t.Fatal("exact enriched boundary should occupy one window")
	}
}

type windowRetractionPages struct{ wikiOutcomePages }

func (windowRetractionPages) ListSlugsBySourceRef(context.Context, string, string) ([]string, error) {
	return []string{"entity/known", "entity/stale"}, nil
}

func TestWikiWindowsRetractionsKeepActualFirstWindowAndPriorContribution(t *testing.T) {
	first := "![scan](" + strings.Repeat("x", 32768) + ")"
	tail := "Current real source text is sufficiently substantial."
	repo := &windowChunks{chunks: []*types.Chunk{windowChunk("first", 0, first), windowChunk("tail", 1, tail)}}
	model := &windowChat{answer: func(ctx context.Context, _ []chat.Message) (*types.ChatResponse, error) {
		purpose, _ := types.LLMCallMetadataFromContext(ctx)
		switch purpose {
		case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
			return candidateAnswer(extractedItem{Slug: "entity/known", Name: "Known"}), nil
		case wikiPromptPurpose(agent.WikiChunkCitationPrompt):
			return &types.ChatResponse{Content: `{"citations":{"entity/known":["c000"]}}`}, nil
		default:
			return &types.ChatResponse{Content: "SUMMARY: Current\nCurrent summary"}, nil
		}
	}}
	batch := wikiOutcomeBatchContext()
	batch.SummaryContentByKnowledgeID = func(context.Context, string) string { return "PRIOR_CONTRIBUTION" }
	svc := &wikiIngestService{
		chunkRepo:    repo,
		knowledgeSvc: wikiOutcomeKnowledge{},
		wikiService:  &windowRetractionPages{},
	}
	_, updates, err := svc.mapOneDocument(
		context.Background(), model, WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"},
		WikiPendingOp{KnowledgeID: "source"}, batch,
	)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]string{}
	for _, update := range updates {
		if update.Type == "retract" || update.Type == "retractStale" {
			seen[update.Type] = update.RetractDocContent
		}
	}
	if seen["retract"] != "PRIOR_CONTRIBUTION" || seen["retractStale"] != first {
		t.Fatalf(
			"retraction context changed: prior=%q stale_runes=%d", seen["retract"],
			utf8.RuneCountInString(seen["retractStale"]),
		)
	}
}

type windowUntitledKnowledge struct{ wikiOutcomeKnowledge }

func (windowUntitledKnowledge) GetKnowledgeByIDOnly(context.Context, string) (*types.Knowledge, error) {
	return &types.Knowledge{ID: "source", ParseStatus: types.ParseStatusFinalizing}, nil
}

func TestWikiWindowsIgnoreNilChunkDuringTitleFallback(t *testing.T) {
	model := &windowChat{answer: func(ctx context.Context, _ []chat.Message) (*types.ChatResponse, error) {
		purpose, _ := types.LLMCallMetadataFromContext(ctx)
		if purpose == wikiPromptPurpose(agent.WikiCandidateSlugPrompt) {
			return candidateAnswer(), nil
		}
		return &types.ChatResponse{Content: "SUMMARY: Body\nSummary"}, nil
	}}
	svc := &wikiIngestService{
		chunkRepo: &windowChunks{
			chunks: []*types.Chunk{nil, windowChunk("body", 0, "This is substantial body text.")},
		},
		knowledgeSvc: windowUntitledKnowledge{},
		wikiService:  &wikiOutcomePages{},
	}
	_, _, err := svc.mapOneDocument(
		context.Background(), model, WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"},
		WikiPendingOp{KnowledgeID: "source"}, wikiOutcomeBatchContext(),
	)
	if err != nil {
		t.Fatal(err)
	}
}
