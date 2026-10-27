package enterprise_test

// RV6b acceptance fixtures (protected, written by Claude): the in-memory point platform and the
// world the tests in session_points_test.go review (Spec docs/design/slices/RV6b-逐字段审核平台.md).

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"sort"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// pointPlatform adds point decisions to the RV5a review platform. As in PostgreSQL, a candidate
// counts as released as a whole only by a release whose digest is its bundle digest: point
// releases carry their batch digest. One release per digest; approvals are written by Activate.
type pointPlatform struct {
	*reviewPlatform
	digests map[string]string                // release id -> ActivationWrite.BundleDigest
	points  map[string]release.PointDecision // candidate + "\x00" + slug
}

func pointKey(candidate, slug string) string { return candidate + "\x00" + slug }

func (p *pointPlatform) PointDecisions(
	_ context.Context, tenantID uint64, spaceID, candidateID string,
) ([]release.PointDecision, error) {
	var out []release.PointDecision
	for _, d := range p.points {
		if d.TenantID == tenantID && d.SpaceID == spaceID && d.CandidateID == candidateID {
			out = append(out, d)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Slug < out[j].Slug })
	return out, nil
}

func (p *pointPlatform) RejectPoints(_ context.Context, decisions []release.PointDecision) error {
	if err := p.undecided(decisions); err != nil {
		return err
	}
	for _, d := range decisions {
		p.save(d, "")
	}
	return nil
}

func (p *pointPlatform) undecided(decisions []release.PointDecision) error {
	for _, d := range decisions {
		if _, ok := p.points[pointKey(d.CandidateID, d.Slug)]; ok {
			return &release.Error{Code: release.ErrorMemberDecided, Detail: d.Slug}
		}
	}
	return nil
}

func (p *pointPlatform) save(d release.PointDecision, releaseID string) {
	d.ID, d.CreatedAt, d.ReleaseID = fmt.Sprintf("point-%d", len(p.points)+1), p.tick(), releaseID
	p.points[pointKey(d.CandidateID, d.Slug)] = d
}

func (p *pointPlatform) Activate(ctx context.Context, w release.ActivationWrite) (release.Release, error) {
	for id, digest := range p.digests {
		if digest == w.BundleDigest {
			return p.releases[id], nil
		}
	}
	if err := p.undecided(w.Points); err != nil {
		return release.Release{}, err
	}
	r, err := p.reviewPlatform.Activate(ctx, w)
	if err != nil {
		return r, err
	}
	p.digests[r.ID] = w.BundleDigest
	for _, d := range w.Points {
		p.save(d, r.ID)
	}
	return r, nil
}

func (p *pointPlatform) Queue(
	_ context.Context, tenantID uint64, spaceID, status string, limit int,
) ([]release.QueueEntry, error) {
	var out []release.QueueEntry
	for _, id := range p.order {
		c := p.candidates[id]
		if c.TenantID != tenantID || c.SpaceID != spaceID {
			continue
		}
		e := release.QueueEntry{Candidate: c, CreatedAt: p.created[id], CreatedBy: "svc-harness"}
		e.Candidate.Status = "pending"
		if ids := p.history[id]; len(ids) > 0 {
			d := p.decisions[ids[len(ids)-1]]
			e.Decision = &d
			e.Candidate.Status = map[string]string{"approve": "approved", "reject": "rejected"}[d.Outcome]
		}
		for rid, digest := range p.digests {
			if digest == c.BundleDigest {
				e.Candidate.Status, e.ReleaseID = "released", rid
			}
		}
		if (status == "pending") == (e.Candidate.Status == "pending") {
			out = append(out, e)
		}
	}
	if status == "decided" {
		for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
			out[i], out[j] = out[j], out[i]
		}
		if len(out) > limit {
			out = out[:limit]
		}
	}
	return out, nil
}

type pointWorld struct {
	*reviewWorld
	points *pointPlatform
	cand   release.Candidate
}

var harnessKey = release.Principal{TenantID: 7, Subject: "svc-harness"}

// plainMember is a non-claim member: the platform only knows kind "claim".
func plainMember(t *testing.T, kind, slug string, payload map[string]any) map[string]any {
	t.Helper()
	canonical, err := json.Marshal(payload)
	require.NoError(t, err)
	return map[string]any{
		"kind": kind, "logical_slug": slug, "payload": payload, "member_digest": digestOf(canonical),
		"access_scope": "space",
	}
}

func (w *pointWorld) submitWith(
	t *testing.T, base string, removals []string, members ...map[string]any,
) release.Candidate {
	t.Helper()
	doc := map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test", "members": members,
	}
	if base != "" {
		doc["base_release_id"] = base
	}
	if len(removals) > 0 {
		doc["removals"] = removals
	}
	raw, err := json.Marshal(doc)
	require.NoError(t, err)
	c, err := w.releases.Receive(context.Background(), harnessKey, "demo", raw)
	require.NoError(t, err)
	return c
}

