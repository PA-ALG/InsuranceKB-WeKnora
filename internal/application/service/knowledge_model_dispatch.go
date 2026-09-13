package service

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
)

const (
	knowledgeModelDispatchMarkerContract  = "knowledge-model-dispatch-journal.830.v1"
	knowledgeModelDispatchReceiptContract = "knowledge-model-dispatch-receipt.830.v1"
	G3PlatformProcessingReceiptContractV1 = "g3-platform-source-processing-receipt.830.v1"
	knowledgeModelDispatchMarkerName      = "model-dispatch.journal"
	knowledgeModelDispatchNamePrefix      = "model-dispatch."

	G3PlatformProcessingAvailable   = "AVAILABLE"
	G3PlatformProcessingUnavailable = "UNAVAILABLE"
)

type knowledgeModelDispatchMarker struct {
	Contract          string                 `json:"contract"`
	Scope             types.WikiReleaseScope `json:"scope"`
	KnowledgeID       string                 `json:"knowledge_id"`
	ProcessingAttempt int                    `json:"processing_attempt"`
	ParseAttempt      int64                  `json:"parse_attempt"`
}

type knowledgeModelDispatchInput struct {
	Contract            string `json:"contract"`
	DispatchID          string `json:"dispatch_id"`
	Operation           string `json:"operation"`
	Purpose             string `json:"purpose"`
	ModelID             string `json:"model_id"`
	ModelName           string `json:"model_name"`
	RequestSHA256       string `json:"request_sha256"`
	TransportRetryIndex int    `json:"transport_retry_index"`
	WorkerRetry         int    `json:"worker_retry"`
}

type G3PlatformProcessingCallReceiptV1 struct {
	Contract            string `json:"contract"`
	DispatchID          string `json:"dispatch_id"`
	Operation           string `json:"operation"`
	Purpose             string `json:"purpose"`
	ModelID             string `json:"model_id"`
	ModelName           string `json:"model_name"`
	RequestSHA256       string `json:"request_sha256"`
	TransportRetryIndex int    `json:"transport_retry_index"`
	State               string `json:"state"`
	Outcome             string `json:"outcome"`
	HTTPStatus          int    `json:"http_status,omitempty"`
	StartedAtUnixMS     int64  `json:"started_at_unix_ms"`
	FinishedAtUnixMS    int64  `json:"finished_at_unix_ms"`
	DurationMS          int64  `json:"duration_ms"`
}

type G3PlatformProcessingCountsV1 struct {
	Attempts         int `json:"attempts"`
	Confirmed        int `json:"confirmed"`
	Interrupted      int `json:"interrupted"`
	NotDispatched    int `json:"not_dispatched"`
	TransportRetries int `json:"transport_retries"`
}

type G3PlatformProcessingPhaseOccurrenceV1 struct {
	Occurrence       int    `json:"occurrence"`
	Status           string `json:"status"`
	StartedAtUnixMS  int64  `json:"started_at_unix_ms"`
	FinishedAtUnixMS int64  `json:"finished_at_unix_ms"`
	DurationMS       int64  `json:"duration_ms"`
}

type G3PlatformProcessingPhaseV1 struct {
	Phase       string                                  `json:"phase"`
	Recorded    bool                                    `json:"recorded"`
	Occurrences []G3PlatformProcessingPhaseOccurrenceV1 `json:"occurrences"`
}

type G3PlatformSourceProcessingReceiptV1 struct {
	Contract             string                               `json:"contract"`
	Availability         string                               `json:"availability"`
	KnowledgeID          string                               `json:"knowledge_id"`
	ParseAttempt         int64                                `json:"parse_attempt"`
	ProcessingAttempt    int                                  `json:"processing_attempt,omitempty"`
	JournalMarkerSHA256  string                               `json:"journal_marker_sha256,omitempty"`
	Calls                *[]G3PlatformProcessingCallReceiptV1 `json:"calls,omitempty"`
	Counts               *G3PlatformProcessingCountsV1        `json:"counts,omitempty"`
	UnavailabilityReason string                               `json:"unavailability_reason,omitempty"`
	Phases               []G3PlatformProcessingPhaseV1        `json:"phases"`
	ReceiptSHA256        string                               `json:"receipt_sha256"`
}

