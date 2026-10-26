package enterprise_test

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// Synchronize individual storage operations, never the service workflow: both reviewers
// must read pending and save their approvals before either activation is allowed to run.
type concurrentReviews struct {
	*reviewPlatform
	mu           sync.Mutex
	queued       int
	saved        int
	queueReady   chan struct{}
	decidedReady chan struct{}
}

func (p *concurrentReviews) CandidateByID(
	ctx context.Context, tenant uint64, space, id string,
) (release.Candidate, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.reviewPlatform.CandidateByID(ctx, tenant, space, id)
}

func (p *concurrentReviews) BundleOf(ctx context.Context, tenant uint64, space, id string) (release.Bundle, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.reviewPlatform.BundleOf(ctx, tenant, space, id)
}

func (p *concurrentReviews) Head(ctx context.Context, tenant uint64, space string) (release.Head, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.reviewPlatform.Head(ctx, tenant, space)
}

func (p *concurrentReviews) Queue(
	ctx context.Context, tenant uint64, space, status string, limit int,
) ([]release.QueueEntry, error) {
	p.mu.Lock()
	entries, err := p.reviewPlatform.Queue(ctx, tenant, space, status, limit)
	p.queued++
	if p.queued == 2 {
		close(p.queueReady)
	}
	p.mu.Unlock()
	select {
	case <-p.queueReady:
		return entries, err
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (p *concurrentReviews) SaveDecision(ctx context.Context, d release.Decision) (release.Decision, error) {
	p.mu.Lock()
	stored, err := p.reviewPlatform.SaveDecision(ctx, d)
	p.saved++
	if p.saved == 2 {
		close(p.decidedReady)
	}
	p.mu.Unlock()
	select {
	case <-p.decidedReady:
		return stored, err
	case <-ctx.Done():
		return release.Decision{}, ctx.Err()
	}
}

func (p *concurrentReviews) DecisionByID(
	ctx context.Context, tenant uint64, space, id string,
) (release.Decision, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.reviewPlatform.DecisionByID(ctx, tenant, space, id)
}

func (p *concurrentReviews) ReleaseByID(ctx context.Context, tenant uint64, space, id string) (release.Release, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.reviewPlatform.ReleaseByID(ctx, tenant, space, id)
}

func (p *concurrentReviews) Activate(ctx context.Context, write release.ActivationWrite) (release.Release, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.reviewPlatform.Activate(ctx, write)
}

func TestReviewConcurrentChangedCandidateHasOneActivation(t *testing.T) {
	w := newReviewWorld(t)
	store := &concurrentReviews{
		reviewPlatform: w.platform,
		queueReady:     make(chan struct{}), decidedReady: make(chan struct{}),
	}
	w.releases = release.NewService(store, nil, nil, release.WithPublisher(store))
	var handlers []http.Handler
	for _, user := range []string{"reviewer-a", "reviewer-b"} {
		handlers = append(handlers, w.router(identity{
			tenant:    7,
			principal: types.Principal{Type: types.PrincipalWebUser, ID: user},
		}, types.TenantRoleAdmin))
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	responses := make(chan *httptest.ResponseRecorder, 2)
	for _, handler := range handlers {
		go func(handler http.Handler) {
			req := httptest.NewRequest(http.MethodPost, reviewsPath+"/"+w.waiting.ID+"/decisions",
				bytes.NewReader(decision("approve", "checked"))).WithContext(ctx)
			req.Header.Set("Content-Type", "application/json")
			res := httptest.NewRecorder()
			handler.ServeHTTP(res, req)
			responses <- res
		}(handler)
	}
	statuses := []int{}
	for range handlers {
		select {
		case res := <-responses:
			statuses = append(statuses, res.Code)
			if res.Code == http.StatusConflict {
				require.Contains(t, []string{release.ErrorNeedsRebase, release.ErrorReleaseConflict},
					code(t, res.Body.Bytes()), res.Body.String())
			}
		case <-ctx.Done():
			t.Fatal("concurrent approval did not finish before its deadline")
		}
	}
	require.ElementsMatch(t, []int{http.StatusCreated, http.StatusConflict}, statuses)
	require.Equal(t, 2, store.saved, "both independently attributed decisions remain")
	require.Len(t, store.releases, 2, "the seed and exactly one activation of the changed candidate")
	require.Equal(t, uint64(2), store.head.Epoch)
}
