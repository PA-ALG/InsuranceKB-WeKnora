package enterprise_test

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

func TestPointBatchReplayKeepsOriginalAuditAndHistoricalRelease(t *testing.T) {
	w := newPointWorld(t)
	first := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "first", "Q/waiting", "Q/grace"))
	require.Equal(t, http.StatusCreated, first.Code, first.Body.String())
	id := dataOf(t, first)["release_id"]
	saved := w.points.points[pointKey(w.cand.ID, "Q/waiting")]
	next := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "next", "entity/P"))
	require.Equal(t, http.StatusCreated, next.Code, next.Body.String())
	head := w.points.head
	replay := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "different reason", "Q/grace", "Q/waiting"))
	require.Equal(t, http.StatusCreated, replay.Code, replay.Body.String())
	require.Equal(t, id, dataOf(t, replay)["release_id"])
	require.Equal(t, head, w.points.head)
	require.Equal(t, saved, w.points.points[pointKey(w.cand.ID, "Q/waiting")])
	for _, slugs := range [][]string{{"Q/waiting"}, {"Q/waiting", "entity/P"}, {"Q/waiting", "P/old"}} {
		res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "cannot compose batches", slugs...))
		require.Equal(t, http.StatusConflict, res.Code, res.Body.String())
		require.Equal(t, release.ErrorMemberDecided, code(t, res.Body.Bytes()))
	}
	require.Len(t, w.points.points, 3)
	require.Len(t, w.points.releases, 3)
}

func TestPointApprovalPreservesUnchangedAndUnselectedHeadMembers(t *testing.T) {
	w := newPointWorld(t)
	w.machine(t, w.submitWith(t, w.first.ID, nil, claimMember(t, "P", "grace", "40日")))
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "Q only", "Q/waiting"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	require.Equal(t, "40日", w.active(t)["P/grace"]["value"])
	require.Equal(t, "90日", w.active(t)["P/waiting"]["value"])
	require.NotContains(t, w.active(t), "Q/grace")
}

type pointReadCounter struct {
	*pointPlatform
	heads         int
	releasesRead  map[string]int
	membersRead   map[string]int
	bundlesRead   map[string]int
	membersError  error
	releaseErrors map[string]error
}

func (p *pointReadCounter) MembersOf(ctx context.Context, tenant uint64, space, id string) (map[string]string, error) {
	if p.membersRead == nil {
		p.membersRead = map[string]int{}
	}
	p.membersRead[id]++
	if p.membersError != nil {
		return nil, p.membersError
	}
	return p.pointPlatform.MembersOf(ctx, tenant, space, id)
}

func (p *pointReadCounter) BundleOf(ctx context.Context, tenant uint64, space, id string) (release.Bundle, error) {
	if p.bundlesRead == nil {
		p.bundlesRead = map[string]int{}
	}
	p.bundlesRead[id]++
	return p.pointPlatform.BundleOf(ctx, tenant, space, id)
}

func (p *pointReadCounter) Head(ctx context.Context, tenant uint64, space string) (release.Head, error) {
	p.heads++
	return p.pointPlatform.Head(ctx, tenant, space)
}

func (p *pointReadCounter) ReleaseByID(ctx context.Context, tenant uint64, space, id string) (release.Release, error) {
	p.releasesRead[id]++
	if err := p.releaseErrors[id]; err != nil {
		return release.Release{}, err
	}
	return p.pointPlatform.ReleaseByID(ctx, tenant, space, id)
}

func TestPointReadCachesVersionsAndLatestReleaseUsesDecisionOrder(t *testing.T) {
	w := newPointWorld(t)
	for _, slug := range []string{"Q/waiting", "Q/grace"} {
		res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "ok", slug))
		require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	}
	// Equal decision timestamps use ID, independent of release contents/epoch.
	older := w.points.points[pointKey(w.cand.ID, "Q/waiting")]
	newer := w.points.points[pointKey(w.cand.ID, "Q/grace")]
	older.CreatedAt, older.ID = newer.CreatedAt, "point-z"
	newer.ID = "point-a"
	w.points.points[pointKey(w.cand.ID, "Q/waiting")] = older
	w.points.points[pointKey(w.cand.ID, "Q/grace")] = newer
	counter := &pointReadCounter{pointPlatform: w.points, releasesRead: map[string]int{}}
	w.releases = release.NewService(counter, nil, nil, release.WithPublisher(counter))
	detail := w.detail(t, w.cand.ID)
	require.Equal(t, older.ReleaseID, detail["release_id"])
	require.Equal(t, 1, counter.heads)
	require.Equal(t, map[string]int{w.points.head.ReleaseID: 1}, counter.releasesRead)
	counter.releasesRead = map[string]int{}
	counter.membersRead = map[string]int{}
	item := w.listed(t, "pending", w.cand.ID)
	require.Equal(t, older.ReleaseID, item["release_id"])
	require.Equal(t, 1, counter.membersRead[w.first.ID], "one shared base digest read per list")
	require.Empty(t, counter.releasesRead, "neither base nor point version payload is needed")
}

