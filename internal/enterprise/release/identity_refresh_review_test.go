// PV-4a acceptance (#510 R1): an identity refresh is decided only as a whole, by machine.
// Protected file: written by Claude.
//
// The production store is also a PointStore, whose per-point approvals publish a selected
// delta without the whole-bundle activation and its full-target check. A refresh is therefore
// not reviewable per point (approve or reject), nor by any human decision; its detail and each
// of its points name that blocker, and the machine whole-bundle path still checks the full
// target against the exact Head.
package release_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// machineDecisionOnly is the typed refusal (an HTTP 409 code) of a non-machine decision.
const machineDecisionOnly = "MACHINE_DECISION_ONLY"

// queuePlatform adds the queue store to the in-memory platform; pointPlatform adds the point
// store as well, like the production store. A batch release commits its point decisions; it is
// never the candidate's whole release.
type queuePlatform struct {
	*platform
	batches map[string]bool
}

type pointPlatform struct {
	*queuePlatform
	points []release.PointDecision
}

func newPointPlatform() *pointPlatform {
	return &pointPlatform{queuePlatform: &queuePlatform{platform: newPlatform(), batches: map[string]bool{}}}
}

func (p *pointPlatform) PointDecisions(_ context.Context, _ uint64, _, id string) ([]release.PointDecision, error) {
	var out []release.PointDecision
	for _, d := range p.points {
		if d.CandidateID == id {
			out = append(out, d)
		}
	}
	return out, nil
}

func (p *pointPlatform) RejectPoints(_ context.Context, decisions []release.PointDecision) error {
	for _, d := range decisions {
		d.ID = fmt.Sprintf("point-%d", len(p.points)+1)
		p.points = append(p.points, d)
	}
	return nil
}

func (p *pointPlatform) Activate(ctx context.Context, w release.ActivationWrite) (release.Release, error) {
	r, err := p.platform.Activate(ctx, w)
	if err != nil || len(w.Points) == 0 {
		return r, err
	}
	p.batches[r.ID] = true
	for _, d := range w.Points {
		d.ID, d.ReleaseID = fmt.Sprintf("point-%d", len(p.points)+1), r.ID
		p.points = append(p.points, d)
	}
	return r, nil
}

func (p *queuePlatform) Queue(_ context.Context, _ uint64, _, status string, _ int) ([]release.QueueEntry, error) {
	var out []release.QueueEntry
	for id, c := range p.candidates {
		entry := release.QueueEntry{Candidate: c}
		entry.Candidate.Status = "pending"
		for _, d := range p.decisions {
			if d.CandidateID == id {
				decided := d
				entry.Decision, entry.Candidate.Status = &decided, "rejected"
				if d.Outcome == "approve" {
					entry.Candidate.Status = "approved"
				}
			}
		}
		for rid, r := range p.releases {
			if r.CandidateID == id && !p.batches[rid] {
				entry.ReleaseID, entry.Candidate.Status = rid, "released"
			}
		}
		if (status == "pending") == (entry.Candidate.Status == "pending") {
			out = append(out, entry)
		}
	}
	return out, nil
}

func pointService(t *testing.T, p *pointPlatform) *release.Service {
	t.Helper()
	return release.NewService(p, fakeEvidence{allowed: map[string]bool{evidenceRef: true}}, realSchemas(t),
		release.WithPublisher(p), release.WithVersionedEntityTypes("product"))
}

func queueService(t *testing.T, p *queuePlatform) *release.Service {
	t.Helper()
	return release.NewService(p, fakeEvidence{allowed: map[string]bool{evidenceRef: true}}, realSchemas(t),
		release.WithPublisher(p), release.WithVersionedEntityTypes("product"))
}

