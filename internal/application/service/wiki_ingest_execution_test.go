package service

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/hibiken/asynq"
	"strings"
	"testing"
)

type wikiExecutionKB struct {
	interfaces.KnowledgeBaseService
}

func (wikiExecutionKB) GetKnowledgeBaseByIDOnly(context.Context, string) (*types.KnowledgeBase, error) {
	return &types.KnowledgeBase{ID: "kb", TenantID: 1, SummaryModelID: "model", IndexingStrategy: types.IndexingStrategy{WikiEnabled: true}}, nil
}
func (k wikiExecutionKB) GetKnowledgeBaseByID(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	return k.GetKnowledgeBaseByIDOnly(ctx, id)
}

type wikiExecutionModels struct {
	interfaces.ModelService
	model chat.Chat
}

func (m wikiExecutionModels) GetChatModel(context.Context, string) (chat.Chat, error) {
	return m.model, nil
}

type wikiExecutionPending struct {
	interfaces.TaskPendingOpsRepository
	interfaces.TaskPendingOpsExecutionStore
	rows                     []*types.TaskPendingOp
	beginErr, archiveErr     error
	beginCalls, archiveCalls int
	completeCalls            int
	unconfirmed              bool
	afterBegin               func()
	archived                 []*types.TaskPendingOp
}

