// S8b acceptance: a candidate whose base is no longer the Head is applied on top of the
// current Head when the Head has not touched any slug the candidate touches; otherwise it
// still needs a rebase and nothing is written (Spec docs/design/slices/S8b-自动变基与实体回退.md
// §4). Protected file: written by Claude. RED until S8b: every base mismatch needs a rebase.
package release_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// activate receives, approves and activates one bundle, returning the activation error.
func activate(t *testing.T, s *release.Service, raw []byte) (release.Release, error) {
	t.Helper()
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, raw)
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	return s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
}

// moved publishes a first release (a, b, x) and then another candidate that changes x.
func moved(t *testing.T) (*platform, *release.Service, release.Release, release.Release) {
	t.Helper()
	p := newPlatform()
	s := publishing(p)
	first := publish(t, s, candidateBundle(t, "", nil,
		member(t, "a", map[string]any{"v": 1}),
		member(t, "b", map[string]any{"v": 2}),
		member(t, "x", map[string]any{"v": 9})))
	second := publish(t, s, candidateBundle(t, first.ID, nil, member(t, "x", map[string]any{"v": 90})))
	return p, s, first, second
}

func TestAnUntouchedHeadAdvanceIsRebasedAutomatically(t *testing.T) {
	p, s, first, second := moved(t)
	third, err := activate(t, s, candidateBundle(t, first.ID, []string{"a"},
		member(t, "b", map[string]any{"v": 20})))
	require.NoError(t, err)
	require.Equal(t, second.ID, third.BaseReleaseID, "the delta lands on the current Head")
	require.Equal(t, []string{"b", "x"}, slugs(third))
	require.JSONEq(t, `{"v":20}`, string(memberBySlug(third, "b").Payload))
	require.JSONEq(t, `{"v":90}`, string(memberBySlug(third, "x").Payload), "the Head's own change is kept")
	require.Equal(t, 3, p.activations)
}

func TestAHeadThatChangedATouchedSlugStillNeedsRebase(t *testing.T) {
	for name, raw := range map[string]func(*testing.T, string) []byte{
		"changed member": func(t *testing.T, base string) []byte {
			return candidateBundle(t, base, nil, member(t, "x", map[string]any{"v": 91}))
		},
		"removed member": func(t *testing.T, base string) []byte {
			return candidateBundle(t, base, []string{"x"}, member(t, "c", map[string]any{"v": 3}))
		},
	} {
		t.Run(name, func(t *testing.T) {
			p, s, first, second := moved(t)
			_, err := activate(t, s, raw(t, first.ID))
			require.Equal(t, release.ErrorNeedsRebase, codeOf(t, err))
			require.Equal(t, 2, p.activations, "nothing is written")
			require.Equal(t, second.ID, p.head.ReleaseID)
		})
	}
}

func TestAHeadThatAddedTheSameNewSlugStillNeedsRebase(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	first := publish(t, s, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	publish(t, s, candidateBundle(t, first.ID, nil, member(t, "n", map[string]any{"v": 1})))
	_, err := activate(t, s, candidateBundle(t, first.ID, nil, member(t, "n", map[string]any{"v": 2})))
	require.Equal(t, release.ErrorNeedsRebase, codeOf(t, err))
	require.Equal(t, 2, p.activations)
}

func TestAnUnknownBaseStillNeedsRebase(t *testing.T) {
	p, s, _, _ := moved(t)
	_, err := activate(t, s, candidateBundle(t, "release-old", nil, member(t, "b", map[string]any{"v": 3})))
	require.Equal(t, release.ErrorNeedsRebase, codeOf(t, err))
	require.Equal(t, 2, p.activations)
}

func TestAFirstPublishCandidateIsRebasedOntoAnUnrelatedHead(t *testing.T) {
	p := newPlatform()
	s := publishing(p)
	first := publish(t, s, candidateBundle(t, "", nil, member(t, "a", map[string]any{"v": 1})))
	second, err := activate(t, s, candidateBundle(t, "", nil, member(t, "b", map[string]any{"v": 2})))
	require.NoError(t, err)
	require.Equal(t, first.ID, second.BaseReleaseID)
	require.Equal(t, []string{"a", "b"}, slugs(second))
	require.Equal(t, 2, p.activations)
}