// KnowledgeModelDispatchJournal persists strict provider-call receipts in the
// existing attempt span tree. Unlike SpanTracker, its writes are not best effort.
type KnowledgeModelDispatchJournal struct {
	repo repository.KnowledgeSpanRepository
}

type modelDispatchWorkerRetryContextKey struct{}

func NewKnowledgeModelDispatchJournal(repo repository.KnowledgeSpanRepository) *KnowledgeModelDispatchJournal {
	return &KnowledgeModelDispatchJournal{repo: repo}
}

func withModelDispatchWorkerRetry(ctx context.Context, retry int) context.Context {
	if ctx == nil || retry < 0 {
		return ctx
	}
	return context.WithValue(ctx, modelDispatchWorkerRetryContextKey{}, retry)
}

func modelDispatchWorkerRetry(ctx context.Context) int {
	if ctx == nil {
		return 0
	}
	retry, _ := ctx.Value(modelDispatchWorkerRetryContextKey{}).(int)
	if retry < 0 {
		return 0
	}
	return retry
}

func (s *knowledgeService) g3ModelDispatchJournal(
	knowledge *types.Knowledge,
) (*KnowledgeModelDispatchJournal, types.WikiReleaseScope, bool) {
	if s == nil || s.config == nil || s.config.G3PlatformProcessing == nil ||
		!s.config.G3PlatformProcessing.Enabled || knowledge == nil {
		return nil, types.WikiReleaseScope{}, false
	}
	cfg := s.config.G3PlatformProcessing
	if knowledge.TenantID != cfg.TenantID || knowledge.KnowledgeBaseID != cfg.RawKBID {
		return nil, types.WikiReleaseScope{}, false
	}
	tracker, ok := s.tracker().(*spanTracker)
	if !ok || tracker.repo == nil {
		return nil, types.WikiReleaseScope{}, true
	}
	return NewKnowledgeModelDispatchJournal(tracker.repo), types.WikiReleaseScope{
		TenantID: cfg.TenantID, SpaceID: cfg.SpaceID, RawKBID: cfg.RawKBID, WikiKBID: cfg.WikiKBID,
	}, true
}

func (s *knowledgeService) ensureG3ModelDispatchJournal(
	ctx context.Context, knowledge *types.Knowledge, processingAttempt int, parseAttempt int64,
) error {
	journal, scope, enabled := s.g3ModelDispatchJournal(knowledge)
	if !enabled {
		return nil
	}
	if journal == nil {
		return types.ErrModelDispatchJournalUnavailable
	}
	_, err := journal.EnsureEnabled(ctx, scope, knowledge.ID, processingAttempt, parseAttempt)
	return err
}

func (s *knowledgeService) withG3ModelDispatchParent(
	ctx context.Context, knowledge *types.Knowledge, parent *Span,
) (context.Context, error) {
	journal, _, enabled := s.g3ModelDispatchJournal(knowledge)
	if !enabled {
		return ctx, nil
	}
	if journal == nil || parent == nil {
		return ctx, types.ErrModelDispatchJournalUnavailable
	}
	return journal.WithParent(ctx, parent, modelDispatchWorkerRetry(ctx))
}

func modelDispatchJSONMap(value any) (types.JSONMap, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var result types.JSONMap
	if err := json.Unmarshal(raw, &result); err != nil {
		return nil, err
	}
	return result, nil
}

func decodeModelDispatchMap(value types.JSONMap, target any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(target) != nil || !jsonEOF830G2(decoder) {
		return types.ErrModelDispatchJournalUnavailable
	}
	return nil
}

func modelDispatchDigest(contract string, value any) (string, error) {
	return g3PlatformSnapshotDigest(contract, value, "receipt_sha256")
}

