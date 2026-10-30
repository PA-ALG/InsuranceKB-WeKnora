package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"sync"
	"syscall"

	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/models/api"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/google/uuid"
)

const (
	wikiOutcomeFailed  = "FAILED"
	wikiOutcomeUnknown = "OUTCOME_UNKNOWN"
	wikiOutcomeNotRun  = "NOT_RUN"
)

// wikiStageFailure is the native pipeline's failure contract. It deliberately
// does not infer safe replay from provider error text. Error exposes a stable,
// safe description; Unwrap retains the cause for diagnostics and cancellation.
type wikiStageFailure struct {
	Stage   string
	Outcome string
	Cause   error
}

func (e *wikiStageFailure) Error() string { return fmt.Sprintf("%s: %s", e.Stage, e.Outcome) }
func (e *wikiStageFailure) Unwrap() error { return e.Cause }

// wikiLookupStage marks a failed source-document lookup. No model work was
// sent, so it is NOT_RUN; unlike a cancelled batch it is an attempt of this op
// and spends upstream's retry budget (v0.9.0), also when the lookup was
// interrupted.
const wikiLookupStage = "wiki_lookup"

func wikiLookupFailed(err error) error {
	return &wikiStageFailure{Stage: wikiLookupStage, Outcome: wikiOutcomeNotRun, Cause: err}
}

// wikiBudgetRetries is how many of a queue row's failures were budgeted
// retries of never-run attempts (TaskPendingOpsBudgetStore). Failures beyond
// it are legacy and cannot authorize replay.
func wikiBudgetRetries(row *types.TaskPendingOp) int {
	var marker struct {
		BudgetRetries int `json:"budget_retries"`
	}
	if len(row.Payload) == 0 || json.Unmarshal(row.Payload, &marker) != nil {
		return 0
	}
	return marker.BudgetRetries
}

func isWikiLookupFailure(err error) bool {
	var failure *wikiStageFailure
	return errors.As(err, &failure) && failure.Stage == wikiLookupStage
}

func wikiFailureOutcome(err error) string {
	if err == nil {
		return wikiOutcomeNotRun
	}
	if joined, ok := err.(interface{ Unwrap() []error }); ok {
		result := wikiOutcomeNotRun
		for _, child := range joined.Unwrap() {
			state := wikiFailureOutcome(child)
			if state == wikiOutcomeUnknown {
				return state
			}
			if state == wikiOutcomeFailed {
				result = state
			}
		}
		return result
	}
	if failure, ok := err.(*wikiStageFailure); ok {
		return failure.Outcome
	}
	if wrapped, ok := err.(interface{ Unwrap() error }); ok {
		return wikiFailureOutcome(wrapped.Unwrap())
	}
	return wikiOutcomeFailed
}

// wikiLLMRequest shares dispatch state as well as the result. Cancellation and
// the dispatch boundary use the same lock: a NOT_RUN answer must prevent a
// delayed worker from sending afterwards. The entry is never a result cache.
type wikiLLMRequest struct {
	mu     sync.Mutex
	sent   bool
	ctx    context.Context
	cancel context.CancelCauseFunc
	done   chan struct{}
	result wikiTemplateResult
	err    error
}

func (r *wikiLLMRequest) beginDispatch(stage string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if err := r.ctx.Err(); err != nil {
		return r.cancellationFailure(stage, err)
	}
	r.sent = true
	return nil
}

func (r *wikiLLMRequest) cancellationFailure(stage string, cause error) error {
	outcome := wikiOutcomeNotRun
	if r.sent {
		outcome = wikiOutcomeUnknown
	}
	return &wikiStageFailure{Stage: stage, Outcome: outcome, Cause: cause}
}

func (r *wikiLLMRequest) cancelled(stage string, cause error) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if !r.sent {
		r.cancel(cause)
	}
	return r.cancellationFailure(stage, cause)
}

