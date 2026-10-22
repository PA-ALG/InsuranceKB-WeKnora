// S4c-2a acceptance: decide, activate and read releases through the Space's single
// Head (Spec §3.1). Protected file: written by Claude.
//
// Uses only the package's exported surface and an in-memory platform that implements
// both Store and Publisher, with the S3b helpers of this test package (member,
// schemas, fakeEvidence, principal, codeOf, spaceID). RED until S4c-2a implements it.
package release_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// ---- in-memory platform: one Head per Space, CAS on activation ---------------------------

type platform struct {
	candidates  map[string]release.Candidate
	bundles     map[string]release.Bundle
	byDigest    map[string]string
	decisions   map[string]release.Decision
	decisionIDs map[string]string // digest -> id
	releases    map[string]release.Release
	nonces      map[string]string // nonce -> release id
	head        release.Head
	activations int
	// racer, when set, activates first: the Head moves between the service's read and write.
	racer *release.Head
}

func newPlatform() *platform {
	return &platform{
		candidates: map[string]release.Candidate{}, bundles: map[string]release.Bundle{},
		byDigest: map[string]string{}, decisions: map[string]release.Decision{},
		decisionIDs: map[string]string{}, releases: map[string]release.Release{},
		nonces: map[string]string{},
	}
}

func (p *platform) CreateCandidate(
	_ context.Context, c release.Candidate, b release.Bundle,
) (release.Candidate, error) {
	if id, ok := p.byDigest[c.BundleDigest]; ok {
		existing := p.candidates[id]
		existing.Status = "existing"
		return existing, nil
	}
	c.ID = fmt.Sprintf("candidate-%d", len(p.candidates)+1)
	c.Status = "created"
	p.candidates[c.ID], p.bundles[c.ID], p.byDigest[c.BundleDigest] = c, b, c.ID
	return c, nil
}

func (p *platform) CandidateByID(_ context.Context, _ uint64, _, id string) (release.Candidate, error) {
	c, ok := p.candidates[id]
	if !ok {
		return release.Candidate{}, &release.Error{Code: release.ErrorCandidateNotFound, Detail: id}
	}
	return c, nil
}

func (p *platform) BundleOf(_ context.Context, _ uint64, _, id string) (release.Bundle, error) {
	return p.bundles[id], nil
}

func (p *platform) Head(context.Context, uint64, string) (release.Head, error) { return p.head, nil }

func (p *platform) MembersOf(_ context.Context, _ uint64, _, releaseID string) (map[string]string, error) {
	out := map[string]string{}
	for _, m := range p.releases[releaseID].Members {
		out[m.LogicalSlug] = m.MemberDigest
	}
	return out, nil
}

func (p *platform) SaveDecision(_ context.Context, d release.Decision) (release.Decision, error) {
	if id, ok := p.decisionIDs[d.Digest]; ok {
		return p.decisions[id], nil
	}
	d.ID = fmt.Sprintf("decision-%d", len(p.decisions)+1)
	p.decisions[d.ID], p.decisionIDs[d.Digest] = d, d.ID
	return d, nil
}

func (p *platform) DecisionByID(_ context.Context, _ uint64, _, id string) (release.Decision, error) {
	d, ok := p.decisions[id]
	if !ok {
		return release.Decision{}, &release.Error{Code: release.ErrorDecisionNotFound, Detail: id}
	}
	return d, nil
}

func (p *platform) ReleaseByID(_ context.Context, _ uint64, _, id string) (release.Release, error) {
	if id == "" {
		id = p.head.ReleaseID
	}
	r, ok := p.releases[id]
	if !ok {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound, Detail: id}
	}
	return r, nil
}

func (p *platform) Activate(_ context.Context, w release.ActivationWrite) (release.Release, error) {
	if id, ok := p.nonces[w.Nonce]; ok {
		return p.releases[id], nil
	}
	if p.racer != nil {
		p.head, p.racer = *p.racer, nil
	}
	if w.Expected != p.head {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseConflict, Detail: "head moved"}
	}
	p.activations++
	r := release.Release{
		ID: fmt.Sprintf("release-%d", p.activations), Epoch: p.head.Epoch + 1,
		BaseReleaseID: w.Expected.ReleaseID, CandidateID: w.CandidateID,
		DecisionDigest: w.DecisionDigest, Members: w.Members,
	}
	p.releases[r.ID], p.nonces[w.Nonce] = r, r.ID
	p.head = release.Head{ReleaseID: r.ID, Epoch: r.Epoch}
	return r, nil
}

// ---- helpers ------------------------------------------------------------------------------

func publishing(p *platform, refs ...string) *release.Service {
	allowed := map[string]bool{}
	for _, ref := range refs {
		allowed[ref] = true
	}
	return release.NewService(p, fakeEvidence{allowed: allowed}, schemas(), release.WithPublisher(p))
}

