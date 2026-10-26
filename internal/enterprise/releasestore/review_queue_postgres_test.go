package releasestore

// RV5a acceptance (protected, written by Claude): the review queue derives each candidate's
// status from its latest decision and from the release it became (Spec
// docs/design/slices/RV5a-人工审核队列平台.md §2–§3). Requires WEKNORA_TEST_POSTGRES_URL.

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

var (
	humanApprove = release.DecisionInput{Outcome: "approve", Mode: "human", Reason: "checked"}
	humanReject  = release.DecisionInput{Outcome: "reject", Mode: "human", Reason: "wrong value"}
)

func queueOf(t *testing.T, store *Store, tenant uint64, space, status string, limit int) []release.QueueEntry {
	t.Helper()
	var queue release.QueueStore = store
	entries, err := queue.Queue(context.Background(), tenant, space, status, limit)
	require.NoError(t, err)
	return entries
}

func idsOf(entries []release.QueueEntry) []string {
	ids := make([]string, 0, len(entries))
	for _, e := range entries {
		ids = append(ids, e.Candidate.ID)
	}
	return ids
}

// submitCandidate stores one candidate per call; distinct slugs keep bundle digests distinct, and the
// short pause keeps created_at strictly increasing.
func submitCandidate(t *testing.T, s *release.Service, space, slug string) release.Candidate {
	t.Helper()
	c, err := s.Receive(context.Background(), principal, space, rawBundle(t, "", slug, `{"v":1}`))
	require.NoError(t, err)
	time.Sleep(5 * time.Millisecond)
	return c
}

func decideCandidate(t *testing.T, s *release.Service, c release.Candidate, in release.DecisionInput) release.Decision {
	t.Helper()
	d, err := s.Decide(context.Background(), principal, c.SpaceID, c.ID, in)
	require.NoError(t, err)
	time.Sleep(5 * time.Millisecond)
	return d
}

func TestPostgresReviewQueueDerivesEachStatus(t *testing.T) {
	store := New(openSchema(t), testSpaces(t))
	s := service(store)
	ctx := context.Background()

	pending := submitCandidate(t, s, "space-1", "a")
	rejected := submitCandidate(t, s, "space-1", "b")
	approved := submitCandidate(t, s, "space-1", "c")
	released := submitCandidate(t, s, "space-1", "d")
	flipped := submitCandidate(t, s, "space-1", "e")

	decideCandidate(t, s, rejected, humanReject)
	decideCandidate(t, s, approved, humanApprove)
	d := decideCandidate(t, s, released, humanApprove)
	r, err := s.Activate(ctx, principal, "space-1", released.ID, d.ID)
	require.NoError(t, err)
	decideCandidate(t, s, flipped, humanReject)
	decideCandidate(t, s, flipped, humanApprove) // the latest decision wins

	waiting := queueOf(t, store, 7, "space-1", "pending", 100)
	require.Equal(t, []string{pending.ID}, idsOf(waiting))
	require.Equal(t, "pending", waiting[0].Candidate.Status)
	require.Nil(t, waiting[0].Decision)
	require.Empty(t, waiting[0].ReleaseID)
	require.Equal(t, principal.Subject, waiting[0].CreatedBy)
	require.False(t, waiting[0].CreatedAt.IsZero())
	require.Equal(t, pending.BundleDigest, waiting[0].Candidate.BundleDigest)

	decided := queueOf(t, store, 7, "space-1", "decided", 100)
	require.Equal(t, []string{flipped.ID, released.ID, approved.ID, rejected.ID}, idsOf(decided),
		"decided candidates come newest first")
	status := map[string]release.QueueEntry{}
	for _, e := range decided {
		status[e.Candidate.ID] = e
	}
	require.Equal(t, "rejected", status[rejected.ID].Candidate.Status)
	require.Equal(t, "reject", status[rejected.ID].Decision.Outcome)
	require.Equal(t, "wrong value", status[rejected.ID].Decision.Reason)
	require.False(t, status[rejected.ID].Decision.CreatedAt.IsZero())
	require.Equal(t, "approved", status[approved.ID].Candidate.Status)
	require.Empty(t, status[approved.ID].ReleaseID, "approved but never activated")
	require.Equal(t, "released", status[released.ID].Candidate.Status)
	require.Equal(t, r.ID, status[released.ID].ReleaseID)
	require.Equal(t, "approved", status[flipped.ID].Candidate.Status)
	require.Equal(t, "approve", status[flipped.ID].Decision.Outcome)
}

func TestPostgresReviewQueueOrdersPendingOldestFirstAndLimitsDecided(t *testing.T) {
	store := New(openSchema(t), testSpaces(t))
	s := service(store)
	var waiting []string
	for i := 0; i < 3; i++ {
		waiting = append(waiting, submitCandidate(t, s, "space-1", fmt.Sprintf("p-%d", i)).ID)
	}
	var rejected []string
	for i := 0; i < 3; i++ {
		c := submitCandidate(t, s, "space-1", fmt.Sprintf("r-%d", i))
		decideCandidate(t, s, c, humanReject)
		rejected = append(rejected, c.ID)
	}
	require.Equal(t, waiting, idsOf(queueOf(t, store, 7, "space-1", "pending", 1)),
		"the pending list is complete whatever the limit")
	require.Equal(t, []string{rejected[2], rejected[1]}, idsOf(queueOf(t, store, 7, "space-1", "decided", 2)))
}

func TestPostgresReviewQueueKeepsTenantsAndSpacesApart(t *testing.T) {
	store := New(openSchema(t), testSpaces(t))
	s := service(store)
	mine := submitCandidate(t, s, "space-1", "a")
	other := submitCandidate(t, s, "space-2", "a")
	decideCandidate(t, s, submitCandidate(t, s, "space-2", "b"), humanReject)

	require.Equal(t, []string{mine.ID}, idsOf(queueOf(t, store, 7, "space-1", "pending", 100)))
	require.Empty(t, queueOf(t, store, 7, "space-1", "decided", 100))
	require.Equal(t, []string{other.ID}, idsOf(queueOf(t, store, 7, "space-2", "pending", 100)))
	require.Empty(t, queueOf(t, store, 8, "space-1", "pending", 100), "another tenant sees nothing")
	require.Empty(t, queueOf(t, store, 7, "space-unconfigured", "pending", 100))
}
