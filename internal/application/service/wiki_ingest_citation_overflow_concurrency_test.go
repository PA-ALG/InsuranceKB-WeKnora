package service

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestCitationOverflowCancellationDoesNotSendRemainingChildren(t *testing.T) {
	for _, tc := range []struct {
		name     string
		cancelAt int
		succeed  bool
		calls    int
		outcome  string
	}{
		{"before root", 0, false, 0, wikiOutcomeNotRun},
		{"after root overflow", 1, false, 1, wikiOutcomeNotRun},
		{"during first child", 2, false, 2, wikiOutcomeUnknown},
		{"after first child success", 2, true, 2, wikiOutcomeNotRun},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if tc.cancelAt == 0 {
				cancel()
			}
			calls := 0
			model := &windowChat{answer: func(ctx context.Context, _ []chat.Message) (*types.ChatResponse, error) {
				calls++
				if calls == tc.cancelAt {
					cancel()
				}
				if calls == 1 {
					return citationOverflowAnswer(), nil
				}
				if tc.succeed {
					return &types.ChatResponse{Content: `{"citations":{"entity/known":["c000"]}}`}, nil
				}
				return nil, ctx.Err()
			}}
			out := (&wikiIngestService{}).classifyChunkCitations(
				ctx, model, "entity/known", citationOverflowChunks(4), "en", wikiOutcomeBatchContext(), nil,
			)
			require.Equal(t, tc.calls, calls)
			require.Equal(t, tc.outcome, wikiFailureOutcome(out.Err()), "%v", out.Err())
			if tc.succeed {
				require.Equal(t, []string{"source-chunk-0"}, out.Citations["entity/known"])
			}
		})
	}
}

func TestCitationOverflowKeepsOnePoolAndSuccessfulSiblings(t *testing.T) {
	var windows []wikiDocumentWindow
	var chunks []*types.Chunk
	for i := 0; i < 6; i++ {
		members := []*types.Chunk{
			windowChunk(fmt.Sprintf("left-%d", i), i*2, "left source"),
			windowChunk(fmt.Sprintf("right-%d", i), i*2+1, "right source"),
		}
		windows = append(windows, wikiDocumentWindow{
			content: "source", candidates: "entity/known", chunks: members,
		})
		chunks = append(chunks, members...)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	started := make(chan struct{}, 6)
	release := make(chan struct{})
	var active, peak atomic.Int32
	var mu sync.Mutex
	visits := make(map[int][]int)
	model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		_, indexes := citationCallMembers(messages)
		n := active.Add(1)
		defer active.Add(-1)
		for old := peak.Load(); n > old; old = peak.Load() {
			if peak.CompareAndSwap(old, n) {
				break
			}
		}
		mu.Lock()
		root := indexes[0] / 2
		visits[root] = append(visits[root], len(indexes))
		mu.Unlock()
		if len(indexes) > 1 {
			started <- struct{}{}
			select {
			case <-release:
				return citationOverflowAnswer(), nil
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
		// A parse failure in the first child must not suppress its sibling.
		if indexes[0] == 0 {
			return &types.ChatResponse{Content: "{"}, nil
		}
		return &types.ChatResponse{Content: `{"citations":{"entity/known":["c000"]}}`}, nil
	}}
	done := make(chan citationClassificationOutcome, 1)
	go func() {
		done <- (&wikiIngestService{}).classifyChunkCitations(
			ctx, model, "entity/known", chunks, "en", wikiOutcomeBatchContext(), nil, windows,
		)
	}()
	timer := time.NewTimer(10 * time.Second)
	defer timer.Stop()
	for i := 0; i < 4; i++ {
		select {
		case <-started:
		case <-timer.C:
			t.Fatal("root citation pool did not fill")
		}
	}
	close(release)
	var out citationClassificationOutcome
	select {
	case out = <-done:
	case <-timer.C:
		t.Fatal("split children blocked inside the root pool")
	}
	require.EqualValues(t, 4, peak.Load())
	require.Equal(t, wikiOutcomeFailed, wikiFailureOutcome(out.Err()))
	require.Len(t, out.BatchErrors, 6)
	require.Error(t, out.BatchErrors[0])
	for i := 1; i < 6; i++ {
		require.NoError(t, out.BatchErrors[i])
	}
	for i := 0; i < 6; i++ {
		require.Equal(t, []int{2, 1, 1}, visits[i])
	}
	var want []string
	for _, chunk := range chunks[1:] {
		want = append(want, chunk.ID)
	}
	require.Equal(t, want, out.Citations["entity/known"])
}
