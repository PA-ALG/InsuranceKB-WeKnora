package enterprise_test

// RV6b acceptance (protected, written by Claude): administrators approve or reject each review
// point of a candidate on its own; an approval publishes only those points plus the new members
// they need (Spec docs/design/slices/RV6b-逐字段审核平台.md §2–§5). The platform is in memory
// (session_points_world_test.go); the store's transactional point writes are proven in
// releasestore/point_decisions_postgres_test.go.

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestReviewPointsAreTheCandidatesChangesAgainstItsBase(t *testing.T) {
	w := newPointWorld(t)
	points := pointsOf(t, w.detail(t, w.cand.ID))
	kinds := map[string]any{}
	for slug, point := range points {
		kinds[slug] = point["kind"]
		require.Equal(t, "pending", point["status"], slug)
		require.Nil(t, point["decision"], slug)
		require.Nil(t, point["release_id"], slug)
		require.Equal(t, "", point["blocker"], slug)
	}
	require.Equal(t, map[string]any{
		"P/old": "removal", "P/waiting": "claim", "Q/grace": "claim", "Q/waiting": "claim", "entity/P": "member",
	}, kinds, "an unchanged member and new non-claim members are not review points")

	item := w.listed(t, "pending", w.cand.ID)
	require.NotNil(t, item)
	require.EqualValues(t, 5, item["point_count"])
	require.EqualValues(t, 5, item["pending_points"])
}

func TestApprovingOnePointPublishesOnlyItAndTheNewMembersItNeeds(t *testing.T) {
	w := newPointWorld(t)
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "  等待期核对无误  ", "Q/waiting"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	data := dataOf(t, res)
	require.Equal(t, "pending", data["status"], "four points still wait")
	require.Equal(t, w.points.head.ReleaseID, data["release_id"])
	require.EqualValues(t, 2, data["epoch"])
	require.Equal(t, []any{map[string]any{"slug": "Q/waiting", "status": "released"}}, data["points"])

	live := w.active(t)
	require.Equal(t, "60日", live["Q/waiting"]["value"])
	require.Contains(t, live, "entity/Q", "the new product's entity goes live with its first point")
	require.Contains(t, live, "presentation/Q")
	require.NotContains(t, live, "Q/grace", "an undecided point stays out")
	require.Equal(t, "90日", live["P/waiting"]["value"])
	require.Contains(t, live, "P/old")
	require.Equal(t, "产品P", live["entity/P"]["name"])

	points := pointsOf(t, w.detail(t, w.cand.ID))
	approved := points["Q/waiting"]
	require.Equal(t, "released", approved["status"])
	require.Equal(t, data["release_id"], approved["release_id"])
	verdict := approved["decision"].(map[string]any)
	require.Equal(t, "approve", verdict["outcome"])
	require.Equal(t, "等待期核对无误", verdict["reason"])
	require.Equal(t, browser.principal.StorageID(), verdict["subject"])
	require.Equal(t, "pending", points["Q/grace"]["status"])

	item := w.listed(t, "pending", w.cand.ID)
	require.NotNil(t, item, "the candidate stays in the queue")
	require.EqualValues(t, 4, item["pending_points"])
	require.Equal(t, data["release_id"], item["release_id"])

	// The second approval sees entity/Q already live and unchanged: no NEEDS_REBASE.
	entity := live["entity/Q"]["_digest"]
	again := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "宽限期无误", "Q/grace"))
	require.Equal(t, http.StatusCreated, again.Code, again.Body.String())
	require.EqualValues(t, 3, dataOf(t, again)["epoch"])
	live = w.active(t)
	require.Equal(t, "15日", live["Q/grace"]["value"])
	require.Equal(t, "60日", live["Q/waiting"]["value"])
	require.Equal(t, entity, live["entity/Q"]["_digest"])
}