func TestPointQueueIncludesOldCandidateDecidedAfterTheHundredNewest(t *testing.T) {
	w := newPointWorld(t)
	for i := 0; i < 101; i++ {
		slug := fmt.Sprintf("R%d", i)
		c := w.submitWith(t, w.first.ID, nil, claimMember(t, slug, "waiting", "1日"))
		res := w.decidePoints(w.admin(), c.ID, pointsBody("reject", "no", slug+"/waiting"))
		require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	}
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("reject", "last",
		"P/waiting", "P/old", "Q/waiting", "Q/grace", "entity/P"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	items := w.items(t, "decided")
	require.Len(t, items, 100)
	require.Equal(t, w.cand.ID, items[0]["candidate_id"])
}

func TestPointWholeManualDecisionAndZeroPointCandidate(t *testing.T) {
	w := newPointWorld(t)
	_, err := w.releases.Decide(context.Background(), harnessKey, "demo", w.cand.ID,
		release.DecisionInput{Outcome: "manual", Mode: "machine", PolicyRef: "test"})
	require.NoError(t, err)
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("reject", "cannot bypass manual", "Q/waiting"))
	require.Equal(t, http.StatusConflict, res.Code, res.Body.String())
	require.Equal(t, release.ErrorCandidateDecided, code(t, res.Body.Bytes()))
	require.Empty(t, w.points.points)
	c := w.submitWith(t, w.first.ID, nil, claimMember(t, "P", "grace", "30日"))
	detail := w.detail(t, c.ID)
	require.EqualValues(t, 0, detail["point_count"])
	require.Equal(t, "pending", detail["status"])
	res = w.decide(w.admin(), c.ID, decision("approve", "whole no-op is still allowed"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
}

func TestPointRequestBoundaryAndMissingPortWriteNothing(t *testing.T) {
	w := newPointWorld(t)
	for _, raw := range []string{
		`{"slugs":[null],"outcome":"approve","reason":"ok"}`,
		`{"slugs":["Q/waiting"],"outcome":"approve","reason":null}`,
		`{"slugs":["Q/waiting"],"outcome":"approve","reason":"ok","\u0073lugs":["Q/grace"]}`,
		string(pointsBody("approve", "ok", "Q/waiting")) + strings.Repeat(" ", 64<<10),
	} {
		res := w.decidePoints(w.admin(), w.cand.ID, []byte(raw))
		require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
	}
	require.Empty(t, w.points.points)
	// Old publishers retain whole-candidate routes; the new write port fails closed.
	w.releases = release.NewService(w.platform, nil, nil, release.WithPublisher(w.platform))
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "ok", "Q/waiting"))
	require.Equal(t, http.StatusServiceUnavailable, res.Code, res.Body.String())
	require.Empty(t, w.points.points)
}

type pointLookupRace struct {
	*pointPlatform
	afterRead func()
}

func (p *pointLookupRace) PointDecisions(
	ctx context.Context, tenant uint64, space, id string,
) ([]release.PointDecision, error) {
	ds, err := p.pointPlatform.PointDecisions(ctx, tenant, space, id)
	if p.afterRead != nil {
		callback := p.afterRead
		p.afterRead = nil
		callback()
	}
	return ds, err
}

func TestPointBatchCommitsBetweenDecisionLookupAndHead(t *testing.T) {
	for _, advanceAgain := range []bool{false, true} {
		t.Run(fmt.Sprint(advanceAgain), func(t *testing.T) {
			w := newPointWorld(t)
			original := w.releases
			wrapper := &pointLookupRace{pointPlatform: w.points}
			var first release.PointResult
			wrapper.afterRead = func() {
				var err error
				first, err = original.ReviewPoints(context.Background(), harnessKey, "demo", w.cand.ID,
					[]string{"Q/waiting"}, "approve", "first")
				require.NoError(t, err)
				if advanceAgain {
					_, err = original.ReviewPoints(context.Background(), harnessKey, "demo", w.cand.ID,
						[]string{"Q/grace"}, "approve", "second batch")
					require.NoError(t, err)
				}
			}
			w.releases = release.NewService(w.points, nil, nil, release.WithPublisher(wrapper))
			res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "retry", "Q/waiting"))
			require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
			require.Equal(t, *first.ReleaseID, dataOf(t, res)["release_id"])
			count := 2
			if advanceAgain {
				count++
			}
			require.Len(t, w.points.releases, count)
			require.Len(t, w.points.points, count-1)
		})
	}
}

func TestPointBatchAcceptsFiveHundredPointsAndAtomicRemovalFailure(t *testing.T) {
	w := newPointWorld(t)
	members := make([]map[string]any, 0, 500)
	slugs := make([]string, 0, 500)
	for i := 0; i < 500; i++ {
		name := fmt.Sprintf("Many%d", i)
		members = append(members, claimMember(t, name, "value", "1"))
		slugs = append(slugs, name+"/value")
	}
	c := w.submitWith(t, w.first.ID, nil, members...)
	res := w.decidePoints(w.admin(), c.ID, pointsBody("approve", strings.Repeat("核", 2000), slugs...))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	require.Equal(t, "released", dataOf(t, res)["status"])
	require.Len(t, dataOf(t, res)["points"], 500)
	require.Len(t, w.points.points, 500)
	head := w.points.head
	invalid := w.submitWith(t, head.ReleaseID, []string{"absent"}, claimMember(t, "New", "value", "1"))
	res = w.decidePoints(w.admin(), invalid.ID, pointsBody("approve", "invalid removal", "absent", "New/value"))
	require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
	require.Equal(t, release.ErrorCandidateInvalid, code(t, res.Body.Bytes()))
	require.Equal(t, head, w.points.head)
	require.Len(t, w.points.points, 500, "invalid removal cannot leave the other approval written")
}