func (j *KnowledgeModelDispatchJournal) EnsureEnabled(
	ctx context.Context,
	scope types.WikiReleaseScope,
	knowledgeID string,
	processingAttempt int,
	parseAttempt int64,
) (string, error) {
	if j == nil || j.repo == nil || !validG3PlatformScope(scope) || knowledgeID == "" ||
		processingAttempt <= 0 || parseAttempt <= 0 {
		return "", types.ErrModelDispatchJournalUnavailable
	}
	rows, err := j.repo.ListByAttempt(ctx, knowledgeID, processingAttempt)
	if err != nil {
		return "", fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
	}
	rootID := ""
	for _, row := range rows {
		if row.Kind == types.SpanKindRoot && row.ParentSpanID == "" {
			if rootID != "" && rootID != row.SpanID {
				return "", types.ErrModelDispatchJournalUnavailable
			}
			rootID = row.SpanID
		}
	}
	if rootID == "" {
		return "", types.ErrModelDispatchJournalUnavailable
	}
	marker := knowledgeModelDispatchMarker{
		Contract: knowledgeModelDispatchMarkerContract, Scope: scope, KnowledgeID: knowledgeID,
		ProcessingAttempt: processingAttempt, ParseAttempt: parseAttempt,
	}
	markerSHA, err := modelDispatchDigest(marker.Contract, marker)
	if err != nil {
		return "", types.ErrModelDispatchJournalUnavailable
	}
	input, err := modelDispatchJSONMap(marker)
	if err != nil {
		return "", types.ErrModelDispatchJournalUnavailable
	}
	for _, row := range rows {
		if row.Name != knowledgeModelDispatchMarkerName {
			continue
		}
		var existing knowledgeModelDispatchMarker
		if row.SpanID != markerSHA || row.ParentSpanID != rootID || row.Kind != types.SpanKindSubSpan ||
			row.Status != types.SpanStatusDone || decodeModelDispatchMap(row.Input, &existing) != nil ||
			existing != marker {
			return "", types.ErrModelDispatchJournalUnavailable
		}
		return markerSHA, nil
	}
	now := time.Now()
	if err := j.repo.Upsert(ctx, &types.KnowledgeProcessingSpan{
		KnowledgeID: knowledgeID, Attempt: processingAttempt, SpanID: markerSHA,
		ParentSpanID: rootID, Name: knowledgeModelDispatchMarkerName, Kind: types.SpanKindSubSpan,
		Status: types.SpanStatusDone, Input: input, StartedAt: &now, FinishedAt: &now,
	}); err != nil {
		return "", fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
	}
	return markerSHA, nil
}

func (j *KnowledgeModelDispatchJournal) WithParent(
	ctx context.Context, parent *Span, workerRetry int,
) (context.Context, error) {
	if j == nil || j.repo == nil || parent == nil || parent.KnowledgeID == "" ||
		parent.Attempt <= 0 || parent.SpanID == "" || workerRetry < 0 {
		return ctx, types.ErrModelDispatchJournalUnavailable
	}
	rows, err := j.repo.ListByAttempt(ctx, parent.KnowledgeID, parent.Attempt)
	if err != nil {
		return ctx, fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
	}
	rootID := ""
	for i := range rows {
		row := rows[i]
		if row.Kind == types.SpanKindRoot && row.ParentSpanID == "" {
			if rootID != "" && rootID != row.SpanID {
				return ctx, types.ErrModelDispatchJournalUnavailable
			}
			rootID = row.SpanID
		}
	}
	if rootID == "" {
		return ctx, types.ErrModelDispatchJournalUnavailable
	}
	markerFound := false
	for i := range rows {
		row := rows[i]
		if row.Name != knowledgeModelDispatchMarkerName {
			continue
		}
		var marker knowledgeModelDispatchMarker
		if markerFound || row.Status != types.SpanStatusDone || row.Kind != types.SpanKindSubSpan ||
			decodeModelDispatchMap(row.Input, &marker) != nil || marker.Contract != knowledgeModelDispatchMarkerContract ||
			marker.KnowledgeID != parent.KnowledgeID || marker.ProcessingAttempt != parent.Attempt ||
			marker.ParseAttempt <= 0 || !validG3PlatformScope(marker.Scope) || row.ParentSpanID != rootID {
			return ctx, types.ErrModelDispatchJournalUnavailable
		}
		markerSHA, digestErr := modelDispatchDigest(marker.Contract, marker)
		if digestErr != nil || markerSHA != row.SpanID {
			return ctx, types.ErrModelDispatchJournalUnavailable
		}
		markerFound = true
	}
	if !markerFound {
		return ctx, types.ErrModelDispatchJournalUnavailable
	}
	for i := range rows {
		row := rows[i]
		if row.ParentSpanID != parent.SpanID || row.Kind != types.SpanKindGeneration ||
			!strings.HasPrefix(row.Name, knowledgeModelDispatchNamePrefix) ||
			(row.Status != types.SpanStatusPending && row.Status != types.SpanStatusRunning) {
			continue
		}
		var input knowledgeModelDispatchInput
		if decodeModelDispatchMap(row.Input, &input) != nil || input.Contract != knowledgeModelDispatchReceiptContract ||
			input.WorkerRetry >= workerRetry {
			continue
		}
		outcome := "NOT_DISPATCHED"
		if row.Status == types.SpanStatusRunning {
			outcome = "DISPATCH_UNCERTAIN"
		}
		output := types.JSONMap{"state": "INTERRUPTED", "outcome": outcome}
		now := time.Now()
		row.Status = types.SpanStatusCancelled
		row.Output = output
		row.Metadata = types.JSONMap{"state": "INTERRUPTED"}
		row.FinishedAt = &now
		row.DurationMs = modelDispatchDuration(row.StartedAt, now)
		if err := j.repo.Upsert(ctx, &row); err != nil {
			return ctx, fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
		}
	}
	return types.WithModelDispatchRecorder(ctx, &knowledgeModelDispatchRecorder{
		journal: j, parent: *parent, workerRetry: workerRetry,
	}), nil
}