func TestRejectingAPointPublishesNothingAndEachPointIsDecidedOnce(t *testing.T) {
	w := newPointWorld(t)
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("reject", "取值与条款不符", "P/waiting"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	data := dataOf(t, res)
	require.Equal(t, "pending", data["status"])
	require.Nil(t, data["release_id"])
	require.Nil(t, data["epoch"])
	require.Equal(t, []any{map[string]any{"slug": "P/waiting", "status": "rejected"}}, data["points"])
	require.Equal(t, w.first.ID, w.points.head.ReleaseID, "a rejection publishes nothing")
	require.Equal(t, "rejected", pointsOf(t, w.detail(t, w.cand.ID))["P/waiting"]["status"])

	for _, outcome := range []string{"approve", "reject"} {
		again := w.decidePoints(w.admin(), w.cand.ID, pointsBody(outcome, "再看一次", "P/waiting"))
		require.Equal(t, http.StatusConflict, again.Code, again.Body.String())
		require.Equal(t, release.ErrorMemberDecided, code(t, again.Body.Bytes()))
	}
	mixed := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "一起批准", "Q/waiting", "P/waiting"))
	require.Equal(t, http.StatusConflict, mixed.Code, mixed.Body.String())
	require.Equal(t, release.ErrorMemberDecided, code(t, mixed.Body.Bytes()))
	require.Len(t, w.points.points, 1, "a refused batch writes none of its points")
	require.Equal(t, w.first.ID, w.points.head.ReleaseID)
}

func TestPointRequestsAreStrictAndWriteNothing(t *testing.T) {
	w := newPointWorld(t)
	many := make([]string, 501)
	for i := range many {
		many[i] = fmt.Sprintf("X/%d", i)
	}
	manyRaw, _ := json.Marshal(many)
	for name, body := range map[string]string{
		"unchanged member":   string(pointsBody("approve", "ok", "P/grace")),
		"new non-claim":      string(pointsBody("approve", "ok", "entity/Q")),
		"unknown slug":       string(pointsBody("approve", "ok", "Z/none")),
		"duplicate slug":     string(pointsBody("approve", "ok", "Q/waiting", "Q/waiting")),
		"empty slugs":        `{"slugs":[],"outcome":"approve","reason":"ok"}`,
		"missing slugs":      `{"outcome":"approve","reason":"ok"}`,
		"slug not a string":  `{"slugs":[1],"outcome":"approve","reason":"ok"}`,
		"too many slugs":     fmt.Sprintf(`{"slugs":%s,"outcome":"reject","reason":"ok"}`, manyRaw),
		"unknown key":        `{"slugs":["Q/waiting"],"outcome":"approve","reason":"ok","mode":"machine"}`,
		"duplicate key":      `{"slugs":["Q/waiting"],"outcome":"approve","outcome":"reject","reason":"ok"}`,
		"manual outcome":     `{"slugs":["Q/waiting"],"outcome":"manual","reason":"ok"}`,
		"blank reason":       `{"slugs":["Q/waiting"],"outcome":"reject","reason":"   "}`,
		"long reason":        fmt.Sprintf(`{"slugs":["Q/waiting"],"outcome":"reject","reason":%q}`, strings.Repeat("长", 2001)),
		"not an object":      `[["Q/waiting"],"approve"]`,
		"valid then unknown": string(pointsBody("reject", "ok", "Q/waiting", "Z/none")),
	} {
		t.Run(name, func(t *testing.T) {
			res := w.decidePoints(w.admin(), w.cand.ID, []byte(body))
			require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
			require.Equal(t, release.ErrorDecisionInvalid, code(t, res.Body.Bytes()))
		})
	}
	missing := w.decidePoints(w.admin(), "cand_unknown", pointsBody("approve", "ok", "Q/waiting"))
	require.Equal(t, http.StatusNotFound, missing.Code)
	require.Equal(t, release.ErrorCandidateNotFound, code(t, missing.Body.Bytes()))
	require.Empty(t, w.points.points)
	require.Equal(t, w.first.ID, w.points.head.ReleaseID)
}