func wikiFailureCauseCategory(err error) string {
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return "deadline exceeded"
	case errors.Is(err, context.Canceled):
		return "context canceled"
	case wikiFailureOutcome(err) == wikiOutcomeUnknown:
		return "transport error"
	default:
		return "generation failure"
	}
}

// wikiTransportDetail exposes only a category: provider error bodies and
// wrapper messages can contain credentials or echoed request material.
func wikiTransportDetail(err error) string {
	var httpErr *api.HTTPError
	if errors.As(err, &httpErr) {
		return fmt.Sprintf("http %d", httpErr.StatusCode)
	}
	if wikiTransportTimeout(err) {
		return "timeout"
	}
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) ||
		errors.Is(err, syscall.ECONNRESET) || errors.Is(err, syscall.EPIPE) {
		return "connection closed"
	}
	return "other"
}

func wikiTransportTimeout(err error) bool {
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return true
	}
	// A non-timeout net.Error can precede a timeout in a joined chain, or
	// wrap it without forwarding Timeout. Inspect the remaining causes too.
	switch wrapped := err.(type) {
	case interface{ Unwrap() []error }:
		for _, child := range wrapped.Unwrap() {
			if wikiTransportTimeout(child) {
				return true
			}
		}
	case interface{ Unwrap() error }:
		return wikiTransportTimeout(wrapped.Unwrap())
	}
	return false
}

func (s *wikiIngestService) runWikiRequest(
	ctx context.Context, key string, shared bool, stage string,
	execute func(context.Context, *wikiLLMRequest) (wikiTemplateResult, error),
) (result wikiTemplateResult, err error) {
	defer func() {
		if err != nil {
			cause := wikiFailureCauseCategory(err)
			if cause == "transport error" {
				logger.Warnf(ctx, "wiki ingest: call failed stage=%s outcome=%s cause=%s detail=%s",
					stage, wikiFailureOutcome(err), cause, wikiTransportDetail(err))
				return
			}
			logger.Warnf(ctx, "wiki ingest: call failed stage=%s outcome=%s cause=%s",
				stage, wikiFailureOutcome(err), cause)
		}
	}()
	if err := ctx.Err(); err != nil {
		return result, &wikiStageFailure{Stage: stage, Outcome: wikiOutcomeNotRun, Cause: err}
	}
	if !shared {
		// Preserve synchronous result ownership for independent calls, including
		// known truncated responses returned while the parent is being cancelled.
		runCtx, cancel := context.WithCancelCause(ctx)
		defer cancel(nil)
		return execute(runCtx, &wikiLLMRequest{ctx: runCtx, cancel: cancel})
	}
	var request *wikiLLMRequest
	if existing, ok := s.llmRequests.Load(key); ok {
		request = existing.(*wikiLLMRequest)
	}
	if request == nil {
		runCtx, cancel := context.WithCancelCause(ctx)
		request = &wikiLLMRequest{ctx: runCtx, cancel: cancel, done: make(chan struct{})}
		actual, loaded := s.llmRequests.LoadOrStore(key, request)
		if loaded {
			cancel(nil)
			request = actual.(*wikiLLMRequest)
		}
		if !loaded {
			go func() {
				request.result, request.err = execute(request.ctx, request)
				request.cancel(nil)
				s.llmRequests.CompareAndDelete(key, request)
				close(request.done)
			}()
		}
	}
	select {
	case <-request.done:
		return request.result, request.err
	case <-ctx.Done():
		// Prefer a known, completed result over an uncertain cancellation.
		select {
		case <-request.done:
			return request.result, request.err
		default:
			return result, request.cancelled(stage, ctx.Err())
		}
	}
}