type knowledgeModelDispatchRecorder struct {
	journal     *KnowledgeModelDispatchJournal
	parent      Span
	workerRetry int
}

func validModelDispatchSpec(spec types.ModelDispatchSpec) bool {
	if spec.TransportRetryIndex < 0 || !validServiceSHA256(spec.RequestSHA256) ||
		spec.ModelID == "" || spec.ModelName == "" || len(spec.ModelID) > 256 || len(spec.ModelName) > 256 ||
		strings.ContainsRune(spec.ModelID, '\x00') || strings.ContainsRune(spec.ModelName, '\x00') {
		return false
	}
	return (spec.Operation == "embedding" &&
		(spec.Purpose == "document_embedding" || spec.Purpose == "summary_embedding")) ||
		(spec.Operation == "document_summary" && spec.Purpose == "document_summary")
}

func (r *knowledgeModelDispatchRecorder) ReserveModelDispatch(
	ctx context.Context, spec types.ModelDispatchSpec,
) (types.ModelDispatchReservation, error) {
	if r == nil || r.journal == nil || r.journal.repo == nil || !validModelDispatchSpec(spec) {
		return nil, types.ErrModelDispatchJournalUnavailable
	}
	now := time.Now()
	id := newSpanID()
	inputValue := knowledgeModelDispatchInput{
		Contract: knowledgeModelDispatchReceiptContract, DispatchID: id,
		Operation: spec.Operation, Purpose: spec.Purpose, ModelID: spec.ModelID,
		ModelName: spec.ModelName, RequestSHA256: spec.RequestSHA256,
		TransportRetryIndex: spec.TransportRetryIndex, WorkerRetry: r.workerRetry,
	}
	input, err := modelDispatchJSONMap(inputValue)
	if err != nil {
		return nil, types.ErrModelDispatchJournalUnavailable
	}
	row := types.KnowledgeProcessingSpan{
		KnowledgeID: r.parent.KnowledgeID, Attempt: r.parent.Attempt, SpanID: id,
		ParentSpanID: r.parent.SpanID, Name: knowledgeModelDispatchNamePrefix + spec.Operation,
		Kind: types.SpanKindGeneration, Status: types.SpanStatusPending, Input: input,
		Metadata: types.JSONMap{"state": "RESERVED"}, StartedAt: &now,
	}
	if err := r.journal.repo.Upsert(ctx, &row); err != nil {
		return nil, fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
	}
	return &knowledgeModelDispatchReservation{repo: r.journal.repo, row: row}, nil
}

type knowledgeModelDispatchReservation struct {
	repo        repository.KnowledgeSpanRepository
	row         types.KnowledgeProcessingSpan
	dispatching bool
}

func (r *knowledgeModelDispatchReservation) MarkDispatching(ctx context.Context) error {
	if r == nil || r.repo == nil || r.dispatching {
		return types.ErrModelDispatchJournalUnavailable
	}
	r.row.Status = types.SpanStatusRunning
	r.row.Metadata = types.JSONMap{"state": "DISPATCHING"}
	if err := r.repo.Upsert(ctx, &r.row); err != nil {
		return fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
	}
	r.dispatching = true
	return nil
}