func TestDecidingEveryPointMovesTheCandidateToDecided(t *testing.T) {
	w := newPointWorld(t)
	require.Equal(t, http.StatusCreated,
		w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "ok", "Q/waiting")).Code)
	require.Equal(t, http.StatusCreated,
		w.decidePoints(w.admin(), w.cand.ID, pointsBody("reject", "不对", "P/waiting")).Code)
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "其余无误", "entity/P", "P/old", "Q/grace"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	data := dataOf(t, res)
	require.Equal(t, "released", data["status"])
	require.Equal(t, w.points.head.ReleaseID, data["release_id"])
	require.Len(t, data["points"], 3)

	live := w.active(t)
	require.NotContains(t, live, "P/old", "an approved removal goes live")
	require.Equal(t, "产品P（新）", live["entity/P"]["name"])
	require.Equal(t, "15日", live["Q/grace"]["value"])
	require.Equal(t, "90日", live["P/waiting"]["value"], "the rejected point never goes live")

	require.Nil(t, w.listed(t, "pending", w.cand.ID))
	decided := w.items(t, "decided")
	require.Equal(t, w.cand.ID, decided[0]["candidate_id"], "newest decision first")
	require.Equal(t, "released", decided[0]["status"])
	require.Equal(t, w.points.head.ReleaseID, decided[0]["release_id"])
	require.EqualValues(t, 5, decided[0]["point_count"])
	require.EqualValues(t, 0, decided[0]["pending_points"])
	for slug, point := range pointsOf(t, w.detail(t, w.cand.ID)) {
		require.NotEqual(t, "pending", point["status"], slug)
		require.Equal(t, "", point["blocker"], slug)
	}
}

func TestRejectingEveryPointRejectsTheCandidate(t *testing.T) {
	w := newPointWorld(t)
	res := w.decidePoints(w.admin(), w.cand.ID,
		pointsBody("reject", "整体不对", "P/old", "P/waiting", "Q/grace", "Q/waiting", "entity/P"))
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	require.Equal(t, "rejected", dataOf(t, res)["status"])
	require.Equal(t, w.first.ID, w.points.head.ReleaseID)
	item := w.listed(t, "decided", w.cand.ID)
	require.NotNil(t, item)
	require.Equal(t, "rejected", item["status"])
	require.Nil(t, item["release_id"])
}

func TestAPointTheHeadChangedIsBlockedAndRecordsNothing(t *testing.T) {
	w := newPointWorld(t)
	w.machine(t, w.submitWith(t, w.first.ID, nil, claimMember(t, "P", "waiting", "120日")))

	points := pointsOf(t, w.detail(t, w.cand.ID))
	require.Equal(t, release.ErrorNeedsRebase, points["P/waiting"]["blocker"])
	require.Equal(t, "", points["Q/waiting"]["blocker"], "the Head did not touch Q")

	head := w.points.head
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "ok", "P/waiting"))
	require.Equal(t, http.StatusConflict, res.Code, res.Body.String())
	require.Equal(t, release.ErrorNeedsRebase, code(t, res.Body.Bytes()))
	require.Empty(t, w.points.points, "a failed precheck records nothing")
	require.Equal(t, head, w.points.head)

	require.Equal(t, http.StatusCreated,
		w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "ok", "Q/waiting")).Code)
	require.Equal(t, "120日", w.active(t)["P/waiting"]["value"], "the newer Head value is kept")
	require.Equal(t, http.StatusCreated,
		w.decidePoints(w.admin(), w.cand.ID, pointsBody("reject", "已过期", "P/waiting")).Code,
		"a blocked point can still be rejected")
}