// beginWikiOperations marks the whole selected cohort before any model work.
// A late unmarked sibling cannot hide an interrupted execution. On any CAS
// error, no operations run or archive; recovery sees all markers that committed.
func (s *wikiIngestService) beginWikiOperations(ctx context.Context, payload WikiIngestPayload, ops []WikiPendingOp) error {
	store, ok := s.pendingRepo.(interfaces.TaskPendingOpsExecutionStore)
	if !ok {
		return errors.New("wiki execution guard unavailable")
	}
	for i := range ops {
		op := &ops[i]
		if len(op.queueRows) == 0 {
			return errors.New("wiki execution has no persisted claim")
		}
		if op.ExecutionID == "" {
			op.ExecutionID = uuid.NewString()
		}
		for _, row := range op.queueRows {
			if row.TenantID != payload.TenantID || row.TaskType != wikiTaskType || row.Scope != wikiTaskScope || row.ScopeID != payload.KnowledgeBaseID || row.DedupKey != op.KnowledgeID {
				return errors.New("wiki execution claim scope mismatch")
			}
			var fields map[string]json.RawMessage
			if err := json.Unmarshal(row.Payload, &fields); err != nil {
				return err
			}
			var executionID string
			if err := json.Unmarshal(fields["execution_id"], &executionID); len(fields["execution_id"]) != 0 && err != nil {
				return err
			}
			if executionID != "" {
				op.recoveryBlocked = true
				continue
			}
			accepted, err := store.BeginOperation(ctx, row, op.ExecutionID)
			if err != nil {
				return err
			}
			if !accepted {
				return errors.New("wiki execution claim superseded")
			}
			fields["execution_id"], _ = json.Marshal(op.ExecutionID)
			// This is local claim metadata only; the repo's JSON update preserves the
			// authoritative payload and Archive reads it under the row lock.
			row.Payload, _ = json.Marshal(fields)
		}
		// Selected operations may carry superseded, never-started queue rows.
		// Only the selected exact input decides whether this execution is blocked.
		for _, row := range op.queueRows {
			if row.ID != op.dbID {
				continue
			}
			blocked, err := store.HasFailedOperation(ctx, row)
			if err != nil {
				return err
			}
			op.recoveryBlocked = op.recoveryBlocked || blocked
		}
	}
	return nil
}

// settleWikiOperation never repeats model work. Missing/superseded claims do
// not prove completion, so they do not drain the source enrichment slot.
func (s *wikiIngestService) settleWikiOperation(ctx context.Context, payload WikiIngestPayload, op WikiPendingOp) error {
	store, ok := s.pendingRepo.(interfaces.TaskPendingOpsExecutionStore)
	if !ok {
		return errors.New("wiki execution guard unavailable")
	}
	releaseForRetry := op.failure != nil && wikiFailureOutcome(op.failure) == wikiOutcomeNotRun
	retryStore, canRelease := s.pendingRepo.(interfaces.TaskPendingOpsRetryStore)
	if releaseForRetry && !canRelease {
		return errors.New("wiki retry release unavailable")
	}
	// Upstream's retry budget (v0.9.0): an op whose attempt failed must not be
	// released forever. Past wikiMaxFailRetries it is archived like any other
	// failure, which also releases its finalizing slot below. A cancelled batch
	// keeps its budget: cancellation is not a failed attempt of this op. A failed
	// source lookup always counts, as in upstream.
	countsAttempt := releaseForRetry && (isWikiLookupFailure(op.failure) || !errors.Is(op.failure, context.Canceled))
	failCount := 0
	for _, row := range op.queueRows {
		failCount = max(failCount, row.FailCount)
	}
	if countsAttempt && failCount+1 > wikiMaxFailRetries {
		releaseForRetry = false
	}
	allSettled := true
	for _, row := range op.queueRows {
		var marker struct {
			ExecutionID string `json:"execution_id"`
		}
		if err := json.Unmarshal(row.Payload, &marker); err != nil {
			return err
		}
		var settled bool
		var err error
		if op.failure == nil {
			settled, err = store.CompleteOperation(ctx, row, marker.ExecutionID)
		} else if releaseForRetry {
			budget, recordsBudget := s.pendingRepo.(interfaces.TaskPendingOpsBudgetStore)
			switch {
			case countsAttempt && recordsBudget:
				settled, err = budget.ReleaseOperationAfterAttempt(ctx, row, marker.ExecutionID)
			case countsAttempt:
				// Without a budget record the next claim treats the count as a
				// legacy failure and quarantines it: fail closed.
				if _, err = s.pendingRepo.IncrFailCount(ctx, row.ID); err != nil {
					return err
				}
				settled, err = retryStore.ReleaseOperation(ctx, row, marker.ExecutionID)
			default:
				settled, err = retryStore.ReleaseOperation(ctx, row, marker.ExecutionID)
			}
		} else {
			settled, err = store.ArchiveOperation(ctx, row, marker.ExecutionID, &types.TaskDeadLetter{
				TenantID: payload.TenantID, TaskType: wikiTaskType, Scope: wikiTaskScope, ScopeID: payload.KnowledgeBaseID,
				RelatedID: op.KnowledgeID, LastError: "Wiki generation needs attention: " + wikiFailureOutcome(op.failure),
				FailCount: row.FailCount + 1,
			})
		}
		if err != nil {
			return err
		}
		allSettled = allSettled && settled
	}
	if !allSettled || len(op.queueRows) == 0 {
		return errors.New("wiki settlement unconfirmed")
	}
	if op.Op == WikiOpIngest && !releaseForRetry {
		// Upstream's attempt guard plus our revision-bound slot release.
		superseded := attemptSuperseded(ctx, s.tracker(), op.KnowledgeID, op.Attempt)
		finalizeSubtaskDetached(ctx, withRevisionSlot(s.knowledgeRepo, op.Revision),
			op.KnowledgeID, "wiki", nil, superseded, true)
	}
	return nil
}

