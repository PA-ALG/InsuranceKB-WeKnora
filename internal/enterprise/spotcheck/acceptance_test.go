// RV4a acceptance: samples of a release's members and append-only verdicts on them
// (Spec docs/design/slices/RV4-发布后抽检.md §2.1, §6). Protected file: written by Claude.
//
// The service is exercised with an in-memory Store and ReleaseReader, so only its rules are
// covered here: the member digest comes from the release, never from the caller; samples are
// idempotent per (tenant, Space, release, slug); verdicts only append and name the principal;
// every scope is isolated. PostgreSQL storage, the migration and the routes are the
// implementer's tests. RED until RV4a implements the package.
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

const space = "space-1"

type key struct {
	tenant               uint64
	space, release, slug string
}

type memStore struct {
	samples  []tenantSample
	verdicts []tenantVerdict
	fail     error
}

type tenantSample struct {
	tenant uint64
	spotcheck.Sample
}

type tenantVerdict struct {
	tenant uint64
	space  string
	spotcheck.Verdict
}

func (m *memStore) InsertSamples(_ context.Context, tenantID uint64, in []spotcheck.Sample) ([]spotcheck.Sample, error) {
	if m.fail != nil {
		return nil, m.fail
	}
	out := make([]spotcheck.Sample, 0, len(in))
	for _, s := range in {
		found := false
		for _, kept := range m.samples {
			if (key{kept.tenant, kept.SpaceID, kept.ReleaseID, kept.LogicalSlug}) ==
				(key{tenantID, s.SpaceID, s.ReleaseID, s.LogicalSlug}) {
				out, found = append(out, kept.Sample), true
				break
			}
		}
		if !found {
			m.samples = append(m.samples, tenantSample{tenantID, s})
			out = append(out, s)
		}
	}
	return out, nil
}

func (m *memStore) latest(tenant uint64, sampleID string) *spotcheck.Verdict {
	var last *spotcheck.Verdict
	for i := range m.verdicts {
		if m.verdicts[i].tenant == tenant && m.verdicts[i].SampleID == sampleID {
			v := m.verdicts[i].Verdict
			last = &v
		}
	}
	return last
}

func (m *memStore) ListSamples(_ context.Context, tenantID uint64, spaceID string, f spotcheck.Filter) ([]spotcheck.Sample, error) {
	if m.fail != nil {
		return nil, m.fail
	}
	var out []spotcheck.Sample
	for _, s := range m.samples {
		if s.tenant != tenantID || s.SpaceID != spaceID || (f.ReleaseID != "" && s.ReleaseID != f.ReleaseID) {
			continue
		}
		sample := s.Sample
		sample.Verdict = m.latest(tenantID, s.ID)
		if (f.Status == "pending" && sample.Verdict != nil) || (f.Status == "decided" && sample.Verdict == nil) {
			continue
		}
		out = append(out, sample)
	}
	return out, nil
}

func (m *memStore) SampleByID(_ context.Context, tenantID uint64, spaceID, id string) (spotcheck.Sample, bool, error) {
	for _, s := range m.samples {
		if s.tenant == tenantID && s.SpaceID == spaceID && s.ID == id {
			sample := s.Sample
			sample.Verdict = m.latest(tenantID, id)
			return sample, true, nil
		}
	}
	return spotcheck.Sample{}, false, m.fail
}

func (m *memStore) AppendVerdict(_ context.Context, tenantID uint64, spaceID string, v spotcheck.Verdict) error {
	if m.fail != nil {
		return m.fail
	}
	m.verdicts = append(m.verdicts, tenantVerdict{tenantID, spaceID, v})
	return nil
}

type releases map[string]release.Release // keyed by "<tenant>/<space>/<release>"

func (r releases) Release(_ context.Context, p release.Principal, spaceID, releaseID string) (release.Release, error) {
	if got, ok := r[fmt.Sprintf("%d/%s/%s", p.TenantID, spaceID, releaseID)]; ok {
		return got, nil
	}
	return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound, Detail: "release was not found"}
}

func members(slugs ...string) []release.Member {
	out := make([]release.Member, 0, len(slugs))
	for _, slug := range slugs {
		out = append(out, release.Member{
			Kind: "claim", LogicalSlug: slug, MemberDigest: "digest-of-" + slug, AccessScope: "space",
		})
	}
	return out
}

func alice() release.Principal { return release.Principal{TenantID: 7, Subject: "user:alice"} }