func TestANewMemberTheHeadHoldsDifferentlyBlocksTheApproval(t *testing.T) {
	w := newPointWorld(t)
	w.machine(t, w.submitWith(t, w.first.ID, nil,
		plainMember(t, "entity", "entity/Q", map[string]any{"name": "别的Q"})))

	require.Equal(t, release.ErrorNeedsRebase, pointsOf(t, w.detail(t, w.cand.ID))["Q/waiting"]["blocker"])
	res := w.decidePoints(w.admin(), w.cand.ID, pointsBody("approve", "ok", "Q/waiting"))
	require.Equal(t, http.StatusConflict, res.Code, res.Body.String())
	require.Equal(t, release.ErrorNeedsRebase, code(t, res.Body.Bytes()))
	require.Empty(t, w.points.points)
	require.Equal(t, "别的Q", w.active(t)["entity/Q"]["name"])
}

func TestPointDecisionsAndWholeCandidateDecisionsExcludeEachOther(t *testing.T) {
	w := newPointWorld(t)
	require.Equal(t, http.StatusCreated,
		w.decidePoints(w.admin(), w.cand.ID, pointsBody("reject", "不对", "P/waiting")).Code)
	for _, outcome := range []string{"approve", "reject"} {
		res := w.decide(w.admin(), w.cand.ID, decision(outcome, "整份处理"))
		require.Equal(t, http.StatusConflict, res.Code, res.Body.String())
		require.Equal(t, release.ErrorCandidateDecided, code(t, res.Body.Bytes()))
	}
	_, err := w.releases.Decide(context.Background(), harnessKey, "demo", w.cand.ID, release.DecisionInput{
		Outcome: "approve", Mode: "machine", PolicyRef: "review-policy@2",
	})
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorCandidateDecided, failure.Code)
	require.Len(t, w.points.decisions, 1, "only the seed's machine decision exists")

	// The other way round: a whole-candidate decision closes the point route.
	other := w.submitWith(t, w.first.ID, nil, claimMember(t, "R", "waiting", "30日"))
	require.Equal(t, http.StatusCreated, w.decide(w.admin(), other.ID, decision("reject", "整份拒绝")).Code)
	res := w.decidePoints(w.admin(), other.ID, pointsBody("approve", "ok", "R/waiting"))
	require.Equal(t, http.StatusConflict, res.Code, res.Body.String())
	require.Equal(t, release.ErrorCandidateDecided, code(t, res.Body.Bytes()))
	point := pointsOf(t, w.detail(t, other.ID))["R/waiting"]
	require.Equal(t, "rejected", point["status"], "points follow a whole-candidate decision")
	require.Len(t, w.points.points, 1)
}

func TestPointRoutesNeedAnAdministratorBrowserSessionInTheirSpace(t *testing.T) {
	w := newPointWorld(t)
	denied, missing := release.ErrorReleaseAccessDenied, release.ErrorReleaseNotFound
	serviceKey := identity{tenant: 7, principal: browser.principal, apiKey: true}
	otherTenant := identity{tenant: 8, principal: browser.principal}
	for name, probe := range map[string]struct {
		who    identity
		role   types.TenantRole
		space  string
		status int
		code   string
	}{
		"contributor role": {browser, types.TenantRoleContributor, "demo", http.StatusForbidden, denied},
		"service key":      {serviceKey, types.TenantRoleOwner, "demo", http.StatusForbidden, denied},
		"unknown Space":    {browser, types.TenantRoleAdmin, "nope", http.StatusNotFound, missing},
		"another tenant":   {browser, types.TenantRoleAdmin, "other", http.StatusNotFound, missing},
		"tenant 8 caller":  {otherTenant, types.TenantRoleOwner, "demo", http.StatusNotFound, missing},
	} {
		t.Run(name, func(t *testing.T) {
			path := strings.Replace(reviewsPath, "/demo/", "/"+probe.space+"/", 1)
			res := call(w.router(probe.who, probe.role), http.MethodPost,
				path+"/"+w.cand.ID+"/points/decisions", pointsBody("approve", "ok", "Q/waiting"))
			require.Equal(t, probe.status, res.Code, res.Body.String())
			require.Equal(t, probe.code, code(t, res.Body.Bytes()))
		})
	}
	require.Empty(t, w.points.points)
	require.Equal(t, w.first.ID, w.points.head.ReleaseID)
}
