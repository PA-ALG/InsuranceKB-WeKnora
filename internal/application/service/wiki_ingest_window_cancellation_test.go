package service

import (
	"context"
	"errors"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

// Production uses tenant-scoped request coalescing. Cancellation must be
// classified before an unsent worker enters its asynchronous response select.
func TestWindowTenantCancellationTracksUnsentCalls(t *testing.T) {
	for _, stage := range []string{"candidate", "citation"} {
		for _, preCancelled := range []bool{true, false} {
			t.Run(fmt.Sprintf("%s/pre_cancelled=%v", stage, preCancelled), func(t *testing.T) {
				const n = 7
				windows := candidateWindows(n)
				var chunks []*types.Chunk
				for i := range windows {
					windows[i].chunks = []*types.Chunk{windowChunk(fmt.Sprintf("source-%d", i), i, windows[i].content)}
					windows[i].candidates = "entity/shared"
					chunks = append(chunks, windows[i].chunks...)
				}
				tenantCtx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
				ctx, cancel := context.WithCancel(tenantCtx)
				defer cancel()
				started := make(chan struct{}, n)
				finished := make(chan struct{}, n)
				var calls atomic.Int32
				model := &windowChat{answer: func(ctx context.Context, _ []chat.Message) (*types.ChatResponse, error) {
					calls.Add(1)
					started <- struct{}{}
					<-ctx.Done()
					finished <- struct{}{}
					return nil, ctx.Err()
				}}
				type cancellationResult struct {
					err      error
					failures []error
					partial  bool
				}
				done := make(chan cancellationResult, 1)
				if preCancelled {
					cancel()
				}
				svc := &wikiIngestService{}
				go func() {
					if stage == "citation" {
						outcome := svc.classifyChunkCitations(
							ctx, model, "entity/shared", chunks, "en", wikiOutcomeBatchContext(), nil, windows,
						)
						done <- cancellationResult{
							err:      outcome.Err(),
							failures: outcome.BatchErrors,
							partial:  len(outcome.Citations)+len(outcome.NewSlugs) > 0,
						}
						return
					}
					entities, concepts, items, err := svc.extractCandidateSlugs(
						ctx, model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
					)
					var failure *wikiStageFailure
					var failures []error
					if errors.As(err, &failure) {
						if joined, ok := failure.Cause.(interface{ Unwrap() []error }); ok {
							failures = joined.Unwrap()
						}
					}
					done <- cancellationResult{
						err:      err,
						failures: failures,
						partial:  len(entities)+len(concepts)+len(items) > 0,
					}
				}()
				timer := time.NewTimer(10 * time.Second)
				defer timer.Stop()
				if !preCancelled {
					for i := 0; i < 4; i++ {
						select {
						case <-started:
						case <-timer.C:
							t.Fatal("first four calls were not sent")
						}
					}
					cancel()
				}
				var result cancellationResult
				select {
				case result = <-done:
				case <-timer.C:
					t.Fatal("cancelled work did not settle")
				}
				wantCalls := int32(4)
				wantOutcome := wikiOutcomeUnknown
				if preCancelled {
					wantCalls = 0
					wantOutcome = wikiOutcomeNotRun
				}
				if calls.Load() != wantCalls || result.partial || wikiFailureOutcome(result.err) != wantOutcome ||
					len(result.failures) != n {
					t.Fatalf(
						"calls=%d want=%d partial=%v failures=%d outcome=%v want=%s", calls.Load(), wantCalls,
						result.partial, len(result.failures), result.err, wantOutcome,
					)
				}
				for i, err := range result.failures {
					want := wikiOutcomeNotRun
					if !preCancelled && i < 4 {
						want = wikiOutcomeUnknown
					}
					if wikiFailureOutcome(err) != want {
						t.Fatalf("job %d outcome=%s want=%s", i, wikiFailureOutcome(err), want)
					}
				}
				for i := int32(0); i < wantCalls; i++ {
					select {
					case <-finished:
					case <-timer.C:
						t.Fatal("sent fake call did not stop")
					}
				}
			})
		}
	}
}
