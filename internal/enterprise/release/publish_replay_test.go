package release_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// A commits as R1 but its response is lost; B commits on R1 as R2; A is retried. The retry
// must return R1 by nonce without a new write, while a candidate that never committed on the
// old base and touches a member the Head has since changed still needs a rebase (PR #164
// review item 1, Spec §3.1; since S8b an untouched Head advance is rebased automatically).
func TestRetryAfterTheHeadMovedReturnsTheCommittedRelease(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	ctx := context.Background()

	a, err := s.Receive(ctx, principal(), spaceID, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	require.NoError(t, err)
	approved, err := s.Decide(ctx, principal(), spaceID, a.ID, approve)
	require.NoError(t, err)
	stale, err := s.Receive(ctx, principal(), spaceID,
		candidateBundle(t, "", nil, member(t, "b", map[string]any{"v": 3})))
	require.NoError(t, err)
	staleDecision, err := s.Decide(ctx, principal(), spaceID, stale.ID, approve)
	require.NoError(t, err)

	r1, err := s.Activate(ctx, principal(), spaceID, a.ID, approved.ID)
	require.NoError(t, err)
	r2 := publish(t, s, candidateBundle(t, r1.ID, nil, member(t, "b", map[string]any{"v": 2})))
	writes := p.activations

	again, err := s.Activate(ctx, principal(), spaceID, a.ID, approved.ID)
	require.NoError(t, err)
	require.Equal(t, r1.ID, again.ID)
	require.Equal(t, writes, p.activations, "a replay writes nothing")
	head, err := s.Release(ctx, principal(), spaceID, "")
	require.NoError(t, err)
	require.Equal(t, r2.ID, head.ID, "the Head stays where B left it")

	_, err = s.Activate(ctx, principal(), spaceID, stale.ID, staleDecision.ID)
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorNeedsRebase, failure.Code)
	require.Equal(t, writes, p.activations, "a stale candidate writes nothing")
}
