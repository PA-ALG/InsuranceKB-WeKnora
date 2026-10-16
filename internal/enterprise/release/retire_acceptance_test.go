// S4c-2b-1 acceptance: retiring a non-active release and listing the releases that pin a
// source (Spec docs/design/slices/S4c-2b-1-发布固定来源.md §3.3). Protected file: written by Claude.
//
// Reuses the S4c-2a in-memory platform (Store + Publisher) and adds an in-memory Retirer,
// so only the service rules are exercised here; persistence and unpinning are covered by
// the adapter's PostgreSQL tests. RED until S4c-2b-1 implements it.
package release_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

type memRetirer struct {
	retired map[string]release.Retirement
	writes  []release.RetirementWrite
	pins    []release.SourcePin
	queries []string
	fail    error
}

func newRetirer() *memRetirer { return &memRetirer{retired: map[string]release.Retirement{}} }

func (m *memRetirer) Retire(_ context.Context, w release.RetirementWrite) (release.Retirement, error) {
	m.writes = append(m.writes, w)
	if m.fail != nil {
		return release.Retirement{}, m.fail
	}
	if r, ok := m.retired[w.ReleaseID]; ok {
		return r, nil
	}
	r := release.Retirement{
		ReleaseID: w.ReleaseID, Reason: w.Reason, Subject: w.Subject,
		RetiredAt: time.Date(2026, 10, 16, 12, 0, 0, 0, time.UTC),
	}
	m.retired[w.ReleaseID] = r
	return r, nil
}

func (m *memRetirer) SourcePins(_ context.Context, _ uint64, _, knowledgeID string) ([]release.SourcePin, error) {
	m.queries = append(m.queries, knowledgeID)
	return m.pins, m.fail
}

// twoReleases publishes r1 and then r2 on top of it, so r2 is the Space's active release.
func twoReleases(t *testing.T, p *platform, r *memRetirer) (*release.Service, release.Release, release.Release) {
	t.Helper()
	s := release.NewService(p, fakeEvidence{allowed: map[string]bool{"source:v1:k-1:1:abc": true}}, schemas(),
		release.WithPublisher(p), release.WithRetirer(r))
	first := publish(t, s, candidateBundle(t, "", nil,
		member(t, "a", map[string]any{"v": 1}, "source:v1:k-1:1:abc")))
	second := publish(t, s, candidateBundle(t, first.ID, nil, member(t, "b", map[string]any{"v": 2})))
	return s, first, second
}

func TestRetireNeedsAConfiguredRetirerAndAccess(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	_, err := s.Retire(context.Background(), principal(), spaceID, "release-1", "superseded")
	require.Equal(t, release.ErrorServiceUnavailable, codeOf(t, err))
	_, err = s.SourcePins(context.Background(), principal(), spaceID, "k-1")
	require.Equal(t, release.ErrorServiceUnavailable, codeOf(t, err))

	r := newRetirer()
	s, first, _ := twoReleases(t, newPlatform(), r)
	_, err = s.Retire(context.Background(), release.Principal{TenantID: 7}, spaceID, first.ID, "superseded")
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	_, err = s.SourcePins(context.Background(), release.Principal{Subject: "svc"}, spaceID, "k-1")
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	require.Empty(t, r.writes)
	require.Empty(t, r.queries)
}

func TestRetireValidatesTheRequestBeforeWriting(t *testing.T) {
	r := newRetirer()
	s, first, _ := twoReleases(t, newPlatform(), r)
	ctx := context.Background()

	_, err := s.Retire(ctx, principal(), spaceID, "  ", "superseded")
	require.Equal(t, release.ErrorReleaseNotFound, codeOf(t, err))
	for _, reason := range []string{"", "   \n", strings.Repeat("理", 501)} {
		_, err = s.Retire(ctx, principal(), spaceID, first.ID, reason)
		require.Equal(t, release.ErrorRetirementInvalid, codeOf(t, err), "reason %q", reason)
	}
	require.Empty(t, r.writes)

	_, err = s.Retire(ctx, principal(), spaceID, first.ID, strings.Repeat("理", 500))
	require.NoError(t, err, "500 characters is the limit, not bytes")
}

func TestTheActiveReleaseCannotBeRetired(t *testing.T) {
	r := newRetirer()
	s, _, active := twoReleases(t, newPlatform(), r)

	_, err := s.Retire(context.Background(), principal(), spaceID, active.ID, "superseded")
	require.Equal(t, release.ErrorReleaseActive, codeOf(t, err))
	require.Empty(t, r.writes, "the service refuses the Head before asking the platform")
}

func TestRetiringAnOlderReleaseHandsTheScopedWriteToThePlatform(t *testing.T) {
	r := newRetirer()
	s, first, _ := twoReleases(t, newPlatform(), r)
	ctx := context.Background()

	got, err := s.Retire(ctx, principal(), spaceID, first.ID, "  replaced by the 2026 terms  ")
	require.NoError(t, err)
	require.Equal(t, []release.RetirementWrite{{
		TenantID: 7, SpaceID: spaceID, ReleaseID: first.ID,
		Reason: "replaced by the 2026 terms", Subject: "svc-harness",
	}}, r.writes)
	require.Equal(t, first.ID, got.ReleaseID)
	require.Equal(t, "replaced by the 2026 terms", got.Reason)

	again, err := s.Retire(ctx, principal(), spaceID, first.ID, "another reason")
	require.NoError(t, err)
	require.Equal(t, got, again, "retiring twice returns the original record")
}

func TestPlatformRefusalsKeepTheirTypedCodes(t *testing.T) {
	for _, code := range []string{release.ErrorReleaseActive, release.ErrorReleaseNotFound} {
		r := newRetirer()
		s, first, _ := twoReleases(t, newPlatform(), r)
		r.fail = &release.Error{Code: code, Detail: "decided inside the platform transaction"}
		_, err := s.Retire(context.Background(), principal(), spaceID, first.ID, "superseded")
		require.Equal(t, code, codeOf(t, err))
	}
}

func TestSourcePinsListsTheReleasesCitingAKnowledge(t *testing.T) {
	r := newRetirer()
	s, first, active := twoReleases(t, newPlatform(), r)
	r.pins = []release.SourcePin{
		{ReleaseID: first.ID, ParseAttempt: 1},
		{ReleaseID: active.ID, ParseAttempt: 1, Active: true},
	}
	ctx := context.Background()

	pins, err := s.SourcePins(ctx, principal(), spaceID, "k-1")
	require.NoError(t, err)
	require.Equal(t, r.pins, pins)
	require.Equal(t, []string{"k-1"}, r.queries)

	_, err = s.SourcePins(ctx, principal(), spaceID, " ")
	require.Equal(t, release.ErrorInvalidRequest, codeOf(t, err))
	require.Equal(t, []string{"k-1"}, r.queries)
}
