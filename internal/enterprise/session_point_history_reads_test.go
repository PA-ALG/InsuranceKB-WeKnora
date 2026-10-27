package enterprise_test

import (
	"context"
	"net/http"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func TestPointHistoryIsNotLoadedByListsOrDetails(t *testing.T) {
	for _, complete := range []bool{false, true} {
		status := "pending"
		if complete {
			status = "decided"
		}
		t.Run(status, func(t *testing.T) {
			w := newPointWorld(t)
			first := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "first", "Q/waiting", "Q/grace"))
			require.Equal(t, http.StatusCreated, first.Code, first.Body.String())
			firstID := dataOf(t, first)["release_id"].(string)
			second := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "second", "entity/P"))
			require.Equal(t, http.StatusCreated, second.Code, second.Body.String())
			secondID := dataOf(t, second)["release_id"].(string)
			slugs := []string{"P/waiting"}
			if complete {
				slugs = append(slugs, "P/old")
			}
			rejected := w.decidePoints(w.admin(), w.cand.ID, pointsBody("reject", "later rejection", slugs...))
			require.Equal(t, http.StatusCreated, rejected.Code, rejected.Body.String())
			// Give detail a distinct Head: neither historical point release is needed for blockers.
			w.machine(t, w.submitWith(t, w.points.head.ReleaseID, nil, claimMember(t, "Next", "value", "1")))
			head := w.points.head
			saved := w.points.points[pointKey(w.cand.ID, "Q/waiting")]
			counter := countPointReads(w)
			item := w.listed(t, status, w.cand.ID)
			require.Empty(t, counter.releasesRead, "list must not load any point release content")
			require.Equal(t, secondID, item["release_id"], "later rejection does not replace the latest approval")
			require.Equal(t, 1, counter.membersRead[w.first.ID], "base is still digest-only")
			detail := w.detail(t, w.cand.ID)
			require.Equal(t, map[string]int{head.ReleaseID: 1}, counter.releasesRead,
				"only current Head content is needed for detail blockers")
			require.Equal(t, secondID, detail["release_id"])
			require.Equal(t, 2, counter.membersRead[w.first.ID], "each request owns its base cache")
			wantStatus := "pending"
			if complete {
				wantStatus = "released"
			}
			require.Equal(t, wantStatus, item["status"])
			require.Equal(t, wantStatus, detail["status"])
			counter.releasesRead, counter.membersRead, counter.heads = map[string]int{}, map[string]int{}, 0
			replayed := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "retry", "Q/grace", "Q/waiting"))
			require.Equal(t, http.StatusCreated, replayed.Code, replayed.Body.String())
			require.Equal(t, firstID, dataOf(t, replayed)["release_id"])
			require.Equal(t, map[string]int{firstID: 1}, counter.releasesRead, "only actual replay needs history")
			require.Zero(t, counter.heads)
			require.Equal(t, 1, counter.membersRead[w.first.ID])
			require.Equal(t, head, w.points.head)
			require.Equal(t, saved, w.points.points[pointKey(w.cand.ID, "Q/waiting")])
		})
	}
}

func TestPointRequiredHeadAndReplayReadFailuresStillPropagate(t *testing.T) {
	w := newPointWorld(t)
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "first", "Q/waiting", "Q/grace"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	historyID := dataOf(t, res)["release_id"].(string)
	w.machine(t, w.submitWith(t, w.points.head.ReleaseID, nil, claimMember(t, "Next", "value", "1")))
	counter := countPointReads(w)
	failure := &release.Error{Code: release.ErrorReleaseNotFound}
	counter.releaseErrors = map[string]error{historyID: failure}
	// An irrelevant historical content failure must not break list/detail metadata.
	require.Equal(t, historyID, w.listed(t, "pending", w.cand.ID)["release_id"])
	require.Equal(t, historyID, w.detail(t, w.cand.ID)["release_id"])
	_, err := w.releases.ReviewPoints(context.Background(), harnessKey, "demo", w.cand.ID,
		[]string{"Q/grace", "Q/waiting"}, "approve", "retry")
	require.ErrorIs(t, err, failure, "an actual historical replay still requires its release")
	counter.releaseErrors[w.points.head.ReleaseID] = context.Canceled
	_, err = w.releases.ReviewCandidate(context.Background(), harnessKey, "demo", w.cand.ID)
	require.ErrorIs(t, err, context.Canceled, "detail cannot ignore a necessary Head read failure")
}