// machine publishes a candidate as a whole, as the machine route does.
func (w *pointWorld) machine(t *testing.T, c release.Candidate) release.Release {
	t.Helper()
	ctx := context.Background()
	d, err := w.releases.Decide(ctx, harnessKey, "demo", c.ID, release.DecisionInput{
		Outcome: "approve", Mode: "machine", PolicyRef: "review-policy@2",
	})
	require.NoError(t, err)
	r, err := w.releases.Activate(ctx, harnessKey, "demo", c.ID, d.ID)
	require.NoError(t, err)
	return r
}

// newPointWorld seeds P (waiting 90日, grace 30日, old, entity/P), then submits one candidate on
// it that changes P/waiting, repeats P/grace unchanged, adds Q's two fields with Q's new entity
// and page, changes entity/P and removes P/old.
func newPointWorld(t *testing.T) *pointWorld {
	t.Helper()
	schemas := map[string][]byte{}
	for _, name := range []string{"candidate_bundle", "evidence", "locator"} {
		raw, err := os.ReadFile("../../contracts/" + name + ".schema.json")
		require.NoError(t, err)
		schemas[name] = raw
	}
	platform := &pointPlatform{
		reviewPlatform: &reviewPlatform{
			expertPlatform: expertPlatform{
				candidates: map[string]release.Candidate{}, bundles: map[string]release.Bundle{},
				decisions: map[string]release.Decision{}, releases: map[string]release.Release{},
			},
			created: map[string]time.Time{}, history: map[string][]string{},
			clock: time.Date(2026, 10, 27, 8, 0, 0, 0, time.UTC),
		},
		digests: map[string]string{}, points: map[string]release.PointDecision{},
	}
	records := expertRecords{}
	w := &pointWorld{reviewWorld: &reviewWorld{platform: platform.reviewPlatform}, points: platform}
	w.releases = release.NewService(platform, expert.NewResolver(records, pdfSources{}), schemas,
		release.WithPublisher(platform), release.WithEvidenceVerifier(expert.NewVerifier(records, pdfSources{})))
	seed := w.submitWith(t, "", nil,
		claimMember(t, "P", "waiting", "90日"), claimMember(t, "P", "grace", "30日"),
		claimMember(t, "P", "old", "旧条款"), plainMember(t, "entity", "entity/P", map[string]any{"name": "产品P"}))
	w.first = w.machine(t, seed)
	w.cand = w.submitWith(t, w.first.ID, []string{"P/old"},
		claimMember(t, "P", "waiting", "180日"),
		claimMember(t, "P", "grace", "30日"),
		claimMember(t, "Q", "waiting", "60日"),
		claimMember(t, "Q", "grace", "15日"),
		plainMember(t, "entity", "entity/Q", map[string]any{"name": "产品Q"}),
		plainMember(t, "presentation_profile", "presentation/Q", map[string]any{"layout": "basic"}),
		plainMember(t, "entity", "entity/P", map[string]any{"name": "产品P（新）"}),
	)
	return w
}

func pointsBody(outcome, reason string, slugs ...string) []byte {
	raw, _ := json.Marshal(map[string]any{"slugs": slugs, "outcome": outcome, "reason": reason})
	return raw
}

func (w *pointWorld) decidePoints(r http.Handler, id string, body []byte) *httptest.ResponseRecorder {
	return call(r, http.MethodPost, reviewsPath+"/"+id+"/points/decisions", body)
}

func (w *pointWorld) detail(t *testing.T, id string) map[string]any {
	t.Helper()
	res := call(w.admin(), http.MethodGet, reviewsPath+"/"+id, nil)
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	return dataOf(t, res)
}

func pointsOf(t *testing.T, detail map[string]any) map[string]map[string]any {
	t.Helper()
	out := map[string]map[string]any{}
	var order []string
	for _, item := range detail["points"].([]any) {
		point := item.(map[string]any)
		slug := point["slug"].(string)
		out[slug] = point
		order = append(order, slug)
	}
	require.True(t, sort.StringsAreSorted(order), "points are ordered by slug: %v", order)
	return out
}

// active reads the Head release's members by slug.
func (w *pointWorld) active(t *testing.T) map[string]map[string]any {
	t.Helper()
	out := map[string]map[string]any{}
	for _, m := range w.points.releases[w.points.head.ReleaseID].Members {
		var payload map[string]any
		require.NoError(t, json.Unmarshal(m.Payload, &payload))
		payload["_digest"] = m.MemberDigest
		out[m.LogicalSlug] = payload
	}
	return out
}

func (w *pointWorld) listed(t *testing.T, status, id string) map[string]any {
	t.Helper()
	for _, item := range w.items(t, status) {
		if item["candidate_id"] == id {
			return item
		}
	}
	return nil
}
