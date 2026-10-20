package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
)

func overflowRoots(n int) []wikiDocumentWindow {
	windows := make([]wikiDocumentWindow, n)
	for i := range windows {
		var bodies []string
		for j := 0; j < 4; j++ {
			bodies = append(bodies, fmt.Sprintf("WINDOW[%d] part %d substantive text", i, j))
		}
		roots, _ := prepareWikiDocumentWindows(context.Background(), nil, 1, overflowChunks(bodies...))
		windows[i] = roots[0]
	}
	return windows
}

func TestCandidateOverflowSharesRootPoolAndKeepsSourceOrder(t *testing.T) {
	const roots = 4
	windows := overflowRoots(roots)
	type request struct{ root, phase int }
	started := make(chan request, roots*3)
	finished := make(chan request, roots*3)
	var gates [roots][3]chan struct{}
	for i := range gates {
		for j := range gates[i] {
			gates[i][j] = make(chan struct{})
		}
	}
	var active, peak, calls atomic.Int32
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		index := candidateWindowIndex(messages, roots)
		if index < 0 {
			return nil, errors.New("missing root marker")
		}
		ids := chunkNumbers(promptText(messages))
		phase := 0
		if len(ids) == 2 {
			phase = 1 + ids[0]/2
		}
		current := active.Add(1)
		defer active.Add(-1)
		calls.Add(1)
		for previous := peak.Load(); current > previous; previous = peak.Load() {
			if peak.CompareAndSwap(previous, current) {
				break
			}
		}
		req := request{index, phase}
		started <- req
		select {
		case <-gates[index][phase]:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
		finished <- req
		if phase == 0 {
			return overflowResponse(), nil
		}
		label := fmt.Sprintf("root-%d-child-%d", index, phase)
		return candidateAnswer(extractedItem{
			Slug: "entity/shared", Name: label, Description: label, Aliases: []string{label},
		}), nil
	}}
	type extraction struct {
		entities []extractedItem
		err      error
	}
	done := make(chan extraction, 1)
	go func() {
		e, _, _, err := (&wikiIngestService{}).extractCandidateSlugs(
			ctx, model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
		)
		done <- extraction{e, err}
	}()
	for phase := 0; phase < 3; phase++ {
		seen := map[int]bool{}
		for i := 0; i < roots; i++ {
			select {
			case req := <-started:
				if req.phase != phase || seen[req.root] {
					t.Fatalf("children must execute sequentially inside each root: %+v", req)
				}
				seen[req.root] = true
			case <-ctx.Done():
				t.Fatal("four overflowing roots deadlocked or lost a child")
			}
		}
		for i := roots - 1; i >= 0; i-- {
			close(gates[i][phase])
			select {
			case req := <-finished:
				if req != (request{i, phase}) {
					t.Fatalf("unexpected response order %+v", req)
				}
			case <-ctx.Done():
				t.Fatal("released response did not return")
			}
		}
	}
	select {
	case result := <-done:
		if result.err != nil || len(result.entities) != 1 {
			t.Fatalf("entities=%v err=%v", result.entities, result.err)
		}
		item := result.entities[0]
		var aliases []string
		for i := 0; i < roots; i++ {
			for phase := 1; phase < 3; phase++ {
				aliases = append(aliases, fmt.Sprintf("root-%d-child-%d", i, phase))
			}
		}
		if item.Name != aliases[0] || item.Description != aliases[0] || !equalStrings(item.Aliases, aliases) {
			t.Fatalf("first leaf must win regardless of completion order: %+v", item)
		}
	case <-ctx.Done():
		t.Fatal("candidate pool did not finish")
	}
	if calls.Load() != 12 || peak.Load() != roots || active.Load() != 0 {
		t.Fatalf("calls=%d peak=%d remaining=%d", calls.Load(), peak.Load(), active.Load())
	}
}

func TestCandidateOverflowCollectsFailedChildrenAndAlreadySentPeer(t *testing.T) {
	windows := overflowRoots(2)
	peerStarted := make(chan struct{})
	childrenDone := make(chan struct{})
	releasePeer := make(chan struct{})
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	var calls atomic.Int32
	model := &windowChat{answer: func(ctx context.Context, messages []chat.Message) (*types.ChatResponse, error) {
		calls.Add(1)
		index := candidateWindowIndex(messages, 2)
		if index == 1 {
			close(peerStarted)
			select {
			case <-releasePeer:
				return candidateAnswer(extractedItem{Name: "Peer", Slug: "entity/peer"}), nil
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
		ids := chunkNumbers(promptText(messages))
		if len(ids) == 4 {
			select {
			case <-peerStarted:
				return overflowResponse(), nil
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
		if ids[0] == 0 {
			return &types.ChatResponse{Content: "invalid", FinishReason: "stop"}, nil
		}
		close(childrenDone)
		return nil, io.EOF
	}}
	done := make(chan error, 1)
	go func() {
		e, c, items, err := (&wikiIngestService{}).extractCandidateSlugs(
			ctx, model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
		)
		if len(e)+len(c)+len(items) != 0 {
			done <- errors.New("partial candidates escaped")
			return
		}
		done <- err
	}()
	select {
	case <-childrenDone:
	case <-ctx.Done():
		t.Fatal("failed child suppressed its sibling or cancelled the peer")
	}
	select {
	case err := <-done:
		t.Fatalf("candidate stage returned before its already-sent peer: %v", err)
	default:
	}
	close(releasePeer)
	select {
	case err := <-done:
		if wikiFailureOutcome(err) != wikiOutcomeUnknown || !errors.Is(err, io.EOF) || calls.Load() != 4 {
			t.Fatalf("calls=%d err=%v", calls.Load(), err)
		}
	case <-ctx.Done():
		t.Fatal("candidate stage did not collect peer result")
	}
}

func TestCandidateOverflowFailurePriorityOverCancelledSibling(t *testing.T) {
	for _, unknown := range []bool{false, true} {
		t.Run(fmt.Sprintf("unknown=%v", unknown), func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			windows := overflowRoots(1)
			calls := 0
			model := &windowChat{answer: func(_ context.Context, messages []chat.Message) (*types.ChatResponse, error) {
				calls++
				if len(chunkNumbers(promptText(messages))) == 4 {
					return overflowResponse(), nil
				}
				cancel()
				if unknown {
					return nil, io.EOF
				}
				return &types.ChatResponse{Content: "invalid"}, nil
			}}
			_, _, _, err := (&wikiIngestService{}).extractCandidateSlugs(
				ctx, model, "kb", windows, "en", nil, wikiOutcomeBatchContext(),
			)
			want := wikiOutcomeFailed
			if unknown {
				want = wikiOutcomeUnknown
			}
			if calls != 2 || wikiFailureOutcome(err) != want || !errors.Is(err, context.Canceled) {
				t.Fatalf("failure must dominate unsent sibling: calls=%d err=%v", calls, err)
			}
			if len(windows[0].chunks) != 4 {
				t.Fatal("root membership changed")
			}
		})
	}
}