func (r *knowledgeModelDispatchReservation) RecordModelDispatch(
	ctx context.Context, result types.ModelDispatchResult,
) error {
	valid := result.Outcome == "TRANSPORT_ERROR" && result.HTTPStatus == 0 ||
		result.Outcome == "HTTP_RESPONSE" && result.HTTPStatus >= 100 && result.HTTPStatus <= 599
	if r == nil || r.repo == nil || !r.dispatching || !valid {
		return types.ErrModelDispatchJournalUnavailable
	}
	now := time.Now()
	r.row.Status = types.SpanStatusDone
	r.row.Metadata = types.JSONMap{"state": "RECORDED"}
	r.row.Output = types.JSONMap{"state": "RECORDED", "outcome": result.Outcome}
	if result.HTTPStatus != 0 {
		r.row.Output["http_status"] = result.HTTPStatus
	}
	r.row.FinishedAt = &now
	r.row.DurationMs = modelDispatchDuration(r.row.StartedAt, now)
	writeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
	defer cancel()
	if err := r.repo.Upsert(writeCtx, &r.row); err != nil {
		return fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
	}
	return nil
}

func modelDispatchDuration(started *time.Time, finished time.Time) int64 {
	if started == nil || finished.Before(*started) {
		return 0
	}
	return finished.Sub(*started).Milliseconds()
}

func (j *KnowledgeModelDispatchJournal) ProcessingReceipt(
	ctx context.Context, scope types.WikiReleaseScope, knowledgeID string, parseAttempt int64,
) (G3PlatformSourceProcessingReceiptV1, error) {
	empty := G3PlatformSourceProcessingReceiptV1{}
	if j == nil || j.repo == nil || !validG3PlatformScope(scope) || knowledgeID == "" || parseAttempt <= 0 {
		return empty, types.ErrModelDispatchJournalUnavailable
	}
	processingAttempt, err := j.repo.LatestAttempt(ctx, knowledgeID)
	if err != nil {
		return empty, fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
	}
	rows := []types.KnowledgeProcessingSpan{}
	if processingAttempt > 0 {
		rows, err = j.repo.ListByAttempt(ctx, knowledgeID, processingAttempt)
		if err != nil {
			return empty, fmt.Errorf("%w: %v", types.ErrModelDispatchJournalUnavailable, err)
		}
	}
	receipt := G3PlatformSourceProcessingReceiptV1{
		Contract: G3PlatformProcessingReceiptContractV1, Availability: G3PlatformProcessingUnavailable,
		KnowledgeID: knowledgeID, ParseAttempt: parseAttempt, ProcessingAttempt: processingAttempt,
		UnavailabilityReason: "LEGACY_NO_JOURNAL", Phases: modelDispatchPhases(rows),
	}
	rootID := ""
	for _, row := range rows {
		if row.Kind == types.SpanKindRoot && row.ParentSpanID == "" {
			if rootID != "" && rootID != row.SpanID {
				return empty, types.ErrModelDispatchJournalUnavailable
			}
			rootID = row.SpanID
		}
	}
	markerCount := 0
	for _, row := range rows {
		if row.Name != knowledgeModelDispatchMarkerName {
			continue
		}
		markerCount++
		var marker knowledgeModelDispatchMarker
		if rootID == "" || row.ParentSpanID != rootID || row.Kind != types.SpanKindSubSpan || row.Status != types.SpanStatusDone ||
			decodeModelDispatchMap(row.Input, &marker) != nil || marker.Contract != knowledgeModelDispatchMarkerContract ||
			marker.Scope != scope || marker.KnowledgeID != knowledgeID ||
			marker.ProcessingAttempt != processingAttempt || marker.ParseAttempt != parseAttempt {
			return empty, types.ErrModelDispatchJournalUnavailable
		}
		markerSHA, digestErr := modelDispatchDigest(marker.Contract, marker)
		if digestErr != nil || row.SpanID != markerSHA {
			return empty, types.ErrModelDispatchJournalUnavailable
		}
		receipt.JournalMarkerSHA256 = markerSHA
	}
	if markerCount == 0 {
		digest, digestErr := modelDispatchDigest(receipt.Contract, receipt)
		if digestErr != nil {
			return empty, types.ErrModelDispatchJournalUnavailable
		}
		receipt.ReceiptSHA256 = digest
		return receipt, nil
	}
	if markerCount != 1 {
		return empty, types.ErrModelDispatchJournalUnavailable
	}
	receipt.Availability = G3PlatformProcessingAvailable
	receipt.UnavailabilityReason = ""
	calls := []G3PlatformProcessingCallReceiptV1{}
	counts := &G3PlatformProcessingCountsV1{}
	byID := make(map[string]types.KnowledgeProcessingSpan, len(rows))
	for _, row := range rows {
		byID[row.SpanID] = row
	}
	for _, row := range rows {
		if !strings.HasPrefix(row.Name, knowledgeModelDispatchNamePrefix) || row.Name == knowledgeModelDispatchMarkerName {
			continue
		}
		call, err := modelDispatchCallReceipt(row, byID)
		if err != nil {
			return empty, err
		}
		calls = append(calls, call)
		switch call.Outcome {
		case "NOT_DISPATCHED":
			counts.NotDispatched++
		case "DISPATCH_UNCERTAIN":
			counts.Attempts++
			counts.Interrupted++
		default:
			counts.Attempts++
			counts.Confirmed++
		}
		if call.TransportRetryIndex > 0 && call.Outcome != "NOT_DISPATCHED" {
			counts.TransportRetries++
		}
	}
	sort.Slice(calls, func(i, k int) bool { return calls[i].DispatchID < calls[k].DispatchID })
	receipt.Calls = &calls
	receipt.Counts = counts
	digest, err := modelDispatchDigest(receipt.Contract, receipt)
	if err != nil {
		return empty, types.ErrModelDispatchJournalUnavailable
	}
	receipt.ReceiptSHA256 = digest
	return receipt, nil
}