func service(store *memStore) *spotcheck.Service {
	ids := 0
	return spotcheck.NewService(store, releases{
		"7/space-1/rel-1": {ID: "rel-1", Epoch: 3, Members: members("P1/a", "P1/b", "P2/a")},
		"7/space-1/rel-2": {ID: "rel-2", Epoch: 4, Members: members("P1/a")},
		"7/space-2/rel-9": {ID: "rel-9", Epoch: 1, Members: members("P1/a")},
		"8/space-1/rel-1": {ID: "rel-1", Epoch: 3, Members: members("P1/a")},
	},
		spotcheck.WithClock(func() time.Time { return time.Date(2026, 10, 18, 12, 0, 0, 0, time.UTC) }),
		spotcheck.WithIDs(func() string { ids++; return fmt.Sprintf("id-%d", ids) }),
	)
}

func codeOf(t *testing.T, err error) string {
	t.Helper()
	var failure *release.Error
	require.True(t, errors.As(err, &failure), "want *release.Error, got %v", err)
	return failure.Code
}

func TestSubmitTakesEachDigestFromTheReleaseAndIsIdempotent(t *testing.T) {
	store := &memStore{}
	s := service(store)
	got, err := s.Submit(context.Background(), alice(), space, "rel-1", []spotcheck.SampleInput{
		{Slug: "P1/b", Stratum: "pack/must"}, {Slug: "P1/a", Stratum: "pack/rest"},
	})
	require.NoError(t, err)
	require.Len(t, got, 2)
	require.Equal(t, []string{"P1/b", "P1/a"}, []string{got[0].LogicalSlug, got[1].LogicalSlug})
	require.Equal(t, "digest-of-P1/b", got[0].MemberDigest)
	require.Equal(t, "rel-1", got[0].ReleaseID)
	require.Equal(t, space, got[0].SpaceID)
	require.Equal(t, "pack/must", got[0].Stratum)
	require.Equal(t, "user:alice", got[0].CreatedBy)
	require.NotEmpty(t, got[0].ID)
	require.Nil(t, got[0].Verdict)

	again, err := s.Submit(context.Background(), alice(), space, "rel-1", []spotcheck.SampleInput{
		{Slug: "P1/a", Stratum: "another/stratum"}, {Slug: "P2/a", Stratum: "pack/rest"},
	})
	require.NoError(t, err)
	require.Equal(t, got[1].ID, again[0].ID)
	require.Equal(t, "pack/rest", again[0].Stratum) // the stored sample is returned unchanged
	require.Len(t, store.samples, 3)
}

