package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/hibiken/asynq"
	"github.com/sirupsen/logrus"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

type wikiCancelQueue struct {
	interfaces.TaskPendingOpsRepository
	interfaces.TaskPendingOpsExecutionStore
	interfaces.TaskPendingOpsRetryStore
	followups int
}

// Exercise real claim timestamps even though the service uses its Lite lock.
func (p *wikiCancelQueue) PeekBatch(
	ctx context.Context, task, scope, id string, limit int,
) ([]*types.TaskPendingOp, error) {
	return p.ClaimBatch(ctx, task, scope, id, limit, time.Now().Add(-time.Hour))
}

func (p *wikiCancelQueue) PendingCount(context.Context, string, string, string) (int64, error) {
	p.followups++
	return 0, nil
}

type wikiCancelSlots struct {
	interfaces.KnowledgeRepository
	calls atomic.Int32
}

func (r *wikiCancelSlots) FinalizeSubtask(context.Context, string) (int, bool, error) {
	r.calls.Add(1)
	return 0, true, nil
}

type wikiCancelPages struct {
	wikiOutcomePages
	mu    sync.Mutex
	pages map[string]*types.WikiPage
}

func (p *wikiCancelPages) GetPageBySlug(_ context.Context, _, slug string) (*types.WikiPage, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.pages[slug], nil
}

func (p *wikiCancelPages) CreatePage(_ context.Context, page *types.WikiPage) (*types.WikiPage, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.pages[page.Slug] = page
	return page, nil
}

func (*wikiCancelPages) UpdatePageMeta(context.Context, *types.WikiPage) error { return nil }
func (*wikiCancelPages) ListDistinctCategoryPaths(context.Context, string, int) ([][]string, error) {
	return nil, nil
}

func (*wikiCancelPages) ListBySlugs(context.Context, string, []string) (map[string]*types.WikiPageLite, error) {
	return nil, nil
}

func (*wikiCancelPages) ListSummariesByKnowledgeIDs(context.Context, string, []string) (map[string]string, error) {
	return nil, nil
}

type wikiCancelChunks struct{ wikiOutcomeChunks }

func (c wikiCancelChunks) ListChunksByID(ctx context.Context, tenant uint64, _ []string) ([]*types.Chunk, error) {
	return c.ListChunksByKnowledgeID(ctx, tenant, "source")
}

type wikiCancelBatchModel struct {
	templateCaptureChatModel
	cancel       context.CancelCauseFunc
	pages        atomic.Int32
	candidateKey string // written by the only candidate call, read after batch joins
	citationKey  string
	summaryError string
	summaryCalls atomic.Int32
}

func wikiCancelRequestKey(modelID string, messages []chat.Message, opts *chat.ChatOptions) string {
	b, _ := json.Marshal(struct {
		Messages []chat.Message    `json:"messages"`
		Options  *chat.ChatOptions `json:"options"`
	}{messages, opts})
	return chat.BuildPromptCacheKey(1, modelID, "wiki_exact_request", chat.FingerprintPromptPrefix(string(b)))
}

func (m *wikiCancelBatchModel) Chat(
	ctx context.Context, messages []chat.Message, opts *chat.ChatOptions,
) (*types.ChatResponse, error) {
	purpose, _ := types.LLMCallMetadataFromContext(ctx)
	content := ""
	switch purpose {
	case "wiki_candidate_slug":
		m.candidateKey = wikiCancelRequestKey(m.GetModelID(), messages, opts)
		content = `{"entities":[],"concepts":[` +
			`{"name":"Loan","slug":"concept/loan","description":"Loan rules","details":"Rules"}]}`
	case "wiki_chunk_citation":
		m.citationKey = wikiCancelRequestKey(m.GetModelID(), messages, opts)
		content = `{"citations":{"concept/loan":["c000"]},"new_slugs":[]}`
	case "wiki_summary":
		m.summaryCalls.Add(1)
		if m.summaryError == wikiOutcomeUnknown {
			return nil, io.ErrUnexpectedEOF
		}
		if m.summaryError == wikiOutcomeFailed {
			return &types.ChatResponse{}, nil
		}
		content = "SUMMARY: Policy\nPolicy summary."
	case "wiki_taxonomy_plan":
		if m.cancel != nil {
			m.cancel(errors.New("fixture batch shutdown"))
			return nil, ctx.Err()
		}
		content = `{"assignments":[]}`
	case "wiki_page_modify":
		m.pages.Add(1)
		return nil, io.ErrUnexpectedEOF
	default:
		return nil, errors.New("unexpected fixture purpose: " + purpose)
	}
	return &types.ChatResponse{Content: content, FinishReason: "stop"}, nil
}

