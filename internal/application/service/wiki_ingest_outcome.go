package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/google/uuid"
	"sync"
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
		} else {
			settled, err = store.ArchiveOperation(ctx, row, marker.ExecutionID, &types.TaskDeadLetter{
				TenantID: payload.TenantID, TaskType: wikiTaskType, Scope: wikiTaskScope, ScopeID: payload.KnowledgeBaseID,
				RelatedID: op.KnowledgeID, LastError: "Wiki generation needs attention: " + wikiFailureOutcome(op.failure),
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
	if op.Op == WikiOpIngest {
		s.finalizeWikiSubtask(ctx, op.KnowledgeID, op.Revision)
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
