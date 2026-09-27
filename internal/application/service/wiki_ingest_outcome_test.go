package service

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type wikiOutcomeKnowledge struct{ interfaces.KnowledgeService }

func (wikiOutcomeKnowledge) GetKnowledgeByIDOnly(context.Context, string) (*types.Knowledge, error) {
	return &types.Knowledge{ID: "source", Title: "Policy", ParseStatus: types.ParseStatusFinalizing}, nil
}

type wikiOutcomeChunks struct{ interfaces.ChunkRepository }

func (wikiOutcomeChunks) ListChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error) {
	return []*types.Chunk{{ID: "chunk-1", KnowledgeID: "source", Content: strings.Repeat("A loan has eligibility requirements, limits and exceptions. ", 4), ChunkType: types.ChunkTypeText}}, nil
}

func (wikiOutcomeChunks) ListChunksByParentIDs(context.Context, uint64, []string) ([]*types.Chunk, error) {
	return nil, nil
}

type wikiOutcomePages struct {
	interfaces.WikiPageService
	writes int
}

func (*wikiOutcomePages) GetPageBySlug(context.Context, string, string) (*types.WikiPage, error) {
	return nil, nil
}
func (p *wikiOutcomePages) CreatePage(_ context.Context, page *types.WikiPage) (*types.WikiPage, error) {
	p.writes++
	return page, nil
}

func (wikiOutcomePages) ListSlugsBySourceRef(context.Context, string, string) ([]string, error) {
	return nil, nil
}
func (wikiOutcomePages) FindSimilarPages(context.Context, string, string, []string, int) ([]*types.WikiPageLite, error) {
	return nil, nil
}

type wikiCitationFailureModel struct{ templateCaptureChatModel }

func (*wikiCitationFailureModel) Chat(ctx context.Context, _ []chat.Message, _ *chat.ChatOptions) (*types.ChatResponse, error) {
	purpose, _ := types.LLMCallMetadataFromContext(ctx)
	switch purpose {
	case wikiPromptPurpose(agent.WikiCandidateSlugPrompt):
		return &types.ChatResponse{Content: `{"entities":[],"concepts":[{"name":"Loan","slug":"concept/loan","description":"Loan rules","details":"A short outline"}]}`}, nil
	case wikiPromptPurpose(agent.WikiChunkCitationPrompt):
		return nil, io.EOF
	default:
		return &types.ChatResponse{Content: "SUMMARY: Policy\nPolicy summary."}, nil
	}
}