func wikiCancelFixture(
	t *testing.T, model *wikiCancelBatchModel,
) (*wikiIngestService, *gorm.DB, *wikiCancelQueue, *wikiCancelSlots, *asynq.Task) {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	sqlDB.SetMaxOpenConns(1)
	t.Cleanup(func() { _ = sqlDB.Close() })
	if err := db.AutoMigrate(&types.TaskPendingOp{}, &types.TaskDeadLetter{}); err != nil {
		t.Fatal(err)
	}
	repo := repository.NewTaskPendingOpsRepository(db)
	pending := &wikiCancelQueue{
		TaskPendingOpsRepository: repo, TaskPendingOpsExecutionStore: repo.(interfaces.TaskPendingOpsExecutionStore),
		TaskPendingOpsRetryStore: repo.(interfaces.TaskPendingOpsRetryStore),
	}
	if err := repo.Enqueue(context.Background(), executionRow(1, "")); err != nil {
		t.Fatal(err)
	}
	slots := &wikiCancelSlots{}
	svc := &wikiIngestService{
		config: &config.Config{}, kbService: wikiExecutionKB{}, modelService: wikiExecutionModels{model: model},
		pendingRepo: pending, knowledgeSvc: wikiOutcomeKnowledge{}, knowledgeRepo: slots,
		chunkRepo: wikiCancelChunks{}, wikiService: &wikiCancelPages{pages: map[string]*types.WikiPage{}},
		task: &wikiGuardTaskQueue{},
	}
	payload, _ := json.Marshal(WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"})
	return svc, db, pending, slots, asynq.NewTask(types.TypeWikiIngest, payload)
}

func TestWikiCancelledBatchReleasesUnsentPagesWithoutFinalizing(t *testing.T) {
	var logs bytes.Buffer
	log := logrus.New()
	log.SetOutput(&logs)
	logCtx := context.WithValue(context.Background(), types.LoggerContextKey, logrus.NewEntry(log))
	ctx, cancel := context.WithCancelCause(logCtx)
	defer cancel(nil)
	model := &wikiCancelBatchModel{cancel: cancel}
	svc, db, pending, slots, task := wikiCancelFixture(t, model)
	if err := svc.ProcessWikiIngest(ctx, task); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled task must use existing retry budget: %v", err)
	}
	var rows []types.TaskPendingOp
	if err := db.Where("task_type = ?", wikiTaskType).Find(&rows).Error; err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 || rows[0].ClaimedAt != nil || strings.Contains(string(rows[0].Payload), "execution_id") {
		t.Fatalf("unsent operation not released: %+v", rows)
	}
	var dead int64
	if err := db.Model(&types.TaskDeadLetter{}).Count(&dead).Error; err != nil {
		t.Fatal(err)
	}
	if dead != 0 || slots.calls.Load() != 0 || model.pages.Load() != 0 || pending.followups != 0 {
		t.Fatalf("unsafe cancelled batch effects: dead=%d finalized=%d sent=%d followup=%d",
			dead, slots.calls.Load(), model.pages.Load(), pending.followups)
	}
	if strings.Contains(logs.String(), "status=success") || !strings.Contains(logs.String(), "fixture batch shutdown") {
		t.Fatalf("batch status/cause missing: %s", logs.String())
	}
	// A completed NOT_RUN result from another coalesced execution must also
	// retry when this batch's own context remains live. Producer races are
	// exercised separately by TestWikiSharedRequestUnsentCancellationCannotDispatch.
	request := &wikiLLMRequest{done: make(chan struct{}), err: &wikiStageFailure{
		Stage: wikiPromptPurpose(agent.WikiCandidateSlugPrompt), Outcome: wikiOutcomeNotRun, Cause: context.Canceled,
	}}
	close(request.done)
	svc.llmRequests.Store(model.candidateKey, request)
	live := context.Background()
	if err := svc.ProcessWikiIngest(live, task); err == nil || live.Err() != nil {
		t.Fatalf("shared NOT_RUN must retain task retry budget with live parent: %v", err)
	}
	if pending.followups != 0 || slots.calls.Load() != 0 {
		t.Fatal("shared cancellation created a new retry owner or drained the knowledge slot")
	}
	reclaimed, err := pending.ClaimBatch(live, wikiTaskType, wikiTaskScope, "kb", 1, time.Now().Add(-time.Hour))
	if err != nil || len(reclaimed) != 1 {
		t.Fatalf("released operation cannot be claimed again: rows=%v err=%v", reclaimed, err)
	}
	ops, _ := svc.decodePendingRows(live, reclaimed)
	if err := svc.beginWikiOperations(live, WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"}, ops); err != nil {
		t.Fatal(err)
	}
	if ops[0].recoveryBlocked {
		t.Fatal("released execution was quarantined on next claim")
	}
}