func validateG3PlatformSourceProcessingReceipt(
	receipt G3PlatformSourceProcessingReceiptV1,
	scope types.WikiReleaseScope,
	knowledgeID string,
	parseAttempt int64,
) error {
	if receipt.Contract != G3PlatformProcessingReceiptContractV1 ||
		receipt.KnowledgeID != knowledgeID || receipt.ParseAttempt != parseAttempt ||
		!validG3PlatformScope(scope) || knowledgeID == "" || parseAttempt <= 0 ||
		!validServiceSHA256(receipt.ReceiptSHA256) || !validModelDispatchPhases(receipt.Phases) {
		return types.ErrModelDispatchJournalUnavailable
	}
	digest, err := modelDispatchDigest(receipt.Contract, receipt)
	if err != nil || digest != receipt.ReceiptSHA256 {
		return types.ErrModelDispatchJournalUnavailable
	}
	switch receipt.Availability {
	case G3PlatformProcessingUnavailable:
		if receipt.ProcessingAttempt < 0 || receipt.JournalMarkerSHA256 != "" ||
			receipt.Calls != nil || receipt.Counts != nil || receipt.UnavailabilityReason != "LEGACY_NO_JOURNAL" {
			return types.ErrModelDispatchJournalUnavailable
		}
		return nil
	case G3PlatformProcessingAvailable:
		if receipt.ProcessingAttempt <= 0 || !validServiceSHA256(receipt.JournalMarkerSHA256) ||
			receipt.Calls == nil || receipt.Counts == nil || receipt.UnavailabilityReason != "" {
			return types.ErrModelDispatchJournalUnavailable
		}
	default:
		return types.ErrModelDispatchJournalUnavailable
	}

	derived := G3PlatformProcessingCountsV1{}
	previousID := ""
	for _, call := range *receipt.Calls {
		if call.Contract != knowledgeModelDispatchReceiptContract || call.DispatchID == "" ||
			(previousID != "" && call.DispatchID <= previousID) ||
			!validModelDispatchSpec(types.ModelDispatchSpec{
				Operation: call.Operation, Purpose: call.Purpose, ModelID: call.ModelID,
				ModelName: call.ModelName, RequestSHA256: call.RequestSHA256,
				TransportRetryIndex: call.TransportRetryIndex,
			}) || call.StartedAtUnixMS <= 0 || call.FinishedAtUnixMS < call.StartedAtUnixMS ||
			call.DurationMS != call.FinishedAtUnixMS-call.StartedAtUnixMS {
			return types.ErrModelDispatchJournalUnavailable
		}
		previousID = call.DispatchID
		switch call.Outcome {
		case "HTTP_RESPONSE":
			if call.State != "RECORDED" || call.HTTPStatus < 100 || call.HTTPStatus > 599 {
				return types.ErrModelDispatchJournalUnavailable
			}
			derived.Attempts++
			derived.Confirmed++
		case "TRANSPORT_ERROR":
			if call.State != "RECORDED" || call.HTTPStatus != 0 {
				return types.ErrModelDispatchJournalUnavailable
			}
			derived.Attempts++
			derived.Confirmed++
		case "DISPATCH_UNCERTAIN":
			if call.State != "INTERRUPTED" || call.HTTPStatus != 0 {
				return types.ErrModelDispatchJournalUnavailable
			}
			derived.Attempts++
			derived.Interrupted++
		case "NOT_DISPATCHED":
			if call.State != "INTERRUPTED" || call.HTTPStatus != 0 {
				return types.ErrModelDispatchJournalUnavailable
			}
			derived.NotDispatched++
		default:
			return types.ErrModelDispatchJournalUnavailable
		}
		if call.TransportRetryIndex > 0 && call.Outcome != "NOT_DISPATCHED" {
			derived.TransportRetries++
		}
	}
	if derived != *receipt.Counts {
		return types.ErrModelDispatchJournalUnavailable
	}
	return nil
}