func TestAnIdentityRefreshIsDecidedOnlyAsAWholeByMachine(t *testing.T) {
	ctx := context.Background()
	p := newPointPlatform()
	s := pointService(t, p)
	a := activeBase(t, s)
	renamed := entityPayload("P1", "product", map[string]any{"names": []any{"renamed"}})
	c, err := s.Receive(ctx, principal(), spaceID,
		vbundle(t, "identity_refresh", &a, nil, vm(t, "entity", "entity/P1", renamed)))
	require.NoError(t, err)

	for _, outcome := range []string{"approve", "reject"} {
		_, err = s.ReviewPoints(ctx, principal(), spaceID, c.ID, []string{"entity/P1"}, outcome, "looks fine")
		require.Equal(t, machineDecisionOnly, codeOf(t, err), "per point "+outcome)
		_, err = s.Review(ctx, principal(), spaceID, c.ID, outcome, "looks fine")
		require.Equal(t, machineDecisionOnly, codeOf(t, err), "whole human "+outcome)
	}
	_, err = s.Decide(ctx, principal(), spaceID, c.ID,
		release.DecisionInput{Outcome: "approve", Mode: "human", Reason: "looks fine"})
	require.Equal(t, machineDecisionOnly, codeOf(t, err))

	detail, err := s.ReviewCandidate(ctx, principal(), spaceID, c.ID)
	require.NoError(t, err)
	require.Equal(t, machineDecisionOnly, detail.Blocker)
	require.NotEmpty(t, detail.Points)
	for _, point := range detail.Points {
		require.Equal(t, machineDecisionOnly, point.Blocker, point.Slug)
	}
	require.Empty(t, p.points)
	require.Equal(t, a.ID, p.head.ReleaseID, "nothing activated")

	// The machine whole-bundle path checks the full target: the rename is refused there.
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
	// Nor may a human review re-trigger the approved machine decision.
	_, err = s.Review(ctx, principal(), spaceID, c.ID, "approve", "looks fine")
	require.Equal(t, machineDecisionOnly, codeOf(t, err))
	require.Equal(t, a.ID, p.head.ReleaseID)
}

// Without a point store the whole-candidate review applies the same refusal.
func TestAnIdentityRefreshIsNotReviewedByAHumanAsAWhole(t *testing.T) {
	ctx := context.Background()
	p := &queuePlatform{platform: newPlatform(), batches: map[string]bool{}}
	s := queueService(t, p)
	a := activeBase(t, s)
	c, err := s.Receive(ctx, principal(), spaceID, vbundle(t, "identity_refresh", &a, nil,
		vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil))))
	require.NoError(t, err)
	detail, err := s.ReviewCandidate(ctx, principal(), spaceID, c.ID)
	require.NoError(t, err)
	require.Equal(t, machineDecisionOnly, detail.Blocker)
	_, err = s.Review(ctx, principal(), spaceID, c.ID, "approve", "looks fine")
	require.Equal(t, machineDecisionOnly, codeOf(t, err))
	require.Equal(t, a.ID, p.head.ReleaseID)
}

func TestAStaleIdentityRefreshIsNotPublishedPerPoint(t *testing.T) {
	ctx := context.Background()
	p := newPointPlatform()
	s := pointService(t, p)
	a := activeBase(t, s)
	c, err := s.Receive(ctx, principal(), spaceID, vbundle(t, "identity_refresh", &a, nil,
		vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil))))
	require.NoError(t, err)
	moved := publish(t, s, vbundle(t, "compile", &a, nil, vm(t, "claim", "Q1/f1", claimPayload("Q1", "f1", nil, nil))))

	_, err = s.ReviewPoints(ctx, principal(), spaceID, c.ID, []string{"P1/f1"}, "approve", "looks fine")
	require.Equal(t, machineDecisionOnly, codeOf(t, err))
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.Equal(t, release.ErrorNeedsRebase, codeOf(t, err))
	require.Equal(t, moved.ID, p.head.ReleaseID)
}

// Control: the same fake publishes a compile candidate's point, so the refusals above come
// from the refresh rule and not from the fake.
func TestThePointFakePublishesACompilePoint(t *testing.T) {
	ctx := context.Background()
	p := newPointPlatform()
	s := pointService(t, p)
	a := activeBase(t, s)
	c, err := s.Receive(ctx, principal(), spaceID, vbundle(t, "compile", &a, nil,
		vm(t, "claim", "P1/f1", claimPayload("P1", "f1", nil, map[string]any{"unit": "day"}))))
	require.NoError(t, err)
	result, err := s.ReviewPoints(ctx, principal(), spaceID, c.ID, []string{"P1/f1"}, "approve", "looks fine")
	require.NoError(t, err)
	require.Equal(t, "released", result.Status)
	require.NotEqual(t, a.ID, p.head.ReleaseID)
}
