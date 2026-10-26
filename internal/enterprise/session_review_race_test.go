package enterprise_test

import (
	"bytes"
	"context"
	"encoding/json"
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
	if r, found := p.published(write.TenantID, write.SpaceID, write.BundleDigest); found {
		return r, nil
	}
	return p.reviewPlatform.Activate(ctx, write)
}

func (p *concurrentReviews) published(tenant uint64, space, digest string) (release.Release, bool) {
	for _, r := range p.releases {
		c := p.candidates[r.CandidateID]
		if c.TenantID == tenant && c.SpaceID == space && c.BundleDigest == digest {
			return r, true
		}
	}
	return release.Release{}, false
}

func (p *concurrentReviews) PublishedCandidate(
	_ context.Context, tenant uint64, space, digest string,
) (release.Release, bool, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	r, found := p.published(tenant, space, digest)
	return r, found, nil
}

func TestReviewConcurrentCandidateHasOneActivation(t *testing.T) {
	for _, noOp := range []bool{false, true} {
		t.Run(map[bool]string{false: "changed", true: "no-op"}[noOp], func(t *testing.T) {
			concurrentReview(t, noOp)
		})
	}
}

func concurrentReview(t *testing.T, noOp bool) {
	t.Helper()
	w := newReviewWorld(t)
	if noOp {
		w.waiting = w.submit(t, w.first.ID, claimMember(t, "P", "waiting", "90日"))
		require.Equal(t, w.first.Members[0].MemberDigest, w.platform.bundles[w.waiting.ID].Members[0].MemberDigest)
	}
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
	releaseIDs := []string{}
	for range handlers {
		select {
		case res := <-responses:
			statuses = append(statuses, res.Code)
			require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
			var body struct {
				Data struct {
					ReleaseID string `json:"release_id"`
				} `json:"data"`
			}
			require.NoError(t, json.Unmarshal(res.Body.Bytes(), &body))
			releaseIDs = append(releaseIDs, body.Data.ReleaseID)
		case <-ctx.Done():
			t.Fatal("concurrent approval did not finish before its deadline")
		}
	}
	require.ElementsMatch(t, []int{http.StatusCreated, http.StatusCreated}, statuses)
	require.NotEmpty(t, releaseIDs[0])
	require.Equal(t, releaseIDs[0], releaseIDs[1])
	require.Equal(t, 2, store.saved, "both independently attributed decisions remain")
	require.Len(t, store.releases, 2, "the seed and exactly one activation of the changed candidate")
	require.Equal(t, uint64(2), store.head.Epoch)
}
