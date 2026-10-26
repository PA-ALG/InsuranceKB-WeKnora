package enterprise_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func TestReviewAPIKeyHistoricalReplayUsesOriginalReleaseAndKeepsHead(t *testing.T) {
	w := newReviewWorld(t)
	ctx := context.Background()
	actor := release.Principal{TenantID: 7, Subject: "svc-harness"}
	original := w.platform.releases[w.first.ID]
	c := w.platform.candidates[original.CandidateID]
	newer := w.decide(w.admin(), w.waiting.ID, decision("approve", "advance"))
	require.Equal(t, http.StatusCreated, newer.Code, newer.Body.String())
	// A different decision after Head has moved must still return the first release.
	d, err := w.releases.Decide(ctx, actor, "demo", c.ID,
		release.DecisionInput{Outcome: "approve", Mode: "human", Reason: "historical replay"})
	require.NoError(t, err)
	rejected, err := w.releases.Decide(ctx, actor, "demo", c.ID,
		release.DecisionInput{Outcome: "reject", Mode: "human", Reason: "cannot activate"})
	require.NoError(t, err)
	store := &concurrentReviews{reviewPlatform: w.platform}
	s := release.NewService(w.platform, nil, nil, release.WithPublisher(store))
	router := mountRouter(s, machineKey())
	head := w.platform.head
	for _, tc := range []struct {
		id     string
		status int
	}{{d.ID, http.StatusOK}, {rejected.ID, http.StatusConflict}} {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/spaces/demo/candidates/"+c.ID+"/activations",
			strings.NewReader(fmt.Sprintf(`{"decision_id":%q}`, tc.id)))
		req.Header.Set("X-API-Key", "test-key")
		req.Header.Set("Content-Type", "application/json")
		res := httptest.NewRecorder()
		router.ServeHTTP(res, req)
		require.Equal(t, tc.status, res.Code, res.Body.String())
		if tc.status == http.StatusOK {
			require.Equal(t, original.ID, dataOf(t, res)["id"])
		}
		require.Equal(t, head, w.platform.head)
		require.Len(t, w.platform.releases, 2)
	}
}

func TestReviewHeadMovesAfterPrecheckKeepsApproval(t *testing.T) {
	w := newReviewWorld(t)
	original := w.releases
	ctx := context.Background()
	actor := release.Principal{TenantID: 7, Subject: "svc-harness"}
	competing := w.submit(t, w.first.ID, claimMember(t, "P", "waiting", "240日"))
	d, err := original.Decide(ctx, actor, "demo", competing.ID,
		release.DecisionInput{Outcome: "approve", Mode: "machine", PolicyRef: "test"})
	require.NoError(t, err)
	publisher := &reviewFaultPublisher{reviewPlatform: w.platform}
	publisher.afterSave = func() {
		_, err := original.Activate(ctx, actor, "demo", competing.ID, d.ID)
		require.NoError(t, err)
	}
	w.releases = release.NewService(w.platform, nil, nil, release.WithPublisher(publisher))
	before := len(w.platform.decisions)
	res := w.decide(w.admin(), w.waiting.ID, decision("approve", "checked before Head moved"))
	require.Equal(t, http.StatusConflict, res.Code, res.Body.String())
	require.Equal(t, release.ErrorNeedsRebase, code(t, res.Body.Bytes()))
	require.Len(t, w.platform.decisions, before+1)
	detail := call(w.admin(), http.MethodGet, reviewsPath+"/"+w.waiting.ID, nil)
	require.Equal(t, "approved", dataOf(t, detail)["status"])
	require.Equal(t, release.ErrorNeedsRebase, dataOf(t, detail)["blocker"])
	res = w.decide(w.admin(), w.waiting.ID, decision("approve", "retry"))
	require.Equal(t, http.StatusConflict, res.Code)
	require.Len(t, w.platform.decisions, before+1, "failed retry precheck cannot replace the approval")
}

// The other reviewer commits between our read-only candidate lookup and Head read.
// Both requests already observed pending, so both decisions must remain attributed.
type reviewLookupRace struct {
	*concurrentReviews
	afterLookup func()
}

func (p *reviewLookupRace) SaveDecision(ctx context.Context, d release.Decision) (release.Decision, error) {
	return p.reviewPlatform.SaveDecision(ctx, d)
}

func (p *reviewLookupRace) PublishedCandidate(
	ctx context.Context, tenant uint64, space, digest string,
) (release.Release, bool, error) {
	r, found, err := p.concurrentReviews.PublishedCandidate(ctx, tenant, space, digest)
	if p.afterLookup != nil {
		callback := p.afterLookup
		p.afterLookup = nil
		callback()
	}
	return r, found, err
}

func TestReviewCandidateCommitsBetweenPrecheckLookupAndHead(t *testing.T) {
	for _, advanceAgain := range []bool{false, true} {
		t.Run(fmt.Sprint(advanceAgain), func(t *testing.T) { reviewPrecheckCommitRace(t, advanceAgain) })
	}
}

func reviewPrecheckCommitRace(t *testing.T, advanceAgain bool) {
	t.Helper()
	w := newReviewWorld(t)
	original := w.releases
	publisher := &reviewLookupRace{concurrentReviews: &concurrentReviews{reviewPlatform: w.platform}}
	var first release.Release
	publisher.afterLookup = func() {
		ctx := context.Background()
		p := release.Principal{TenantID: 7, Subject: "web_user:other-reviewer"}
		d, err := original.Decide(ctx, p, "demo", w.waiting.ID,
			release.DecisionInput{Outcome: "approve", Mode: "human", Reason: "concurrent approval"})
		require.NoError(t, err)
		first, err = original.Activate(ctx, p, "demo", w.waiting.ID, d.ID)
		require.NoError(t, err)
		if advanceAgain {
			// A later candidate touches the same slug, so merely comparing Head's
			// CandidateID cannot distinguish a replay from a stale unpublished bundle.
			source := &reviewWorld{releases: original}
			c := source.submit(t, first.ID, claimMember(t, "P", "waiting", "360日"))
			d, err := original.Decide(ctx, p, "demo", c.ID,
				release.DecisionInput{Outcome: "approve", Mode: "human", Reason: "advance again"})
			require.NoError(t, err)
			_, err = original.Activate(ctx, p, "demo", c.ID, d.ID)
			require.NoError(t, err)
		}
	}
	w.releases = release.NewService(w.platform, nil, nil, release.WithPublisher(publisher))
	res := w.decide(w.admin(), w.waiting.ID, decision("approve", "checked"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	require.Equal(t, first.ID, dataOf(t, res)["release_id"])
	require.Len(t, w.platform.history[w.waiting.ID], 2)
	count := 2
	if advanceAgain {
		count++
	}
	require.Len(t, w.platform.releases, count)
	require.EqualValues(t, count, w.platform.head.Epoch)
}