func validModelDispatchPhases(phases []G3PlatformProcessingPhaseV1) bool {
	names := []string{types.StageDocReader, types.StageChunking, types.StageEmbedding, "postprocess.summary"}
	if len(phases) != len(names) {
		return false
	}
	for i, phase := range phases {
		if phase.Phase != names[i] || phase.Recorded != (len(phase.Occurrences) > 0) || phase.Occurrences == nil {
			return false
		}
		previousStart := int64(0)
		for occurrenceIndex, occurrence := range phase.Occurrences {
			terminal := occurrence.Status == types.SpanStatusDone || occurrence.Status == types.SpanStatusFailed ||
				occurrence.Status == types.SpanStatusSkipped || occurrence.Status == types.SpanStatusCancelled
			if occurrence.Occurrence != occurrenceIndex || !terminal || occurrence.StartedAtUnixMS <= 0 ||
				occurrence.FinishedAtUnixMS < occurrence.StartedAtUnixMS ||
				occurrence.DurationMS != occurrence.FinishedAtUnixMS-occurrence.StartedAtUnixMS ||
				(occurrenceIndex > 0 && occurrence.StartedAtUnixMS < previousStart) {
				return false
			}
			previousStart = occurrence.StartedAtUnixMS
		}
	}
	return true
}

func modelDispatchCallReceipt(
	row types.KnowledgeProcessingSpan, byID map[string]types.KnowledgeProcessingSpan,
) (G3PlatformProcessingCallReceiptV1, error) {
	empty := G3PlatformProcessingCallReceiptV1{}
	var input knowledgeModelDispatchInput
	if row.Kind != types.SpanKindGeneration || decodeModelDispatchMap(row.Input, &input) != nil ||
		input.Contract != knowledgeModelDispatchReceiptContract || input.DispatchID != row.SpanID ||
		!validModelDispatchSpec(types.ModelDispatchSpec{Operation: input.Operation, Purpose: input.Purpose,
			ModelID: input.ModelID, ModelName: input.ModelName, RequestSHA256: input.RequestSHA256,
			TransportRetryIndex: input.TransportRetryIndex}) || row.StartedAt == nil || row.FinishedAt == nil {
		return empty, types.ErrModelDispatchJournalUnavailable
	}
	parent, ok := byID[row.ParentSpanID]
	if !ok || !validModelDispatchParent(input, parent, byID) {
		return empty, types.ErrModelDispatchJournalUnavailable
	}
	state, _ := row.Metadata["state"].(string)
	outcome, _ := row.Output["outcome"].(string)
	if row.Status == types.SpanStatusDone {
		if state != "RECORDED" || (outcome != "HTTP_RESPONSE" && outcome != "TRANSPORT_ERROR") {
			return empty, types.ErrModelDispatchJournalUnavailable
		}
	} else if row.Status == types.SpanStatusCancelled {
		if state != "INTERRUPTED" || (outcome != "NOT_DISPATCHED" && outcome != "DISPATCH_UNCERTAIN") {
			return empty, types.ErrModelDispatchJournalUnavailable
		}
	} else {
		return empty, types.ErrModelDispatchJournalUnavailable
	}
	httpStatus := 0
	if raw, exists := row.Output["http_status"]; exists {
		switch value := raw.(type) {
		case float64:
			httpStatus = int(value)
		case int:
			httpStatus = value
		}
	}
	if outcome == "HTTP_RESPONSE" && (httpStatus < 100 || httpStatus > 599) ||
		outcome != "HTTP_RESPONSE" && httpStatus != 0 {
		return empty, types.ErrModelDispatchJournalUnavailable
	}
	return G3PlatformProcessingCallReceiptV1{
		Contract: input.Contract, DispatchID: input.DispatchID, Operation: input.Operation,
		Purpose: input.Purpose, ModelID: input.ModelID, ModelName: input.ModelName,
		RequestSHA256: input.RequestSHA256, TransportRetryIndex: input.TransportRetryIndex,
		State: state, Outcome: outcome, HTTPStatus: httpStatus,
		StartedAtUnixMS: row.StartedAt.UnixMilli(), FinishedAtUnixMS: row.FinishedAt.UnixMilli(),
		DurationMS: row.FinishedAt.UnixMilli() - row.StartedAt.UnixMilli(),
	}, nil
}