func (p *wikiExecutionPending) PeekBatch(context.Context, string, string, string, int) ([]*types.TaskPendingOp, error) {
	return p.rows, nil
}
func (*wikiExecutionPending) PendingCount(context.Context, string, string, string) (int64, error) {
	return 0, nil
}
func (p *wikiExecutionPending) BeginOperation(_ context.Context, row *types.TaskPendingOp, id string) (bool, error) {
	p.beginCalls++
	if p.beginErr != nil {
		return false, p.beginErr
	}
	var payload map[string]interface{}
	_ = json.Unmarshal(row.Payload, &payload)
	payload["execution_id"] = id
	row.Payload, _ = json.Marshal(payload)
	if p.afterBegin != nil {
		f := p.afterBegin
		p.afterBegin = nil
		f()
	}
	return true, nil
}
func (p *wikiExecutionPending) CompleteOperation(context.Context, *types.TaskPendingOp, string) (bool, error) {
	p.completeCalls++
	return !p.unconfirmed, nil
}
func (p *wikiExecutionPending) ArchiveOperation(_ context.Context, row *types.TaskPendingOp, _ string, _ *types.TaskDeadLetter) (bool, error) {
	p.archiveCalls++
	if p.archiveErr == nil && !p.unconfirmed {
		p.archived = append(p.archived, row)
		kept := p.rows[:0]
		for _, current := range p.rows {
			if current.ID != row.ID {
				kept = append(kept, current)
			}
		}
		p.rows = kept
	}
	return p.archiveErr == nil && !p.unconfirmed, p.archiveErr
}
func executionRow(id int64, marker string) *types.TaskPendingOp {
	payload, _ := json.Marshal(WikiPendingOp{Op: WikiOpIngest, KnowledgeID: "source", ExecutionID: marker})
	return &types.TaskPendingOp{ID: id, TenantID: 1, TaskType: wikiTaskType, Scope: wikiTaskScope, ScopeID: "kb", DedupKey: "source", Op: WikiOpIngest, Payload: payload}
}
func runWikiExecutionTest(pending *wikiExecutionPending, model chat.Chat) error {
	svc := &wikiIngestService{config: &config.Config{}, kbService: wikiExecutionKB{}, modelService: wikiExecutionModels{model: model}, pendingRepo: pending, knowledgeSvc: wikiOutcomeKnowledge{}, chunkRepo: wikiOutcomeChunks{}, wikiService: &wikiOutcomePages{}}
	payload, _ := json.Marshal(WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"})
	return svc.ProcessWikiIngest(context.Background(), asynq.NewTask(types.TypeWikiIngest, payload))
}

func TestWikiExecutionGuardFailureSendsNothing(t *testing.T) {
	model := &interruptedWikiChatModel{}
	pending := &wikiExecutionPending{rows: []*types.TaskPendingOp{executionRow(1, "")}, beginErr: errors.New("database unavailable")}
	if err := runWikiExecutionTest(pending, model); err == nil {
		t.Fatal("guard failure must stop the task")
	}
	if model.calls != 0 || pending.archiveCalls != 0 {
		t.Fatalf("begin failure leaked effects: calls=%d archive=%d", model.calls, pending.archiveCalls)
	}
}
func TestWikiExecutionSettlementRetryDoesNotReplayModel(t *testing.T) {
	model := &interruptedWikiChatModel{}
	pending := &wikiExecutionPending{rows: []*types.TaskPendingOp{executionRow(1, "")}, archiveErr: errors.New("database unavailable")}
	if err := runWikiExecutionTest(pending, model); err == nil {
		t.Fatal("archive failure must remain visible")
	}
	if model.calls != 1 {
		t.Fatalf("initial model calls=%d", model.calls)
	}
	pending.archiveErr = nil
	if err := runWikiExecutionTest(pending, model); err != nil {
		t.Fatal(err)
	}
	if model.calls != 1 || pending.beginCalls != 1 || pending.archiveCalls != 2 {
		t.Fatalf("recovery repeated computation: calls=%d begin=%d archive=%d", model.calls, pending.beginCalls, pending.archiveCalls)
	}
}
func TestWikiExecutionRecoveryQuarantinesLateSibling(t *testing.T) {
	model := &interruptedWikiChatModel{}
	pending := &wikiExecutionPending{rows: []*types.TaskPendingOp{executionRow(1, "interrupted"), executionRow(2, "")}}
	if err := runWikiExecutionTest(pending, model); err != nil {
		t.Fatal(err)
	}
	if model.calls != 0 || pending.beginCalls != 1 || pending.archiveCalls != 2 {
		t.Fatalf("late sibling bypassed isolation: calls=%d begin=%d archive=%d", model.calls, pending.beginCalls, pending.archiveCalls)
	}
}
func TestWikiReduceFailureIsNotALockMiss(t *testing.T) {
	svc := &wikiIngestService{knowledgeSvc: wikiOutcomeKnowledge{}, wikiService: &wikiOutcomePages{}}
	failed := false
	acquired, err := svc.withSlugLock(context.Background(), "kb", "concept/loan", func() error {
		var reduceErr error
		_, _, failed, reduceErr = svc.reduceSlugUpdates(context.Background(), &interruptedWikiChatModel{}, "kb", "concept/loan", []SlugUpdate{{Slug: "concept/loan", Type: types.WikiPageTypeConcept, KnowledgeID: "source", SourceRef: "source", Item: extractedItem{Name: "Loan", Details: "Rules"}}}, 1, wikiOutcomeBatchContext(), nil)
		return reduceErr
	})
	if !acquired || !failed || err == nil {
		t.Fatalf("reduce failure lost ownership: acquired=%v failed=%v err=%v", acquired, failed, err)
	}
}

func TestWikiExecutionLegacyFailureCannotAuthorizeReplay(t *testing.T) {
	model := &interruptedWikiChatModel{}
	row := executionRow(1, "")
	row.FailCount = 1
	pending := &wikiExecutionPending{rows: []*types.TaskPendingOp{row}}
	if err := runWikiExecutionTest(pending, model); err != nil {
		t.Fatal(err)
	}
	if model.calls != 0 || pending.archiveCalls != 1 {
		t.Fatalf("legacy failed operation replayed: calls=%d archive=%d", model.calls, pending.archiveCalls)
	}
}

type wikiFinalizeRecorder struct {
	interfaces.KnowledgeRepository
	revisionRepository
	calls   int
	binding types.RevisionCommitBinding
}

func (r *wikiFinalizeRecorder) FinalizeSubtaskRevision(_ context.Context, _ string, binding types.RevisionCommitBinding) (int, bool, error) {
	r.calls++
	r.binding = binding
	return 0, true, nil
}

func TestWikiSettlementConfirmsWholeCohortBeforeFinalizing(t *testing.T) {
	pending := &wikiExecutionPending{}
	finalize := &wikiFinalizeRecorder{}
	svc := &wikiIngestService{pendingRepo: pending, knowledgeRepo: finalize}
	rows := []*types.TaskPendingOp{executionRow(1, ""), executionRow(2, "")}
	ops, _ := svc.decodePendingRows(context.Background(), rows)
	ops[0].Revision = &types.RevisionCommitBinding{ParseAttempt: 7, FileSHA256: "bound-source"}
	payload := WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"}
	if err := svc.beginWikiOperations(context.Background(), payload, ops); err != nil {
		t.Fatal(err)
	}
	if err := svc.settleWikiOperation(context.Background(), payload, ops[0]); err != nil {
		t.Fatal(err)
	}
	if pending.beginCalls != 2 || pending.completeCalls != 2 || finalize.calls != 1 || finalize.binding.ParseAttempt != 7 {
		t.Fatalf("wrong cohort settlement: begin=%d complete=%d finalize=%d binding=%+v", pending.beginCalls, pending.completeCalls, finalize.calls, finalize.binding)
	}
}
func TestWikiSettlementCASMissCannotReportCompletion(t *testing.T) {
	for _, failed := range []bool{false, true} {
		pending := &wikiExecutionPending{unconfirmed: true}
		finalize := &wikiFinalizeRecorder{}
		svc := &wikiIngestService{pendingRepo: pending, knowledgeRepo: finalize}
		op := WikiPendingOp{Op: WikiOpIngest, KnowledgeID: "source", ExecutionID: "started", queueRows: []*types.TaskPendingOp{executionRow(1, "started")}}
		if failed {
			op.failure = &wikiStageFailure{Outcome: wikiOutcomeUnknown}
		}
		err := svc.settleWikiOperation(context.Background(), WikiIngestPayload{TenantID: 1, KnowledgeBaseID: "kb"}, op)
		if err == nil || finalize.calls != 0 {
			t.Fatalf("CAS miss cannot complete: failed=%v err=%v finalized=%d", failed, err, finalize.calls)
		}
	}
}

func TestWikiExecutionTrueLateDuplicateCannotReplayUnknown(t *testing.T) {
	model := &interruptedWikiChatModel{}
	pending := &wikiExecutionPending{rows: []*types.TaskPendingOp{executionRow(1, "")}}
	pending.afterBegin = func() { pending.rows = append(pending.rows, executionRow(2, "")) }
	if err := runWikiExecutionTest(pending, model); err != nil {
		t.Fatal(err)
	}
	if len(pending.rows) != 1 || pending.rows[0].ID != 2 || len(pending.archived) != 1 {
		t.Fatal("fixture did not enqueue after begin and settle original row")
	}
	if err := runWikiExecutionTest(pending, model); err != nil {
		t.Fatal(err)
	}
	if model.calls != 1 {
		t.Fatalf("same revision unknown replayed by late notification: %d calls", model.calls)
	}
}
func TestWikiRecoveryMarkerDoesNotQuarantineNewRevision(t *testing.T) {
	first, second := executionRow(1, "started"), executionRow(2, "")
	for i, row := range []*types.TaskPendingOp{first, second} {
		var op WikiPendingOp
		_ = json.Unmarshal(row.Payload, &op)
		op.Revision = &types.RevisionCommitBinding{ParseAttempt: int64(i + 1), FileSHA256: strings.Repeat("a", 64)}
		row.Payload, _ = json.Marshal(op)
	}
	ops, _ := (&wikiIngestService{}).decodePendingRows(context.Background(), []*types.TaskPendingOp{first, second})
	if len(ops) != 2 {
		t.Fatalf("old unknown and newer revision need separate settlement: %+v", ops)
	}
	if !ops[0].recoveryBlocked || ops[1].recoveryBlocked || len(ops[0].queueRows) != 1 || len(ops[1].queueRows) != 1 {
		t.Fatalf("revision isolation lost: %+v", ops)
	}
}

func (p *wikiExecutionPending) HasFailedOperation(_ context.Context, row *types.TaskPendingOp) (bool, error) {
	var current WikiPendingOp
	_ = json.Unmarshal(row.Payload, &current)
	for _, old := range p.archived {
		var prior WikiPendingOp
		_ = json.Unmarshal(old.Payload, &prior)
		if prior.Op != current.Op {
			continue
		}
		if prior.Revision == nil && current.Revision == nil {
			return true, nil
		}
		if prior.Revision != nil && current.Revision != nil && *prior.Revision == *current.Revision {
			return true, nil
		}
	}
	return false, nil
}

func TestWikiExecutionNewRevisionRunsBesideOldRecovery(t *testing.T) {
	old, next := executionRow(1, "started"), executionRow(2, "")
	for i, row := range []*types.TaskPendingOp{old, next} {
		var op WikiPendingOp
		_ = json.Unmarshal(row.Payload, &op)
		op.Revision = &types.RevisionCommitBinding{ParseAttempt: int64(i + 1), FileSHA256: strings.Repeat("a", 64)}
		row.Payload, _ = json.Marshal(op)
	}
	model := &interruptedWikiChatModel{}
	pending := &wikiExecutionPending{rows: []*types.TaskPendingOp{old, next}}
	if err := runWikiExecutionTest(pending, model); err != nil {
		t.Fatal(err)
	}
	if model.calls != 1 || pending.archiveCalls != 2 {
		t.Fatalf("new revision blocked or old revision replayed: calls=%d archives=%d", model.calls, pending.archiveCalls)
	}
}

func revisionExecutionRow(id, attempt int64, marker string) *types.TaskPendingOp {
	row := executionRow(id, marker)
	var op WikiPendingOp
	_ = json.Unmarshal(row.Payload, &op)
	op.Revision = &types.RevisionCommitBinding{ParseAttempt: attempt, FileSHA256: strings.Repeat("a", 64)}
	row.Payload, _ = json.Marshal(op)
	return row
}
func TestWikiRevisionSelectionIgnoresLateArrivalOrder(t *testing.T) {
	for _, archived := range []bool{false, true} {
		pending := &wikiExecutionPending{}
		if archived {
			pending.archived = []*types.TaskPendingOp{revisionExecutionRow(1, 1, "sent")}
		} else {
			pending.rows = []*types.TaskPendingOp{revisionExecutionRow(1, 1, "sent")}
		}
		pending.rows = append(pending.rows, revisionExecutionRow(2, 2, ""), revisionExecutionRow(3, 1, ""))
		model := &interruptedWikiChatModel{}
		if err := runWikiExecutionTest(pending, model); err != nil {
			t.Fatal(err)
		}
		if model.calls != 1 {
			t.Fatalf("new R2 must run once despite late R1; archived=%v calls=%d", archived, model.calls)
		}
	}
}
func TestWikiRevisionSelectionRejectsConflictsAndMalformedInputs(t *testing.T) {
	first := revisionExecutionRow(1, 2, "")
	conflict := revisionExecutionRow(2, 2, "")
	var different WikiPendingOp
	_ = json.Unmarshal(conflict.Payload, &different)
	different.Revision.ParserIdentity.ParserEngine = "different"
	conflict.Payload, _ = json.Marshal(different)
	model := &interruptedWikiChatModel{}
	if err := runWikiExecutionTest(&wikiExecutionPending{rows: []*types.TaskPendingOp{first, conflict}}, model); err != nil {
		t.Fatal(err)
	}
	if model.calls != 0 {
		t.Fatalf("conflicting same-attempt inputs sent %d model calls", model.calls)
	}
	invalid := revisionExecutionRow(4, 999, "")
	_ = json.Unmarshal(invalid.Payload, &different)
	different.Revision.FileSHA256 = "invalid"
	invalid.Payload, _ = json.Marshal(different)
	ops, _ := (&wikiIngestService{}).decodePendingRows(context.Background(), []*types.TaskPendingOp{revisionExecutionRow(3, 3, ""), invalid})
	if len(ops) != 2 || ops[0].recoveryBlocked || !ops[1].recoveryBlocked {
		t.Fatalf("malformed high attempt hid valid input: %+v", ops)
	}
}
func TestWikiRevisionSelectionNeverFallsBackOrCrossesRetraction(t *testing.T) {
	svc := &wikiIngestService{}
	ops, _ := svc.decodePendingRows(context.Background(), []*types.TaskPendingOp{revisionExecutionRow(1, 2, "sent"), revisionExecutionRow(2, 1, "")})
	for _, op := range ops {
		if !op.recoveryBlocked {
			t.Fatal("unknown newer input authorized old input")
		}
	}
	retract := executionRow(4, "")
	var op WikiPendingOp
	_ = json.Unmarshal(retract.Payload, &op)
	op.Op = WikiOpRetract
	retract.Op = WikiOpRetract
	retract.Payload, _ = json.Marshal(op)
	ops, _ = svc.decodePendingRows(context.Background(), []*types.TaskPendingOp{revisionExecutionRow(3, 2, ""), retract, revisionExecutionRow(5, 1, "")})
	if len(ops) != 1 || ops[0].Op != WikiOpRetract {
		t.Fatalf("late ingest crossed delete barrier: %+v", ops)
	}
}
