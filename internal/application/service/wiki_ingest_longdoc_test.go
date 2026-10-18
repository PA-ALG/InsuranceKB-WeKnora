package service

// S6a acceptance: a long document is read in windows (Spec docs/design/slices/S6a-原生Wiki长文档分窗.md
// §4). Protected file: written by Claude. RED until S6a: today the candidate step sees only the
// first 32,768 characters, every citation batch carries the whole candidate list, and a truncated
// answer is reported as a parse error.

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

const (
	longDocChunkCount = 90
	longDocChunkLen   = 600 // runes per chunk: 90 × 600 = 54,000, about two windows
	longDocHeadMark   = "HEADMARK"
	longDocTailMark   = "TAILMARK"
	longDocChunkMark  = "段落编号"
)

type longDocChunks struct{ wikiOutcomeChunks }

func (longDocChunks) ListChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error) {
	chunks := make([]*types.Chunk, 0, longDocChunkCount)
	for i := 0; i < longDocChunkCount; i++ {
		label := fmt.Sprintf("%s%03d：", longDocChunkMark, i)
		if i == 0 {
			label += longDocHeadMark
		}
		if i == longDocChunkCount-1 {
			label += longDocTailMark
		}
		body := label + strings.Repeat("条", longDocChunkLen-len([]rune(label)))
		chunks = append(chunks, &types.Chunk{
			ID: fmt.Sprintf("chunk-%03d", i), KnowledgeID: "source", Content: body,
			ChunkIndex: i, ChunkType: types.ChunkTypeText,
		})
	}
	return chunks, nil
}

// longDocModel answers by purpose and records every prompt it was sent.
type longDocModel struct {
	templateCaptureChatModel
	mu                 sync.Mutex
	candidates         []string
	citations          []string
	truncateCandidates bool
}

func promptText(messages []chat.Message) string {
	var sb strings.Builder
	for _, m := range messages {
		sb.WriteString(m.Content)
		sb.WriteString("\n")
	}
	return sb.String()
}

func (m *longDocModel) Chat(
	ctx context.Context, messages []chat.Message, _ *chat.ChatOptions,
) (*types.ChatResponse, error) {
	purpose, _ := types.LLMCallMetadataFromContext(ctx)
	text := promptText(messages)
	m.mu.Lock()
	defer m.mu.Unlock()
	switch purpose {
	case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
		m.candidates = append(m.candidates, text)
		if m.truncateCandidates {
			return &types.ChatResponse{Content: `{"entities":[],"concepts":[{"name":"Head`, FinishReason: "length"}, nil
		}
		name, slug := "Head", "concept/head-rule"
		if strings.Contains(text, longDocTailMark) {
			name, slug = "Tail", "concept/tail-rule"
		}
		return &types.ChatResponse{Content: fmt.Sprintf(
			`{"entities":[],"concepts":[{"name":%q,"slug":%q,"description":"%s rules","details":"outline"}]}`,
			name, slug, name,
		), FinishReason: "stop"}, nil
	case wikiPromptPurpose(agent.WikiChunkCitationPrompt):
		m.citations = append(m.citations, text)
		return &types.ChatResponse{Content: `{"citations":{},"new_slugs":[]}`, FinishReason: "stop"}, nil
	default:
		return &types.ChatResponse{Content: "SUMMARY: Policy\nPolicy summary.", FinishReason: "stop"}, nil
	}
}

func mapLongDocument(t *testing.T, model *longDocModel) error {
	t.Helper()
	svc := &wikiIngestService{
		knowledgeSvc: wikiOutcomeKnowledge{},
		chunkRepo:    longDocChunks{},
		wikiService:  &wikiOutcomePages{},
	}
	_, _, err := svc.mapOneDocument(
		context.Background(),
		model,
		WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"},
		WikiPendingOp{Op: WikiOpIngest, KnowledgeID: "source"},
		wikiOutcomeBatchContext(),
	)
	return err
}

func TestLongDocumentCandidatesReadTheWholeDocumentInWindows(t *testing.T) {
	model := &longDocModel{}
	_ = mapLongDocument(t, model) // the empty citations may end the document; only the calls matter here

	if len(model.candidates) < 2 {
		t.Fatalf("a %d-rune document must be read in at least two windows, got %d candidate calls",
			longDocChunkCount*longDocChunkLen, len(model.candidates))
	}
	head, tail := false, false
	for i, prompt := range model.candidates {
		chunks := strings.Count(prompt, longDocChunkMark)
		if chunks*longDocChunkLen > maxContentForWiki {
			t.Fatalf("candidate call %d carries %d chunks (%d runes), over the %d window",
				i, chunks, chunks*longDocChunkLen, maxContentForWiki)
		}
		head = head || strings.Contains(prompt, longDocHeadMark)
		tail = tail || strings.Contains(prompt, longDocTailMark)
	}
	if !head || !tail {
		t.Fatalf("the candidate step must see both ends of the document: head=%v tail=%v", head, tail)
	}
}

func TestCitationBatchesListOnlyTheirWindowsCandidates(t *testing.T) {
	model := &longDocModel{}
	_ = mapLongDocument(t, model)

	if len(model.citations) == 0 {
		t.Fatal("citation batches must still be classified")
	}
	sawTail := false
	for i, prompt := range model.citations {
		hasTail := strings.Contains(prompt, longDocTailMark)
		listsTail := strings.Contains(prompt, "concept/tail-rule")
		if hasTail && !listsTail {
			t.Fatalf("citation batch %d holds the tail chunk but does not list the tail window's candidate", i)
		}
		if strings.Contains(prompt, longDocHeadMark) && listsTail {
			t.Fatalf("citation batch %d holds the head chunk but lists a candidate of another window", i)
		}
		sawTail = sawTail || hasTail
	}
	if !sawTail {
		t.Fatal("the tail chunk must reach a citation batch")
	}
}

func TestATruncatedCandidateAnswerFailsAsTruncationNotAsAParseError(t *testing.T) {
	model := &longDocModel{truncateCandidates: true}
	err := mapLongDocument(t, model)

	var failure *wikiStageFailure
	if !errors.As(err, &failure) || failure.Stage != "wiki_candidate_slug" || failure.Outcome != wikiOutcomeFailed {
		t.Fatalf("a truncated candidate answer must fail the candidate stage, got %v", err)
	}
	if !errors.Is(err, errWikiOutputTruncated) {
		t.Fatalf("the failure must say the output was truncated, got %v", err)
	}
	if len(model.citations) != 0 {
		t.Fatalf("no citation call may follow a failed candidate stage, got %d", len(model.citations))
	}
}