func TestSubmitRefusesAWholeBatchThatIsNotOfTheRelease(t *testing.T) {
	store := &memStore{}
	s := service(store)
	_, err := s.Submit(context.Background(), alice(), space, "rel-1", []spotcheck.SampleInput{
		{Slug: "P1/a", Stratum: "s"}, {Slug: "P9/x", Stratum: "s"},
	})
	require.Equal(t, release.ErrorMemberNotFound, codeOf(t, err))
	for _, id := range []string{"", "active", "rel-404"} {
		_, err = s.Submit(context.Background(), alice(), space, id, []spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
		require.Equal(t, release.ErrorReleaseNotFound, codeOf(t, err), id)
	}
	_, err = s.Submit(context.Background(), alice(), "space-2", "rel-1", []spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
	require.Equal(t, release.ErrorReleaseNotFound, codeOf(t, err))
	require.Empty(t, store.samples)
}

func TestSubmitValidatesTheBatch(t *testing.T) {
	many := make([]spotcheck.SampleInput, 501)
	for i := range many {
		many[i] = spotcheck.SampleInput{Slug: "P1/a", Stratum: "s"}
	}
	for name, items := range map[string][]spotcheck.SampleInput{
		"empty":          nil,
		"blank slug":     {{Slug: " ", Stratum: "s"}},
		"blank stratum":  {{Slug: "P1/a", Stratum: "\t"}},
		"long stratum":   {{Slug: "P1/a", Stratum: strings.Repeat("s", 65)}},
		"repeated slug":  {{Slug: "P1/a", Stratum: "s"}, {Slug: "P1/a", Stratum: "t"}},
		"too many items": many,
	} {
		store := &memStore{}
		_, err := service(store).Submit(context.Background(), alice(), space, "rel-1", items)
		require.Equal(t, spotcheck.ErrorSampleInvalid, codeOf(t, err), name)
		require.Empty(t, store.samples, name)
	}
}

func TestListIsolatesScopesFiltersAndCarriesTheLatestVerdict(t *testing.T) {
	store := &memStore{}
	s := service(store)
	ctx := context.Background()
	first, err := s.Submit(ctx, alice(), space, "rel-1", []spotcheck.SampleInput{
		{Slug: "P1/a", Stratum: "s"}, {Slug: "P1/b", Stratum: "s"},
	})
	require.NoError(t, err)
	_, err = s.Submit(ctx, alice(), space, "rel-2", []spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
	require.NoError(t, err)
	_, err = s.Submit(ctx, alice(), "space-2", "rel-9", []spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
	require.NoError(t, err)
	other := release.Principal{TenantID: 8, Subject: "user:bob"}
	_, err = s.Submit(ctx, other, space, "rel-1", []spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
	require.NoError(t, err)

	_, err = s.Decide(ctx, alice(), space, first[0].ID, "wrong", "缺少等待期")
	require.NoError(t, err)
	_, err = s.Decide(ctx, alice(), space, first[0].ID, "incomplete", "改判：只缺一项")
	require.NoError(t, err)

	all, err := s.List(ctx, alice(), space, spotcheck.Filter{})
	require.NoError(t, err)
	require.Len(t, all, 3)
	require.NotNil(t, all[0].Verdict)
	require.Equal(t, "incomplete", all[0].Verdict.Outcome)

	pending, err := s.List(ctx, alice(), space, spotcheck.Filter{Status: "pending"})
	require.NoError(t, err)
	require.Len(t, pending, 2)
	decided, err := s.List(ctx, alice(), space, spotcheck.Filter{Status: "decided"})
	require.NoError(t, err)
	require.Len(t, decided, 1)
	byRelease, err := s.List(ctx, alice(), space, spotcheck.Filter{ReleaseID: "rel-2"})
	require.NoError(t, err)
	require.Len(t, byRelease, 1)
	theirs, err := s.List(ctx, other, space, spotcheck.Filter{})
	require.NoError(t, err)
	require.Len(t, theirs, 1)

	_, err = s.List(ctx, alice(), space, spotcheck.Filter{Status: "open"})
	require.Equal(t, spotcheck.ErrorSampleInvalid, codeOf(t, err))
}

func TestVerdictsAppendNameThePrincipalAndStayInScope(t *testing.T) {
	store := &memStore{}
	s := service(store)
	ctx := context.Background()
	samples, err := s.Submit(ctx, alice(), space, "rel-1", []spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
	require.NoError(t, err)
	id := samples[0].ID

	v, err := s.Decide(ctx, alice(), space, id, "correct", "  与条款一致  ")
	require.NoError(t, err)
	require.Equal(t, id, v.SampleID)
	require.Equal(t, "correct", v.Outcome)
	require.Equal(t, "与条款一致", v.Note)
	require.Equal(t, "user:alice", v.Reviewer)
	require.Equal(t, time.Date(2026, 10, 18, 12, 0, 0, 0, time.UTC), v.DecidedAt)
	require.NotEmpty(t, v.ID)

	for name, call := range map[string]func() error{
		"unknown outcome": func() error { _, e := s.Decide(ctx, alice(), space, id, "fine", ""); return e },
		"long note": func() error {
			_, e := s.Decide(ctx, alice(), space, id, "wrong", strings.Repeat("注", 1001))
			return e
		},
	} {
		require.Equal(t, spotcheck.ErrorVerdictInvalid, codeOf(t, call()), name)
	}
	for name, call := range map[string]func() error{
		"missing":     func() error { _, e := s.Decide(ctx, alice(), space, "id-404", "correct", ""); return e },
		"other space": func() error { _, e := s.Decide(ctx, alice(), "space-2", id, "correct", ""); return e },
		"other tenant": func() error {
			_, e := s.Decide(ctx, release.Principal{TenantID: 8, Subject: "u"}, space, id, "correct", "")
			return e
		},
	} {
		require.Equal(t, spotcheck.ErrorSampleNotFound, codeOf(t, call()), name)
	}
	require.Len(t, store.verdicts, 1)
}

func TestEveryCallNeedsAPrincipalAndAScope(t *testing.T) {
	store := &memStore{}
	s := service(store)
	ctx := context.Background()
	for _, p := range []release.Principal{{}, {TenantID: 7}, {Subject: "user:alice"}} {
		_, err := s.Submit(ctx, p, space, "rel-1", []spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
		require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
		_, err = s.List(ctx, p, space, spotcheck.Filter{})
		require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
		_, err = s.Decide(ctx, p, space, "id-1", "correct", "")
		require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	}
	_, err := s.List(ctx, alice(), " ", spotcheck.Filter{})
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	require.Empty(t, store.samples)
}

func TestStorageFailuresSurfaceUnchanged(t *testing.T) {
	boom := errors.New("storage unavailable")
	_, err := service(&memStore{fail: boom}).Submit(context.Background(), alice(), space, "rel-1",
		[]spotcheck.SampleInput{{Slug: "P1/a", Stratum: "s"}})
	require.ErrorIs(t, err, boom)
	_, err = service(&memStore{fail: boom}).List(context.Background(), alice(), space, spotcheck.Filter{})
	require.ErrorIs(t, err, boom)
}
