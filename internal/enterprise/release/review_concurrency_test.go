package release_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// Both reviewers may observe pending and save their approvals before either activates.
// This deterministic interleaving lets the second activation read the first one's Head.
func TestReviewNoOpApprovalInterleavingDoesNotPublishCandidateTwice(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	unchanged := member(t, "a", map[string]any{"v": 1})
	base := publish(t, s, candidateBundle(t, "", nil, unchanged))
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, candidateBundle(t, base.ID, nil, unchanged))
	require.NoError(t, err, "a no-op member is a valid candidate today")
	first, second := principal(), principal()
	first.Subject, second.Subject = "web_user:reviewer-a", "web_user:reviewer-b"
	in := release.DecisionInput{Outcome: "approve", Mode: "human", Reason: "checked"}
	a, err := s.Decide(ctx, first, spaceID, c.ID, in)
	require.NoError(t, err)
	b, err := s.Decide(ctx, second, spaceID, c.ID, in)
	require.NoError(t, err)
	require.NotEqual(t, a.Digest, b.Digest)
	activated, err := s.Activate(ctx, first, spaceID, c.ID, a.ID)
	require.NoError(t, err)
	again, secondErr := s.Activate(ctx, second, spaceID, c.ID, b.ID)
	t.Logf("first=%s second=%s second_error=%v activations=%d", activated.ID, again.ID, secondErr, p.activations)
	require.NoError(t, secondErr)
	require.Equal(t, activated, again)
	require.Equal(t, 2, p.activations, "one seed release plus at most one release of this candidate")
}
