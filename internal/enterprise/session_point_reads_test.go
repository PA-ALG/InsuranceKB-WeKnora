package enterprise_test

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func countPointReads(w *pointWorld) *pointReadCounter {
	counter := &pointReadCounter{pointPlatform: w.points, releasesRead: map[string]int{}}
	w.releases = release.NewService(counter, nil, nil, release.WithPublisher(counter))
	return counter
}

func TestPointBaseReadsOnlyDigestsOncePerRequest(t *testing.T) {
	w := newPointWorld(t)
	w.machine(t, w.submitWith(t, w.first.ID, nil, claimMember(t, "P", "grace", "40日")))
	counter := countPointReads(w)
	for i := 1; i <= 2; i++ {
		items := w.items(t, "pending")
		require.NotEmpty(t, items)
		require.Equal(t, i, counter.membersRead[w.first.ID], "cache is shared only within one request")
		require.Empty(t, counter.releasesRead, "a base-only list must not fetch full member payloads")
	}
	detail := w.detail(t, w.cand.ID)
	require.EqualValues(t, 5, detail["point_count"])
	require.Equal(t, 3, counter.membersRead[w.first.ID])
	require.Equal(t, map[string]int{w.points.head.ReleaseID: 1}, counter.releasesRead,
		"detail still needs full Head, but not full base")
}