func TestWikiSentPageFailureStillArchivesUnknown(t *testing.T) {
	model := &wikiCancelBatchModel{}
	svc, db, _, slots, task := wikiCancelFixture(t, model)
	if err := svc.ProcessWikiIngest(context.Background(), task); err != nil {
		t.Fatal(err)
	}
	var dead []types.TaskDeadLetter
	if err := db.Find(&dead).Error; err != nil {
		t.Fatal(err)
	}
	if model.pages.Load() != 1 || len(dead) != 1 ||
		!strings.Contains(dead[0].LastError, wikiOutcomeUnknown) || slots.calls.Load() != 1 {
		t.Fatalf("sent failure must archive: sent=%d dead=%+v finalize=%d",
			model.pages.Load(), dead, slots.calls.Load())
	}
	if err := svc.ProcessWikiIngest(context.Background(), task); err != nil {
		t.Fatal(err)
	}
	if model.pages.Load() != 1 {
		t.Fatal("unknown page request was resent")
	}
}

func TestWikiMixedParallelMapFailuresCannotReleaseForReplay(t *testing.T) {
	// Capture the real citation request key from a complete map pass.
	first := &wikiCancelBatchModel{}
	firstSvc, _, _, _, task := wikiCancelFixture(t, first)
	if err := firstSvc.ProcessWikiIngest(context.Background(), task); err != nil {
		t.Fatal(err)
	}
	if first.citationKey == "" {
		t.Fatal("fixture did not run citation")
	}
	for _, summaryOutcome := range []string{wikiOutcomeUnknown, wikiOutcomeFailed} {
		t.Run(summaryOutcome, func(t *testing.T) {
			model := &wikiCancelBatchModel{summaryError: summaryOutcome}
			svc, db, _, slots, task := wikiCancelFixture(t, model)
			shared := &wikiLLMRequest{done: make(chan struct{}), err: &wikiStageFailure{
				Stage: "wiki_chunk_citation", Outcome: wikiOutcomeNotRun, Cause: context.Canceled,
			}}
			close(shared.done)
			svc.llmRequests.Store(first.citationKey, shared)
			if err := svc.ProcessWikiIngest(context.Background(), task); err != nil {
				t.Fatalf("mixed failure must archive, not request replay: %v", err)
			}
			var dead []types.TaskDeadLetter
			if err := db.Find(&dead).Error; err != nil {
				t.Fatal(err)
			}
			if len(dead) != 1 || !strings.Contains(dead[0].LastError, summaryOutcome) ||
				model.summaryCalls.Load() != 1 || model.pages.Load() != 0 || slots.calls.Load() != 1 {
				t.Fatalf("parallel summary failure was discarded: outcome=%s dead=%+v", summaryOutcome, dead)
			}
			if err := svc.ProcessWikiIngest(context.Background(), task); err != nil {
				t.Fatal(err)
			}
			if model.summaryCalls.Load() != 1 {
				t.Fatal("sent summary was replayed after a mixed map failure")
			}
		})
	}
}

type wikiReleaseRecorder struct {
	*wikiExecutionPending
	releases int
	reject   bool
}

// v0.9.0 retry budget: a released not-run op counts one failed attempt first.
func (p *wikiReleaseRecorder) IncrFailCount(context.Context, int64) (int, error) { return 1, nil }

func (p *wikiReleaseRecorder) ReleaseOperation(context.Context, *types.TaskPendingOp, string) (bool, error) {
	p.releases++
	return !p.reject, nil
}

func TestWikiNotRunSettlementRequiresWholeCohort(t *testing.T) {
	for _, outcome := range []string{wikiOutcomeNotRun, wikiOutcomeFailed, wikiOutcomeUnknown} {
		for _, reject := range []bool{false, true} {
			pending := &wikiReleaseRecorder{wikiExecutionPending: &wikiExecutionPending{}, reject: reject}
			slots := &wikiCancelSlots{}
			svc := &wikiIngestService{pendingRepo: pending, knowledgeRepo: slots}
			op := WikiPendingOp{
				Op: WikiOpIngest, KnowledgeID: "source", ExecutionID: "sent",
				queueRows: []*types.TaskPendingOp{executionRow(1, "sent"), executionRow(2, "sent")},
				failure: errors.Join(
					&wikiStageFailure{Outcome: wikiOutcomeNotRun}, &wikiStageFailure{Outcome: outcome}),
			}
			payload := WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"}
			err := svc.settleWikiOperation(context.Background(), payload, op)
			if outcome == wikiOutcomeNotRun {
				if (err != nil) != reject || pending.releases != 2 ||
					pending.archiveCalls != 0 || slots.calls.Load() != 0 {
					t.Fatalf("NOT_RUN cohort: err=%v released=%d archived=%d finalized=%d",
						err, pending.releases, pending.archiveCalls, slots.calls.Load())
				}
			} else if err != nil || pending.releases != 0 || pending.archiveCalls != 2 || slots.calls.Load() != 1 {
				t.Fatalf("mixed outcomes must archive: outcome=%s err=%v", outcome, err)
			}
		}
	}
}