func wikiUnsentPageCancellation(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return &wikiStageFailure{Stage: "wiki_page_modify", Outcome: wikiOutcomeNotRun, Cause: err}
	}
	return nil
}

// A fresh follow-up trigger would reset the bounded asynq retry budget.
// Shared unsent work can be cancelled even while this batch remains live.
func wikiBatchRetryError(ctx context.Context, failedOps []WikiPendingOp) error {
	// Upstream (v0.9.0): failed source lookups stay queued with their retry
	// budget and the batch's follow-up drains them; the task itself succeeds.
	onlyLookups := len(failedOps) > 0
	for _, op := range failedOps {
		onlyLookups = onlyLookups && isWikiLookupFailure(op.failure)
	}
	if onlyLookups {
		return nil
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	for _, op := range failedOps {
		if op.failure != nil && !isWikiLookupFailure(op.failure) &&
			wikiFailureOutcome(op.failure) == wikiOutcomeNotRun {
			return errors.New("wiki ingest: unsent operation released for task retry")
		}
	}
	return nil
}

// wikiPageFailures is the batch's single page failure ledger. The same outcome
// drives source attribution, summary links, publication and completion traces.
// Reads happen only after all page workers have joined.
type wikiPageFailures struct {
	mu          sync.Mutex
	bySlug      map[string]error
	byKnowledge map[string]error
	additions   map[string]struct{}
}

func newWikiPageFailures() *wikiPageFailures {
	return &wikiPageFailures{bySlug: map[string]error{}, byKnowledge: map[string]error{}, additions: map[string]struct{}{}}
}

// errWikiPageUpdateDeferred marks upstream's guarded rewrite refusal (the new
// body dropped table rows still on the page): the page keeps its previous body,
// so its documents are recorded as unapplied like any other unwritten slug.
var errWikiPageUpdateDeferred = errors.New("wiki page update deferred: rewrite dropped rows still on the page")

func (f *wikiPageFailures) record(slug string, updates []SlugUpdate, cause error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.bySlug[slug] = errors.Join(f.bySlug[slug], cause)
	for _, u := range updates {
		if u.Type == types.WikiPageTypeEntity || u.Type == types.WikiPageTypeConcept || u.Type == types.WikiPageTypeSummary {
			f.additions[slug] = struct{}{}
		}
		if u.KnowledgeID != "" {
			f.byKnowledge[u.KnowledgeID] = errors.Join(f.byKnowledge[u.KnowledgeID], cause)
		}
	}
}

// selectWikiInputCohorts owns input ordering independently of queue arrival.
// ParseAttempt is the source's monotonic generation. Exact inputs coalesce;
// interrupted/conflicting inputs retain their own settlement. Retraction is
// a document deletion barrier. No model, storage or source state is changed.
func selectWikiInputCohorts(inputs []WikiPendingOp) []WikiPendingOp {
	type inputKey struct {
		knowledge, operation string
		hasRevision          bool
		revision             types.RevisionCommitBinding
	}
	keyOf := func(op WikiPendingOp) inputKey {
		key := inputKey{knowledge: op.KnowledgeID, operation: op.Op, hasRevision: op.Revision != nil}
		if op.Revision != nil {
			key.revision = *op.Revision
		}
		return key
	}
	groups := make(map[inputKey]*WikiPendingOp)
	order := make([]inputKey, 0, len(inputs))
	for _, input := range inputs {
		key := keyOf(input)
		prior := groups[key]
		if prior == nil {
			order = append(order, key)
		} else {
			input.queueRows = append(prior.queueRows, input.queueRows...)
			input.recoveryBlocked = input.recoveryBlocked || prior.recoveryBlocked
		}
		if input.Revision != nil && !input.Revision.Valid() {
			input.recoveryBlocked = true
			input.failure = &wikiStageFailure{Stage: "wiki_revision_invalid", Outcome: wikiOutcomeFailed}
		}
		copy := input
		groups[key] = &copy
	}
	// Same generation with divergent immutable identity is not an ordering
	// choice. Quarantine all competing inputs, including the last arrival.
	type generationKey struct {
		knowledge string
		attempt   int64
	}
	generations := make(map[generationKey][]inputKey)
	for _, key := range order {
		op := groups[key]
		if op.Op == WikiOpIngest && op.Revision != nil && op.Revision.Valid() {
			generation := generationKey{op.KnowledgeID, op.Revision.ParseAttempt}
			generations[generation] = append(generations[generation], key)
		}
	}
	for _, keys := range generations {
		if len(keys) < 2 {
			continue
		}
		for _, key := range keys {
			groups[key].recoveryBlocked = true
			groups[key].failure = &wikiStageFailure{Stage: "wiki_revision_conflict", Outcome: wikiOutcomeFailed}
		}
	}
	selected := make(map[string]inputKey)
	for _, key := range order {
		op := groups[key]
		if op.Revision != nil && !op.Revision.Valid() {
			continue
		}
		previous, exists := selected[op.KnowledgeID]
		if exists {
			prior := groups[previous]
			if prior.Op == WikiOpRetract && op.Op != WikiOpRetract {
				continue
			}
			if prior.Op == WikiOpIngest && op.Op == WikiOpIngest {
				if prior.Revision != nil && (op.Revision == nil || prior.Revision.ParseAttempt > op.Revision.ParseAttempt) {
					continue
				}
			}
		}
		selected[op.KnowledgeID] = key
	}
	// Never-started superseded work needs no model call. Started/invalid work
	// cannot be silently completed with a different generation's success.
	for _, key := range order {
		op := groups[key]
		winner, exists := selected[op.KnowledgeID]
		if exists && key != winner && !op.recoveryBlocked {
			groups[winner].queueRows = append(groups[winner].queueRows, op.queueRows...)
		}
	}
	result := make([]WikiPendingOp, 0, len(groups))
	for _, key := range order {
		op := groups[key]
		winner, exists := selected[op.KnowledgeID]
		if op.recoveryBlocked || exists && key == winner {
			result = append(result, *op)
		}
	}
	return result
}