func TestPointBaseDigestFailuresPropagateAndEmptyBaseNeedsNoLookup(t *testing.T) {
	for _, failure := range []error{
		&release.Error{Code: release.ErrorReleaseNotFound}, context.Canceled, errors.New("digest read failed"),
	} {
		t.Run(failure.Error(), func(t *testing.T) {
			w := newPointWorld(t)
			counter := countPointReads(w)
			counter.membersError = failure
			_, err := w.releases.ReviewQueue(context.Background(), harnessKey, "demo", "pending")
			require.ErrorIs(t, err, failure)
			require.Empty(t, counter.releasesRead, "do not fall back to full payloads on errors")
			counter.membersError = nil
			require.NotEmpty(t, w.items(t, "pending"), "a later request retries the failed digest read")
		})
	}
	w := newPointWorld(t)
	c := w.submitWith(t, "", nil, claimMember(t, "First", "value", "1"))
	counter := countPointReads(w)
	res := w.decidePoints(w.admin(), c.ID, pointsBody("reject", "no", "First/value"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	require.Empty(t, counter.membersRead)
	require.Empty(t, counter.releasesRead)
}

func TestPointDecidedQueueReadsOnlyVisibleWholeBundles(t *testing.T) {
	w := newPointWorld(t)
	pending := []release.Candidate{
		w.submitWith(t, w.first.ID, nil, claimMember(t, "StillPending", "one", "1")),
		w.submitWith(t, w.first.ID, nil, claimMember(t, "StillPending", "two", "2")),
	}
	type ordered struct {
		id   string
		last time.Time
	}
	var expected []ordered
	whole := map[string]bool{}
	tie := time.Date(2030, 1, 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 105; i++ {
		c := w.submitWith(t, w.first.ID, nil, claimMember(t, fmt.Sprintf("R%d", i), "value", "1"))
		res := w.decide(w.admin(), c.ID, decision("reject", "whole"))
		require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
		id := w.points.history[c.ID][0]
		d := w.points.decisions[id]
		d.CreatedAt = tie
		if i == 0 {
			d.CreatedAt = tie.Add(time.Second) // oldest-created candidate has a newer decision
		}
		w.points.decisions[id] = d
		expected = append(expected, ordered{c.ID, d.CreatedAt})
		whole[c.ID] = true
	}
	// Whole publication with no decision uses creation time as its sorting fallback.
	seed := w.points.releases[w.first.ID].CandidateID
	w.points.history[seed] = nil
	w.points.created[seed] = tie.Add(3 * time.Second)
	expected = append(expected, ordered{seed, w.points.created[seed]})
	whole[seed] = true
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("reject", "last point",
		"P/waiting", "P/old", "Q/waiting", "Q/grace", "entity/P"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	for key, d := range w.points.points {
		d.CreatedAt = tie.Add(2 * time.Second)
		w.points.points[key] = d
	}
	expected = append(expected, ordered{w.cand.ID, tie.Add(2 * time.Second)})
	sort.Slice(expected, func(i, j int) bool {
		if expected[i].last.Equal(expected[j].last) {
			return expected[i].id > expected[j].id
		}
		return expected[i].last.After(expected[j].last)
	})
	expected = expected[:100]
	counter := countPointReads(w)
	items := w.items(t, "decided")
	require.Len(t, items, 100)
	visible := map[string]bool{}
	for i, item := range items {
		id := item["candidate_id"].(string)
		require.Equal(t, expected[i].id, id, "last descending, tied id descending")
		visible[id] = true
	}
	require.True(t, visible[w.cand.ID], "fully decided SQL-pending candidate must participate in ranking")
	for id := range whole {
		want := 0
		if visible[id] {
			want = 1
		}
		require.Equal(t, want, counter.bundlesRead[id], id)
	}
	for _, c := range append(pending, w.cand) {
		require.Equal(t, 1, counter.bundlesRead[c.ID], "pending classification reads reused for display")
	}
	require.Equal(t, 1, counter.membersRead[w.first.ID])
	require.Empty(t, counter.releasesRead)
}

type pointQueueTransition struct {
	*pointReadCounter
	afterPending func()
	badDecided   bool
}

func (p *pointQueueTransition) Queue(
	ctx context.Context, tenant uint64, space, status string, limit int,
) ([]release.QueueEntry, error) {
	entries, err := p.pointPlatform.Queue(ctx, tenant, space, status, limit)
	if status == "pending" && p.afterPending != nil {
		callback := p.afterPending
		p.afterPending = nil
		callback()
	}
	if status == "decided" && p.badDecided && len(entries) > 0 {
		entries[0].Candidate.TenantID++
	}
	return entries, err
}

func TestPointQueueRefreshesWholeDecisionMetadataBetweenQueries(t *testing.T) {
	w := newPointWorld(t)
	original := w.releases
	counter := countPointReads(w)
	store := &pointQueueTransition{pointReadCounter: counter}
	store.afterPending = func() {
		_, err := original.Decide(context.Background(), harnessKey, "demo", w.cand.ID,
			release.DecisionInput{Outcome: "reject", Mode: "machine", Reason: "concurrent", PolicyRef: "test"})
		require.NoError(t, err)
	}
	w.releases = release.NewService(store, nil, nil, release.WithPublisher(store))
	items := w.items(t, "decided")
	require.Equal(t, w.cand.ID, items[0]["candidate_id"])
	require.Equal(t, "rejected", items[0]["status"])
	require.Equal(t, "concurrent", items[0]["decision"].(map[string]any)["reason"])
	require.Equal(t, 1, counter.bundlesRead[w.cand.ID], "reuse bundle but not stale pending status/audit")
}

func TestPointQueueStillValidatesMetadataBeforeBundleReads(t *testing.T) {
	w := newPointWorld(t)
	counter := countPointReads(w)
	store := &pointQueueTransition{pointReadCounter: counter, badDecided: true}
	w.releases = release.NewService(store, nil, nil, release.WithPublisher(store))
	_, err := w.releases.ReviewQueue(context.Background(), harnessKey, "demo", "decided")
	var typed *release.Error
	require.ErrorAs(t, err, &typed)
	require.Equal(t, release.ErrorCandidateNotFound, typed.Code)
	seed := w.points.releases[w.first.ID].CandidateID
	require.Zero(t, counter.bundlesRead[seed], "fail closed on whole-candidate metadata before content lookup")
}