func candidateBundle(t *testing.T, base string, removals []string, members ...map[string]any) []byte {
	t.Helper()
	doc := map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
		"members": members,
	}
	if base != "" {
		doc["base_release_id"] = base
	}
	if len(removals) > 0 {
		doc["removals"] = removals
	}
	raw, err := json.Marshal(doc)
	require.NoError(t, err)
	return raw
}

var approve = release.DecisionInput{Outcome: "approve", Mode: "machine", PolicyRef: "gate-2026-10-15", Score: "0.97"}

// publish receives, approves and activates one bundle.
func publish(t *testing.T, s *release.Service, raw []byte) release.Release {
	t.Helper()
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, raw)
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	r, err := s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.NoError(t, err)
	return r
}

func slugs(r release.Release) []string {
	out := make([]string, 0, len(r.Members))
	for _, m := range r.Members {
		out = append(out, m.LogicalSlug)
	}
	return out
}

func memberBySlug(r release.Release, slug string) release.Member {
	for _, m := range r.Members {
		if m.LogicalSlug == slug {
			return m
		}
	}
	return release.Member{}
}

// ---- tests --------------------------------------------------------------------------------

func TestFirstActivationPublishesTheApprovedCandidate(t *testing.T) {
	p := newPlatform()
	s := publishing(p, "source:v1:k-1:1:abc")
	r := publish(t, s, candidateBundle(t, "", nil,
		member(t, "1814/waiting_period", map[string]any{"value": "90日"}, "source:v1:k-1:1:abc"),
		member(t, "1814/coverage_period", map[string]any{"value": "一年"})))

	require.Equal(t, uint64(1), r.Epoch)
	require.Empty(t, r.BaseReleaseID)
	require.Equal(t, []string{"1814/coverage_period", "1814/waiting_period"}, slugs(r), "members sorted by slug")
	waiting := memberBySlug(r, "1814/waiting_period")
	require.JSONEq(t, `{"value":"90日"}`, string(waiting.Payload))
	require.Equal(t, []string{"source:v1:k-1:1:abc"}, waiting.EvidenceRefs)
	require.Equal(t, digest(t, map[string]any{"value": "90日"}), waiting.MemberDigest)
	require.NotEmpty(t, r.DecisionDigest)

	active, err := s.Release(context.Background(), principal(), spaceID, "")
	require.NoError(t, err)
	require.Equal(t, r.ID, active.ID)
}

func TestActivationAppliesTheDeltaOnTopOfTheCurrentHead(t *testing.T) {
	p := newPlatform()
	s := publishing(p, "source:v1:k-1:1:abc")
	first := publish(t, s, candidateBundle(t, "", nil,
		member(t, "a", map[string]any{"v": 1}),
		member(t, "b", map[string]any{"v": 2}),
		member(t, "c", map[string]any{"v": 3}, "source:v1:k-1:1:abc")))

	second := publish(t, s, candidateBundle(t, first.ID, []string{"a"},
		member(t, "b", map[string]any{"v": 20}),
		member(t, "d", map[string]any{"v": 4})))

	require.Equal(t, first.ID, second.BaseReleaseID)
	require.Equal(t, uint64(2), second.Epoch)
	require.Equal(t, []string{"b", "c", "d"}, slugs(second))
	require.JSONEq(t, `{"v":20}`, string(memberBySlug(second, "b").Payload))
	carried := memberBySlug(second, "c")
	require.JSONEq(t, `{"v":3}`, string(carried.Payload), "untouched members carry over unchanged")
	require.Equal(t, []string{"source:v1:k-1:1:abc"}, carried.EvidenceRefs)
}

func TestAStaleBaseNeedsRebaseAndWritesNothing(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	first := publish(t, s, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	ctx := context.Background()

	// S8b: a candidate prepared before the first release is now rebased when the Head did not
	// touch its slugs (rebase_acceptance_test.go); an unknown base still needs a rebase.
	for _, raw := range [][]byte{
		candidateBundle(t, "release-old", nil, member(t, "b", map[string]any{"v": 2})), // another base
	} {
		c, err := s.Receive(ctx, principal(), spaceID, raw)
		require.NoError(t, err)
		d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
		require.NoError(t, err)
		_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
		require.Equal(t, release.ErrorNeedsRebase, codeOf(t, err))
	}
	require.Equal(t, 1, p.activations)
	require.Equal(t, first.ID, p.head.ReleaseID)
}

func TestABaseEpochThatNoLongerMatchesNeedsRebase(t *testing.T) {
	p := newPlatform()
	first := publish(t, publishing(p), candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	// The real contract carries base_epoch; the S3b test schema does not.
	s := release.NewService(p, fakeEvidence{allowed: map[string]bool{}}, contractSchemas(t), release.WithPublisher(p))
	entry := member(t, "b", map[string]any{"v": 2})
	entry["access_scope"] = "space"
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
		"base_release_id": first.ID, "base_epoch": 7, "members": []any{entry},
	})
	require.NoError(t, err)
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, raw)
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.Equal(t, release.ErrorNeedsRebase, codeOf(t, err))
	require.Equal(t, 1, p.activations)
}