func validModelDispatchParent(
	input knowledgeModelDispatchInput,
	parent types.KnowledgeProcessingSpan,
	byID map[string]types.KnowledgeProcessingSpan,
) bool {
	if !terminalModelDispatchSpan(parent) {
		return false
	}
	if input.Purpose == "document_embedding" {
		return parent.Kind == types.SpanKindStage && parent.Name == types.StageEmbedding
	}
	if parent.Kind != types.SpanKindSubSpan || parent.Name != "postprocess.summary" {
		return false
	}
	ancestor, ok := byID[parent.ParentSpanID]
	if !ok || ancestor.Kind != types.SpanKindStage || ancestor.Name != types.StagePostProcess ||
		!terminalModelDispatchSpan(ancestor) {
		return false
	}
	return input.Purpose == "document_summary" || input.Purpose == "summary_embedding"
}

func terminalModelDispatchSpan(row types.KnowledgeProcessingSpan) bool {
	terminal := row.Status == types.SpanStatusDone || row.Status == types.SpanStatusFailed ||
		row.Status == types.SpanStatusSkipped || row.Status == types.SpanStatusCancelled
	return terminal && row.StartedAt != nil && row.FinishedAt != nil && !row.FinishedAt.Before(*row.StartedAt)
}

func modelDispatchPhases(rows []types.KnowledgeProcessingSpan) []G3PlatformProcessingPhaseV1 {
	names := []string{types.StageDocReader, types.StageChunking, types.StageEmbedding, "postprocess.summary"}
	result := make([]G3PlatformProcessingPhaseV1, 0, len(names))
	for _, name := range names {
		matching := []types.KnowledgeProcessingSpan{}
		for _, row := range rows {
			kindOK := name == "postprocess.summary" && row.Kind == types.SpanKindSubSpan ||
				name != "postprocess.summary" && row.Kind == types.SpanKindStage
			if row.Name == name && kindOK && row.StartedAt != nil && row.FinishedAt != nil {
				matching = append(matching, row)
			}
		}
		sort.Slice(matching, func(i, k int) bool {
			if matching[i].StartedAt.Equal(*matching[k].StartedAt) {
				return matching[i].SpanID < matching[k].SpanID
			}
			return matching[i].StartedAt.Before(*matching[k].StartedAt)
		})
		phase := G3PlatformProcessingPhaseV1{Phase: name, Recorded: len(matching) > 0, Occurrences: []G3PlatformProcessingPhaseOccurrenceV1{}}
		for index, row := range matching {
			phase.Occurrences = append(phase.Occurrences, G3PlatformProcessingPhaseOccurrenceV1{
				Occurrence: index, Status: row.Status, StartedAtUnixMS: row.StartedAt.UnixMilli(),
				FinishedAtUnixMS: row.FinishedAt.UnixMilli(),
				DurationMS:       row.FinishedAt.UnixMilli() - row.StartedAt.UnixMilli(),
			})
		}
		result = append(result, phase)
	}
	return result
}

var _ types.ModelDispatchRecorder = (*knowledgeModelDispatchRecorder)(nil)
var _ types.ModelDispatchReservation = (*knowledgeModelDispatchReservation)(nil)
