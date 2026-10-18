package spotcheck_test

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
)

func TestSubmitNormalizesItemsBeforeUniquenessAndCountsUnicodeCharacters(t *testing.T) {
	store := &memStore{}
	s := service(store)
	input := []spotcheck.SampleInput{{Slug: "\tP1/a\u3000", Stratum: "\u3000" + strings.Repeat("层", 64) + "\t"}}
	got, err := s.Submit(context.Background(), alice(), space, "rel-1", input)
	require.NoError(t, err)
	require.Equal(t, "P1/a", got[0].LogicalSlug)
	require.Equal(t, strings.Repeat("层", 64), got[0].Stratum)
	require.Equal(t, "\tP1/a\u3000", input[0].Slug, "caller input is not mutated")

	for _, items := range [][]spotcheck.SampleInput{
		{{Slug: "P1/b", Stratum: "s"}, {Slug: " \tP1/b\u3000", Stratum: "t"}},
		{{Slug: "P1/b", Stratum: strings.Repeat("层", 65)}},
		{{Slug: "P1/b", Stratum: "s"}, {Slug: "P2/a", Stratum: "\u3000"}},
	} {
		_, err := s.Submit(context.Background(), alice(), space, "rel-1", items)
		require.Equal(t, spotcheck.ErrorSampleInvalid, codeOf(t, err))
		require.Len(t, store.samples, 1, "every item is validated before any write")
	}
}

func TestSubmitAcceptsExactlyFiveHundredGenericMembers(t *testing.T) {
	store := &memStore{}
	items := make([]spotcheck.SampleInput, 500)
	var slugs []string
	for i := range items {
		slug := fmt.Sprintf("member/%03d", i)
		items[i] = spotcheck.SampleInput{Slug: slug, Stratum: "opaque"}
		slugs = append(slugs, slug)
	}
	s := spotcheck.NewService(store, releases{"7/space-1/rel": {ID: "rel", Members: members(slugs...)}})
	got, err := s.Submit(context.Background(), alice(), space, "rel", items)
	require.NoError(t, err)
	require.Len(t, got, 500)
	require.Len(t, store.samples, 500)
	seen := map[string]bool{}
	for i, sample := range got {
		require.Equal(t, slugs[i], sample.LogicalSlug)
		require.False(t, seen[sample.ID], "default identifiers are unique")
		seen[sample.ID] = true
	}
}

func TestListSortsByCreationThenIDAndReturnsAnEmptyArray(t *testing.T) {
	ctx := context.Background()
	store := &memStore{}
	got, err := service(store).List(ctx, alice(), space, spotcheck.Filter{})
	require.NoError(t, err)
	require.NotNil(t, got)
	require.Empty(t, got)

	now := time.Date(2026, 10, 18, 12, 0, 0, 0, time.UTC)
	for i, id := range []string{"z", "b", "a", "c"} {
		sample := storedSample(id, "rel-1", "P1/a")
		sample.CreatedAt = now
		if i == 3 {
			sample.CreatedAt = now.Add(-time.Second)
		}
		store.samples = append(store.samples, sample)
	}
	got, err = service(store).List(ctx, alice(), space, spotcheck.Filter{})
	require.NoError(t, err)
	require.Equal(t, []string{"c", "a", "b", "z"}, []string{got[0].ID, got[1].ID, got[2].ID, got[3].ID})
	require.Equal(t, "z", store.samples[0].ID, "sorting must not change storage order")
}

func TestVerdictUnicodeBoundaryAndClockRollbackKeepTheLastAppend(t *testing.T) {
	store := &memStore{samples: []tenantSample{storedSample("sample", "rel-1", "P1/a")}}
	now := time.Date(2026, 10, 18, 12, 0, 0, 0, time.UTC)
	s := spotcheck.NewService(store, nil, spotcheck.WithClock(func() time.Time { return now }))
	ctx := context.Background()
	first, err := s.Decide(ctx, alice(), space, "sample", "wrong", "\u3000"+strings.Repeat("注", 1000)+"\t")
	require.NoError(t, err)
	require.Equal(t, strings.Repeat("注", 1000), first.Note)
	now = now.Add(-time.Hour)
	last, err := s.Decide(ctx, alice(), space, "sample", "incomplete", "changed")
	require.NoError(t, err)
	require.True(t, last.DecidedAt.Before(first.DecidedAt))
	got, err := s.List(ctx, alice(), space, spotcheck.Filter{Status: "decided"})
	require.NoError(t, err)
	require.Equal(t, last.ID, got[0].Verdict.ID)

	_, err = s.Decide(ctx, alice(), space, "sample", "wrong", strings.Repeat("注", 1001))
	require.Equal(t, spotcheck.ErrorVerdictInvalid, codeOf(t, err))
	require.Len(t, store.verdicts, 2)
}

type failingVerdictStore struct {
	*memStore
	lookupErr, appendErr error
}

func (s failingVerdictStore) SampleByID(
	ctx context.Context, tenant uint64, spaceID, id string,
) (spotcheck.Sample, bool, error) {
	if s.lookupErr != nil {
		return spotcheck.Sample{}, false, s.lookupErr
	}
	return s.memStore.SampleByID(ctx, tenant, spaceID, id)
}

func (s failingVerdictStore) AppendVerdict(
	ctx context.Context, tenant uint64, spaceID string, v spotcheck.Verdict,
) error {
	if s.appendErr != nil {
		return s.appendErr
	}
	return s.memStore.AppendVerdict(ctx, tenant, spaceID, v)
}

func TestDecidePreservesLookupAndAppendFailuresWithoutReturningAVerdict(t *testing.T) {
	boom := errors.New("storage unavailable")
	for _, failed := range []failingVerdictStore{
		{lookupErr: boom}, {appendErr: boom},
	} {
		store := &memStore{samples: []tenantSample{storedSample("sample", "rel-1", "P1/a")}}
		failed.memStore = store
		v, err := spotcheck.NewService(failed, nil).Decide(
			context.Background(), alice(), space, "sample", "correct", "",
		)
		require.Same(t, boom, err)
		require.Empty(t, v.ID)
		require.Empty(t, store.verdicts)
	}
}

func TestPrincipalWithWhitespaceSubjectFailsClosedBeforeStorage(t *testing.T) {
	store := &memStore{}
	s := service(store)
	p := release.Principal{TenantID: 7, Subject: "\t\u3000"}
	ctx := context.Background()
	_, err := s.Submit(ctx, p, space, "rel-1", []spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	_, err = s.List(ctx, p, space, spotcheck.Filter{})
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	_, err = s.Decide(ctx, p, space, "sample", "correct", "")
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	require.Empty(t, store.samples)
	require.Empty(t, store.verdicts)
}