func TestOnlyAnApprovedDecisionOfThisCandidateCanActivate(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	require.NoError(t, err)
	for _, outcome := range []string{"reject", "manual"} {
		d, err := s.Decide(ctx, principal(), spaceID, c.ID,
			release.DecisionInput{Outcome: outcome, Mode: "machine", PolicyRef: "gate-2026-10-15"})
		require.NoError(t, err)
		_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
		require.Equal(t, release.ErrorCandidateNotApproved, codeOf(t, err))
	}
	other, err := s.Receive(
		ctx, principal(), spaceID, candidateBundle(t, "", nil, member(t, "z", map[string]any{"v": 9})),
	)
	require.NoError(t, err)
	approved, err := s.Decide(ctx, principal(), spaceID, other.ID, approve)
	require.NoError(t, err)
	_, err = s.Activate(ctx, principal(), spaceID, c.ID, approved.ID)
	require.Equal(t, release.ErrorDecisionNotFound, codeOf(t, err), "another candidate's approval never applies")
	require.Zero(t, p.activations)
}

func TestDecisionsAreValidatedAndBoundToTheirContent(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	require.NoError(t, err)

	for _, bad := range []release.DecisionInput{
		{Outcome: "maybe", Mode: "machine", PolicyRef: "gate"},
		{Outcome: "approve", Mode: "robot", PolicyRef: "gate"},
		{Outcome: "approve", Mode: "machine"}, // machine review must name its versioned policy
		{Outcome: "approve", Mode: "machine", PolicyRef: "gate", Score: "high"},
	} {
		_, err := s.Decide(ctx, principal(), spaceID, c.ID, bad)
		require.Equal(t, release.ErrorDecisionInvalid, codeOf(t, err), "%+v", bad)
	}

	once, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	again, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	require.Equal(t, once.ID, again.ID)
	require.Equal(t, once.Digest, again.Digest)
	require.Equal(t, c.BundleDigest, once.BundleDigest)

	changed := approve
	changed.Reason = "抽检样本"
	different, err := s.Decide(ctx, principal(), spaceID, c.ID, changed)
	require.NoError(t, err)
	require.NotEqual(t, once.Digest, different.Digest)

	_, err = s.Decide(ctx, principal(), spaceID, "candidate-404", approve)
	require.Equal(t, release.ErrorCandidateNotFound, codeOf(t, err))
}

func TestAConcurrentActivationIsAConflictNotAnOverwrite(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	p.racer = &release.Head{ReleaseID: "release-racer", Epoch: 1}

	_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.Equal(t, release.ErrorReleaseConflict, codeOf(t, err))
	require.Equal(t, "release-racer", p.head.ReleaseID, "the other activation stays in place")
}

func TestReplayingAnActivationReturnsTheSameRelease(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	first, err := s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.NoError(t, err)
	again, err := s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.NoError(t, err)
	require.Equal(t, first.ID, again.ID)
	require.Equal(t, 1, p.activations)
}

func TestRemovingAMemberTheHeadDoesNotHaveIsInvalid(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	first := publish(t, s, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID,
		candidateBundle(t, first.ID, []string{"ghost"}, member(t, "b", map[string]any{"v": 2})))
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
	require.Equal(t, 1, p.activations)
}

func TestReleaseReadsFailClosed(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	ctx := context.Background()
	_, err := s.Release(ctx, principal(), spaceID, "")
	require.Equal(t, release.ErrorReleaseNotFound, codeOf(t, err), "no active release yet")
	publish(t, s, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	_, err = s.Release(ctx, principal(), spaceID, "release-404")
	require.Equal(t, release.ErrorReleaseNotFound, codeOf(t, err))
	_, err = s.Release(ctx, release.Principal{TenantID: 0, Subject: "x"}, spaceID, "")
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
}

func TestPublishingWithoutAPublisherIsUnavailable(t *testing.T) {
	p := newPlatform()
	s := release.NewService(p, fakeEvidence{allowed: map[string]bool{}}, schemas())
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	require.NoError(t, err)
	_, err = s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.Equal(t, release.ErrorServiceUnavailable, codeOf(t, err))
	_, err = s.Release(ctx, principal(), spaceID, "")
	require.Equal(t, release.ErrorServiceUnavailable, codeOf(t, err))
}
