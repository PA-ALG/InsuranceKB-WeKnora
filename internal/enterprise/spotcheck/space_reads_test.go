package spotcheck_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
)

type releaseReaderFunc func(context.Context, release.Principal, string, string) (release.Release, error)

func (f releaseReaderFunc) Release(
	ctx context.Context, p release.Principal, spaceID, releaseID string,
) (release.Release, error) {
	return f(ctx, p, spaceID, releaseID)
}

func storedSample(id, releaseID, slug string) tenantSample {
	return tenantSample{7, spotcheck.Sample{
		ID: id, SpaceID: space, ReleaseID: releaseID, LogicalSlug: slug, MemberDigest: "digest-of-" + slug,
	}}
}

func TestSpaceReadViewFiltersTheSamplesOwnReleaseAndDoesNotChangeTheService(t *testing.T) {
	store := &memStore{samples: []tenantSample{
		storedSample("a", "old", "visible"), storedSample("b", "old", "private"),
		storedSample("c", "old", "missing"), storedSample("d", "old", "changed"),
		storedSample("e", "other", "visible"),
	}}
	calls := map[string]int{}
	reader := releaseReaderFunc(func(
		_ context.Context, p release.Principal, spaceID, id string,
	) (release.Release, error) {
		require.Equal(t, alice(), p)
		require.Equal(t, space, spaceID)
		calls[id]++
		require.Contains(t, []string{"old", "other"}, id, "must never resolve Active")
		m := members("visible", "private", "changed")
		m[1].AccessScope = "restricted"
		m[2].MemberDigest = "another-digest"
		return release.Release{ID: id, Members: m}, nil
	})
	s := spotcheck.NewService(store, reader)
	view := s.SpaceReadView()
	require.NotSame(t, s, view)
	all, err := s.List(context.Background(), alice(), space, spotcheck.Filter{})
	require.NoError(t, err)
	require.Len(t, all, 5)
	require.Empty(t, calls, "API Key list does not need a release read")

	visible, err := view.List(context.Background(), alice(), space, spotcheck.Filter{})
	require.NoError(t, err)
	require.Len(t, visible, 2)
	require.Equal(t, []string{"a", "e"}, []string{visible[0].ID, visible[1].ID})
	require.Equal(t, map[string]int{"old": 1, "other": 1}, calls, "one release lookup per list")
	all, err = s.List(context.Background(), alice(), space, spotcheck.Filter{})
	require.NoError(t, err)
	require.Len(t, all, 5, "creating a view must not alter the original service")

	var absent *spotcheck.Service
	require.Nil(t, absent.SpaceReadView())
}

func TestSpaceReadViewOnlyAppendsVerdictsOnReadableSamples(t *testing.T) {
	store := &memStore{samples: []tenantSample{
		storedSample("a", "old", "visible"), storedSample("b", "old", "private"),
		storedSample("c", "old", "missing"), storedSample("d", "old", "changed"),
	}}
	reader := releaseReaderFunc(func(_ context.Context, _ release.Principal, _, id string) (release.Release, error) {
		require.Equal(t, "old", id)
		m := members("visible", "private", "changed")
		m[1].AccessScope = "restricted"
		m[2].MemberDigest = "another-digest"
		return release.Release{ID: id, Members: m}, nil
	})
	s := spotcheck.NewService(store, reader)
	view := s.SpaceReadView()
	ctx := context.Background()
	for _, id := range []string{"b", "c", "d"} {
		_, err := view.Decide(ctx, alice(), space, id, "correct", "")
		require.Equal(t, spotcheck.ErrorSampleNotFound, codeOf(t, err))
	}
	require.Empty(t, store.verdicts)
	v, err := view.Decide(ctx, alice(), space, "a", "correct", " visible ")
	require.NoError(t, err)
	require.Equal(t, "user:alice", v.Reviewer)
	require.Equal(t, "visible", v.Note)
	require.Len(t, store.verdicts, 1)

	_, err = s.Decide(ctx, alice(), space, "b", "wrong", "")
	require.NoError(t, err, "original service retains API Key access")
	require.Len(t, store.verdicts, 2)
}

func TestSpaceReadViewHidesUnreadableReleasesAndPropagatesBackendFailures(t *testing.T) {
	boom := errors.New("release backend unavailable")
	for _, failure := range []error{
		&release.Error{Code: release.ErrorReleaseNotFound},
		&release.Error{Code: release.ErrorReleaseAccessDenied}, boom,
	} {
		t.Run(failure.Error(), func(t *testing.T) {
			store := &memStore{samples: []tenantSample{storedSample("a", "old", "visible")}}
			s := spotcheck.NewService(store, releaseReaderFunc(func(
				context.Context, release.Principal, string, string,
			) (release.Release, error) {
				return release.Release{}, failure
			})).SpaceReadView()
			got, err := s.List(context.Background(), alice(), space, spotcheck.Filter{})
			_, decisionErr := s.Decide(context.Background(), alice(), space, "a", "correct", "")
			if failure == boom {
				require.Same(t, boom, err)
				require.Nil(t, got, "partial lists must not escape on a backend failure")
				require.Same(t, boom, decisionErr)
			} else {
				require.NoError(t, err)
				require.NotNil(t, got)
				require.Empty(t, got)
				require.Equal(t, spotcheck.ErrorSampleNotFound, codeOf(t, decisionErr))
			}
			require.Empty(t, store.verdicts)
		})
	}
}