func TestMapOneDocumentDoesNotUseShortDetailsWhenCitationIncomplete(t *testing.T) {
	svc := &wikiIngestService{knowledgeSvc: wikiOutcomeKnowledge{}, chunkRepo: wikiOutcomeChunks{}, wikiService: &wikiOutcomePages{}}
	result, updates, err := svc.mapOneDocument(context.Background(), &wikiCitationFailureModel{}, WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"}, WikiPendingOp{Op: WikiOpIngest, KnowledgeID: "source"}, wikiOutcomeBatchContext())
	if err == nil || result != nil || len(updates) != 0 {
		t.Fatalf("citation failure must stop page generation, got result=%+v updates=%d error=%v", result, len(updates), err)
	}
}

func wikiOutcomeBatchContext() *WikiBatchContext {
	return &WikiBatchContext{
		SummaryContentByKnowledgeID: func(context.Context, string) string { return "" },
		SlugTitleMany:               func(context.Context, []string) map[string]string { return nil },
	}
}

func TestReduceSlugUpdatesReportsGenerationFailure(t *testing.T) {
	pages := &wikiOutcomePages{}
	model := &interruptedWikiChatModel{}
	svc := &wikiIngestService{knowledgeSvc: wikiOutcomeKnowledge{}, wikiService: pages}
	changed, _, failed, err := svc.reduceSlugUpdates(context.Background(), model, "kb", "concept/loan", []SlugUpdate{{
		Slug: "concept/loan", Type: types.WikiPageTypeConcept, KnowledgeID: "source", SourceRef: "source",
		Item: extractedItem{Name: "Loan", Slug: "concept/loan", Details: "Loan conditions"},
	}}, 1, wikiOutcomeBatchContext(), nil)
	if err == nil || changed || !failed || pages.writes != 0 {
		t.Fatalf("generation failure must remain a failure without writes: changed=%v failed=%v writes=%d error=%v", changed, failed, pages.writes, err)
	}
}

func TestMapOneDocumentDoesNotFallbackAfterUnknownDiscovery(t *testing.T) {
	model := &interruptedWikiChatModel{}
	svc := &wikiIngestService{knowledgeSvc: wikiOutcomeKnowledge{}, chunkRepo: wikiOutcomeChunks{}, wikiService: &wikiOutcomePages{}}
	result, updates, err := svc.mapOneDocument(context.Background(), model, WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"}, WikiPendingOp{Op: WikiOpIngest, KnowledgeID: "source"}, wikiOutcomeBatchContext())
	if result != nil || len(updates) != 0 || err == nil || model.calls != 1 || wikiFailureOutcome(err) != wikiOutcomeUnknown {
		t.Fatalf("unknown discovery cannot fallback: result=%v updates=%d calls=%d error=%v", result, len(updates), model.calls, err)
	}
}

type wikiCitationPeerModel struct {
	templateCaptureChatModel
	invalidJSON bool
}

func (m *wikiCitationPeerModel) Chat(_ context.Context, messages []chat.Message, _ *chat.ChatOptions) (*types.ChatResponse, error) {
	if strings.Contains(messages[0].Content, "FAILED-CHUNK") {
		if m.invalidJSON {
			return &types.ChatResponse{Content: "{broken"}, nil
		}
		return nil, io.ErrUnexpectedEOF
	}
	return &types.ChatResponse{Content: `{"citations":{"concept/loan":["c000"]},"new_slugs":[]}`}, nil
}

func TestCitationOutcomePreservesSuccessfulPeers(t *testing.T) {
	for _, invalidJSON := range []bool{false, true} {
		model := &wikiCitationPeerModel{invalidJSON: invalidJSON}
		result := (&wikiIngestService{}).classifyChunkCitations(context.Background(), model, "concept/loan", []*types.Chunk{
			{ID: "success", ChunkIndex: 0, Content: strings.Repeat("source ", 2000), ChunkType: types.ChunkTypeText},
			{ID: "failed", ChunkIndex: 1, Content: "FAILED-CHUNK", ChunkType: types.ChunkTypeText},
		}, "en", wikiOutcomeBatchContext(), nil)
		want := wikiOutcomeUnknown
		if invalidJSON {
			want = wikiOutcomeFailed
		}
		if len(result.BatchErrors) != 2 || result.BatchErrors[0] != nil || result.BatchErrors[1] == nil || wikiFailureOutcome(result.Err()) != want {
			t.Fatalf("lost per-batch status: %+v error=%v", result, result.Err())
		}
		if got := result.Citations["concept/loan"]; len(got) != 1 || got[0] != "success" {
			t.Fatalf("lost successful citation: %v", got)
		}
	}
}

func TestWikiPendingRecoveryCannotHideMarkedSibling(t *testing.T) {
	ops, _ := (&wikiIngestService{}).decodePendingRows(context.Background(), []*types.TaskPendingOp{
		{ID: 1, DedupKey: "source", Payload: []byte(`{"op":"ingest","knowledge_id":"source","execution_id":"started"}`)},
		{ID: 2, DedupKey: "source", Payload: []byte(`{"op":"ingest","knowledge_id":"source"}`)},
	})
	if len(ops) != 1 || !ops[0].recoveryBlocked || len(ops[0].queueRows) != 2 {
		t.Fatalf("latest operation must retain the marked cohort for isolation: %+v", ops)
	}
}

type wikiUnknownCitationModel struct{ templateCaptureChatModel }

func (*wikiUnknownCitationModel) Chat(context.Context, []chat.Message, *chat.ChatOptions) (*types.ChatResponse, error) {
	return &types.ChatResponse{Content: `{"citations":{"concept/loan":["c999"]},"new_slugs":[]}`}, nil
}

func TestCitationOutcomeRejectsUnknownHandle(t *testing.T) {
	result := (&wikiIngestService{}).classifyChunkCitations(context.Background(), &wikiUnknownCitationModel{}, "concept/loan", []*types.Chunk{{ID: "source", Content: "Loan rules", ChunkType: types.ChunkTypeText}}, "en", wikiOutcomeBatchContext(), nil)
	if result.Err() == nil {
		t.Fatal("unknown chunk handle must fail the batch")
	}
}

func TestCitationOutcomeEntirelyNotRun(t *testing.T) {
	result := citationClassificationOutcome{BatchErrors: []error{&wikiStageFailure{Outcome: wikiOutcomeNotRun}}}
	if got := wikiFailureOutcome(result.Err()); got != wikiOutcomeNotRun {
		t.Fatalf("unsent batches = %s, want NOT_RUN", got)
	}
}

type wikiPublishOutcomePages struct {
	interfaces.WikiPageService
	published []string
}

func (p *wikiPublishOutcomePages) GetPageBySlug(_ context.Context, _ string, slug string) (*types.WikiPage, error) {
	if slug == "read-failed" {
		return nil, errors.New("read failed")
	}
	if slug == "missing" {
		return nil, nil
	}
	return &types.WikiPage{Slug: slug, Status: types.WikiPageStatusDraft}, nil
}
func (p *wikiPublishOutcomePages) UpdatePageMeta(_ context.Context, page *types.WikiPage) error {
	if page.Slug == "write-failed" {
		return errors.New("write failed")
	}
	p.published = append(p.published, page.Slug)
	return nil
}
func TestPublishDraftPagesPreservesSuccessfulSiblingAndReportsFailures(t *testing.T) {
	pages := &wikiPublishOutcomePages{}
	svc := &wikiIngestService{wikiService: pages}
	failures := svc.publishDraftPages(context.Background(), "kb", []string{"read-failed", "ok", "missing", "write-failed"})
	if len(failures) != 3 || failures["read-failed"] == nil || failures["missing"] == nil || failures["write-failed"] == nil {
		t.Fatalf("publication errors disappeared: %v", failures)
	}
	if len(pages.published) != 1 || pages.published[0] != "ok" {
		t.Fatalf("successful sibling lost: %v", pages.published)
	}
}

func TestWikiPageFailureLedgerTracksUnwrittenAdditions(t *testing.T) {
	failures := newWikiPageFailures()
	failures.record("concept/loan", []SlugUpdate{{Type: types.WikiPageTypeConcept, KnowledgeID: "a"}, {Type: types.WikiPageTypeConcept, KnowledgeID: "b"}}, errors.New("repository unavailable"))
	failures.record("old", []SlugUpdate{{Type: "retract", KnowledgeID: "c"}}, errors.New("lock unavailable"))
	if _, ok := failures.additions["concept/loan"]; !ok {
		t.Fatal("repository failure left a missing page eligible for successful links")
	}
	if _, ok := failures.additions["old"]; ok {
		t.Fatal("retract failure does not prove existing page absent")
	}
	if len(failures.byKnowledge) != 3 || len(failures.bySlug) != 2 {
		t.Fatalf("lost contributors: %+v", failures)
	}
}
