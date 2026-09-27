package service

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func newKnowledgeDispatchJournalTest(t *testing.T) (*KnowledgeModelDispatchJournal, repository.KnowledgeSpanRepository) {
	t.Helper()
	db, err := gorm.Open(sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := db.Exec(spanTrackerTestDDL).Error; err != nil {
		t.Fatal(err)
	}
	repo := repository.NewKnowledgeSpanRepository(db)
	return NewKnowledgeModelDispatchJournal(repo), repo
}

func seedDispatchSpan(t *testing.T, repo repository.KnowledgeSpanRepository, row types.KnowledgeProcessingSpan) {
	t.Helper()
	if err := repo.Upsert(context.Background(), &row); err != nil {
		t.Fatal(err)
	}
}

func dispatchTestScope() types.WikiReleaseScope {
	return types.WikiReleaseScope{TenantID: 17, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}
}

func TestKnowledgeModelDispatchJournalProvesZeroCallsAndProjectsRecordedPhases(t *testing.T) {
	journal, repo := newKnowledgeDispatchJournalTest(t)
	now := time.UnixMilli(1_700_000_000_000)
	finished := now.Add(120 * time.Millisecond)
	seedDispatchSpan(t, repo, types.KnowledgeProcessingSpan{
		KnowledgeID: "kid", Attempt: 4, SpanID: "root", Name: "root", Kind: types.SpanKindRoot,
		Status: types.SpanStatusDone, StartedAt: &now, FinishedAt: &finished,
	})
	seedDispatchSpan(t, repo, types.KnowledgeProcessingSpan{
		KnowledgeID: "kid", Attempt: 4, SpanID: "doc", ParentSpanID: "root",
		Name: types.StageDocReader, Kind: types.SpanKindStage, Status: types.SpanStatusDone,
		StartedAt: &now, FinishedAt: &finished, DurationMs: 120,
	})

	marker, err := journal.EnsureEnabled(context.Background(), dispatchTestScope(), "kid", 4, 9)
	if err != nil {
		t.Fatal(err)
	}
	receipt, err := journal.ProcessingReceipt(context.Background(), dispatchTestScope(), "kid", 9)
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Availability != G3PlatformProcessingAvailable || receipt.JournalMarkerSHA256 != marker ||
		receipt.ProcessingAttempt != 4 || receipt.Counts == nil || receipt.Counts.Attempts != 0 ||
		receipt.Calls == nil || len(*receipt.Calls) != 0 || len(receipt.Phases) != 4 || !receipt.Phases[0].Recorded {
		t.Fatalf("unexpected zero-call receipt: %#v", receipt)
	}
	if receipt.Phases[0].Occurrences[0].DurationMS != 120 || receipt.ReceiptSHA256 == "" {
		t.Fatalf("phase timing or receipt digest missing: %#v", receipt.Phases[0])
	}
}

func TestKnowledgeModelDispatchJournalCountsSettledAndInterruptedNetworkAttempts(t *testing.T) {
	journal, repo := newKnowledgeDispatchJournalTest(t)
	now := time.Now()
	seedDispatchSpan(t, repo, types.KnowledgeProcessingSpan{
		KnowledgeID: "kid", Attempt: 4, SpanID: "root", Name: "root", Kind: types.SpanKindRoot,
		Status: types.SpanStatusRunning, StartedAt: &now,
	})
	seedDispatchSpan(t, repo, types.KnowledgeProcessingSpan{
		KnowledgeID: "kid", Attempt: 4, SpanID: "embedding", ParentSpanID: "root",
		Name: types.StageEmbedding, Kind: types.SpanKindStage, Status: types.SpanStatusRunning,
		StartedAt: &now,
	})
	if _, err := journal.EnsureEnabled(context.Background(), dispatchTestScope(), "kid", 4, 9); err != nil {
		t.Fatal(err)
	}

	ctx, err := journal.WithParent(context.Background(), &Span{
		KnowledgeID: "kid", Attempt: 4, SpanID: "embedding", Name: types.StageEmbedding,
		Kind: types.SpanKindStage, Status: types.SpanStatusRunning, StartedAt: now,
	}, 0)
	if err != nil {
		t.Fatal(err)
	}
	first, err := types.ReserveModelDispatch(ctx, types.ModelDispatchSpec{
		Operation: "embedding", Purpose: "document_embedding", ModelID: "qwen-id",
		ModelName: "qwen", RequestSHA256: testSHA256830G2("request-1"), TransportRetryIndex: 0,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := first.MarkDispatching(ctx); err != nil {
		t.Fatal(err)
	}
	if err := first.RecordModelDispatch(ctx, types.ModelDispatchResult{Outcome: "HTTP_RESPONSE", HTTPStatus: 200}); err != nil {
		t.Fatal(err)
	}

	second, err := types.ReserveModelDispatch(ctx, types.ModelDispatchSpec{
		Operation: "embedding", Purpose: "document_embedding", ModelID: "qwen-id",
		ModelName: "qwen", RequestSHA256: testSHA256830G2("request-2"), TransportRetryIndex: 1,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := second.MarkDispatching(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := types.ReserveModelDispatch(ctx, types.ModelDispatchSpec{
		Operation: "embedding", Purpose: "document_embedding", ModelID: "qwen-id",
		ModelName: "qwen", RequestSHA256: testSHA256830G2("request-3"), TransportRetryIndex: 0,
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := journal.ProcessingReceipt(context.Background(), dispatchTestScope(), "kid", 9); err == nil {
		t.Fatal("open dispatch rows must prevent an AVAILABLE receipt")
	}
	// Re-entering the same worker retry can overlap a still-running generation;
	// it must not rewrite that live call as interrupted.
	if _, err := journal.WithParent(context.Background(), &Span{
		KnowledgeID: "kid", Attempt: 4, SpanID: "embedding", Name: types.StageEmbedding,
		Kind: types.SpanKindStage, Status: types.SpanStatusRunning, StartedAt: now,
	}, 0); err != nil {
		t.Fatal(err)
	}
	if _, err := journal.ProcessingReceipt(context.Background(), dispatchTestScope(), "kid", 9); err == nil {
		t.Fatal("same worker retry must leave concurrent open rows unsettled")
	}

	// A higher worker retry may reconcile only lower-generation open rows.
	if _, err := journal.WithParent(context.Background(), &Span{
		KnowledgeID: "kid", Attempt: 4, SpanID: "embedding", Name: types.StageEmbedding,
		Kind: types.SpanKindStage, Status: types.SpanStatusRunning, StartedAt: now,
	}, 1); err != nil {
		t.Fatal(err)
	}
	finished := now.Add(time.Second)
	seedDispatchSpan(t, repo, types.KnowledgeProcessingSpan{
		KnowledgeID: "kid", Attempt: 4, SpanID: "embedding", ParentSpanID: "root",
		Name: types.StageEmbedding, Kind: types.SpanKindStage, Status: types.SpanStatusDone,
		StartedAt: &now, FinishedAt: &finished, DurationMs: 1_000,
	})
	seedDispatchSpan(t, repo, types.KnowledgeProcessingSpan{
		KnowledgeID: "kid", Attempt: 4, SpanID: "root", Name: "root", Kind: types.SpanKindRoot,
		Status: types.SpanStatusDone, StartedAt: &now, FinishedAt: &finished, DurationMs: 1_000,
	})
	receipt, err := journal.ProcessingReceipt(context.Background(), dispatchTestScope(), "kid", 9)
	if err != nil {
		t.Fatal(err)
	}
	counts := receipt.Counts
	if counts == nil || counts.Attempts != 2 || counts.Confirmed != 1 || counts.Interrupted != 1 ||
		counts.NotDispatched != 1 || counts.TransportRetries != 1 || receipt.Calls == nil || len(*receipt.Calls) != 3 {
		t.Fatalf("unexpected dispatch counts: %#v calls=%#v", counts, receipt.Calls)
	}
}

func TestKnowledgeModelDispatchJournalReportsLegacyWithoutInventingZero(t *testing.T) {
	journal, repo := newKnowledgeDispatchJournalTest(t)
	now := time.Now()
	seedDispatchSpan(t, repo, types.KnowledgeProcessingSpan{
		KnowledgeID: "legacy", Attempt: 2, SpanID: "root", Name: "root", Kind: types.SpanKindRoot,
		Status: types.SpanStatusDone, StartedAt: &now, FinishedAt: &now,
	})
	receipt, err := journal.ProcessingReceipt(context.Background(), dispatchTestScope(), "legacy", 7)
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Availability != G3PlatformProcessingUnavailable ||
		receipt.UnavailabilityReason != "LEGACY_NO_JOURNAL" || receipt.Counts != nil || receipt.Calls != nil {
		t.Fatalf("legacy receipt falsely claimed known counts: %#v", receipt)
	}
}

func TestKnowledgeServiceEnablesJournalOnlyForConfiguredG3RawScope(t *testing.T) {
	_, repo := newKnowledgeDispatchJournalTest(t)
	tracker := NewSpanTracker(repo, nil)
	root, attempt, err := tracker.OpenAttempt(context.Background(), "kid", "")
	if err != nil || root == nil {
		t.Fatalf("OpenAttempt = (%#v, %d, %v)", root, attempt, err)
	}
	service := &knowledgeService{
		config: &config.Config{G3PlatformProcessing: &config.G3PlatformProcessingConfig{
			Enabled: true, TenantID: 17, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki",
		}},
		spanTracker: tracker,
	}
	knowledge := &types.Knowledge{ID: "kid", TenantID: 17, KnowledgeBaseID: "raw"}
	if err := service.ensureG3ModelDispatchJournal(context.Background(), knowledge, attempt, 9); err != nil {
		t.Fatal(err)
	}
	receipt, err := NewKnowledgeModelDispatchJournal(repo).ProcessingReceipt(
		context.Background(), dispatchTestScope(), "kid", 9,
	)
	if err != nil || receipt.Availability != G3PlatformProcessingAvailable {
		t.Fatalf("configured RAW receipt = (%#v, %v)", receipt, err)
	}

	otherRoot, otherAttempt, err := tracker.OpenAttempt(context.Background(), "other", "")
	if err != nil || otherRoot == nil {
		t.Fatal(err)
	}
	other := &types.Knowledge{ID: "other", TenantID: 17, KnowledgeBaseID: "another-kb"}
	if err := service.ensureG3ModelDispatchJournal(context.Background(), other, otherAttempt, 10); err != nil {
		t.Fatal(err)
	}
	legacy, err := NewKnowledgeModelDispatchJournal(repo).ProcessingReceipt(
		context.Background(), dispatchTestScope(), "other", 10,
	)
	if err != nil || legacy.Availability != G3PlatformProcessingUnavailable {
		t.Fatalf("other-scope receipt = (%#v, %v)", legacy, err)
	}
}

func TestG3PlatformProcessingReceiptWireFixture(t *testing.T) {
	journal, repo := newKnowledgeDispatchJournalTest(t)
	stamp := func(ms int64) *time.Time {
		value := time.UnixMilli(ms)
		return &value
	}
	for _, row := range []types.KnowledgeProcessingSpan{
		{KnowledgeID: "fixture-kid", Attempt: 3, SpanID: "root", Name: "root", Kind: types.SpanKindRoot,
			Status: types.SpanStatusDone, StartedAt: stamp(1_000), FinishedAt: stamp(1_900), DurationMs: 900},
		{KnowledgeID: "fixture-kid", Attempt: 3, SpanID: "doc", ParentSpanID: "root", Name: types.StageDocReader,
			Kind: types.SpanKindStage, Status: types.SpanStatusDone, StartedAt: stamp(1_000), FinishedAt: stamp(1_100), DurationMs: 100},
		{KnowledgeID: "fixture-kid", Attempt: 3, SpanID: "chunk", ParentSpanID: "root", Name: types.StageChunking,
			Kind: types.SpanKindStage, Status: types.SpanStatusDone, StartedAt: stamp(1_200), FinishedAt: stamp(1_250), DurationMs: 50},
		{KnowledgeID: "fixture-kid", Attempt: 3, SpanID: "embedding", ParentSpanID: "root", Name: types.StageEmbedding,
			Kind: types.SpanKindStage, Status: types.SpanStatusDone, StartedAt: stamp(1_300), FinishedAt: stamp(1_500), DurationMs: 200},
		{KnowledgeID: "fixture-kid", Attempt: 3, SpanID: "postprocess", ParentSpanID: "root", Name: types.StagePostProcess,
			Kind: types.SpanKindStage, Status: types.SpanStatusDone, StartedAt: stamp(1_500), FinishedAt: stamp(1_900), DurationMs: 400},
		{KnowledgeID: "fixture-kid", Attempt: 3, SpanID: "summary", ParentSpanID: "postprocess", Name: "postprocess.summary",
			Kind: types.SpanKindSubSpan, Status: types.SpanStatusFailed, StartedAt: stamp(1_600), FinishedAt: stamp(1_800), DurationMs: 200},
	} {
		seedDispatchSpan(t, repo, row)
	}
	if _, err := journal.EnsureEnabled(context.Background(), dispatchTestScope(), "fixture-kid", 3, 7); err != nil {
		t.Fatal(err)
	}
	requestA, requestB := testSHA256830G2("wire-request-a"), testSHA256830G2("wire-request-b")
	inputs := []knowledgeModelDispatchInput{
		{Contract: knowledgeModelDispatchReceiptContract, DispatchID: "dispatch-a", Operation: "embedding", Purpose: "document_embedding", ModelID: "qwen-id", ModelName: "qwen<&>", RequestSHA256: requestA, WorkerRetry: 0},
		{Contract: knowledgeModelDispatchReceiptContract, DispatchID: "dispatch-b", Operation: "embedding", Purpose: "summary_embedding", ModelID: "qwen-id", ModelName: "qwen<&>", RequestSHA256: requestB, TransportRetryIndex: 1, WorkerRetry: 0},
	}
	parents := []string{"embedding", "summary"}
	outcomes := []types.JSONMap{{"state": "RECORDED", "outcome": "HTTP_RESPONSE", "http_status": 200}, {"state": "RECORDED", "outcome": "TRANSPORT_ERROR"}}
	for i := range inputs {
		input, err := modelDispatchJSONMap(inputs[i])
		if err != nil {
			t.Fatal(err)
		}
		seedDispatchSpan(t, repo, types.KnowledgeProcessingSpan{
			KnowledgeID: "fixture-kid", Attempt: 3, SpanID: inputs[i].DispatchID, ParentSpanID: parents[i],
			Name: knowledgeModelDispatchNamePrefix + "embedding", Kind: types.SpanKindGeneration,
			Status: types.SpanStatusDone, Input: input, Metadata: types.JSONMap{"state": "RECORDED"},
			Output: outcomes[i], StartedAt: stamp(1_400 + int64(i)*300), FinishedAt: stamp(1_410 + int64(i)*300), DurationMs: 10,
		})
	}
	receipt, err := journal.ProcessingReceipt(context.Background(), dispatchTestScope(), "fixture-kid", 7)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join("testdata", "g3_platform_processing_receipt_v1.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture G3PlatformSourceProcessingReceiptV1
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	if receipt.ReceiptSHA256 != fixture.ReceiptSHA256 || receipt.JournalMarkerSHA256 != fixture.JournalMarkerSHA256 {
		t.Fatalf("wire hash drift: actual=%#v fixture=%#v", receipt, fixture)
	}
	encoded, err := canonicalJSON830G2(receipt)
	if err != nil {
		t.Fatal(err)
	}
	expected, err := canonicalJSON830G2(fixture)
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded) != string(expected) {
		t.Fatalf("wire fixture drift\nactual=%s\nfixture=%s", encoded, expected)
	}
	if err := validateG3PlatformSourceProcessingReceipt(fixture, dispatchTestScope(), "fixture-kid", 7); err != nil {
		t.Fatal(err)
	}
}

func TestKnowledgeG3DispatchParentExplicitlyDisablesModelRetry(t *testing.T) {
	journal, repo := newKnowledgeDispatchJournalTest(t)
	tracker := NewSpanTracker(repo, nil)
	parent, attempt, err := tracker.OpenAttempt(context.Background(), "retry-policy-kid", "")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = journal.EnsureEnabled(context.Background(), dispatchTestScope(), "retry-policy-kid", attempt, 9); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name    string
		enabled bool
		tenant  uint64
		kb      string
		want    bool
	}{
		{"g3", true, 17, "raw", true}, {"other_tenant", true, 18, "raw", false}, {"other_kb", true, 17, "other", false}, {"disabled_config", false, 17, "raw", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			service := &knowledgeService{config: &config.Config{G3PlatformProcessing: &config.G3PlatformProcessingConfig{Enabled: tc.enabled, TenantID: 17, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}}, spanTracker: tracker}
			base := context.Background()
			ctx, err := service.withG3ModelDispatchParent(base, &types.Knowledge{ID: "retry-policy-kid", TenantID: tc.tenant, KnowledgeBaseID: tc.kb}, parent)
			if err != nil {
				t.Fatal(err)
			}
			if types.ModelAutomaticRetryDisabled(ctx) != tc.want || types.ModelAutomaticRetryDisabled(base) {
				t.Fatalf("explicit retry policy=%v, want %v", types.ModelAutomaticRetryDisabled(ctx), tc.want)
			}
		})
	}
	// Journaling directly is not an implicit business retry policy.
	ctx, err := journal.WithParent(context.Background(), parent, 0)
	if err != nil || types.ModelAutomaticRetryDisabled(ctx) {
		t.Fatalf("journal alone changed retry policy: %v", err)
	}
}
