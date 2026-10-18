package spotcheck

import (
	"context"
	"errors"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// Service validates complete sample batches and appends attributed verdicts.
type Service struct {
	store     Store
	releases  ReleaseReader
	clock     func() time.Time
	ids       func() string
	spaceOnly bool
}

// Option configures the service clock or identifier generation.
type Option func(*Service)

// WithClock supplies creation and decision timestamps.
func WithClock(clock func() time.Time) Option {
	return func(s *Service) {
		if clock != nil {
			s.clock = clock
		}
	}
}

// WithIDs supplies identifiers for samples and verdicts.
func WithIDs(ids func() string) Option {
	return func(s *Service) {
		if ids != nil {
			s.ids = ids
		}
	}
}

// NewService connects sample storage and release reads, defaulting to system time and random identifiers.
func NewService(store Store, releases ReleaseReader, opts ...Option) *Service {
	s := &Service{store: store, releases: releases, clock: time.Now, ids: uuid.NewString}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

// Submit validates every item before inserting any samples. Digests are taken
// exclusively from the requested immutable release.
func (s *Service) Submit(
	ctx context.Context, p release.Principal, spaceID, releaseID string, items []SampleInput,
) ([]Sample, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return nil, err
	}
	if strings.TrimSpace(releaseID) == "" || strings.TrimSpace(releaseID) == "active" {
		return nil, failure(release.ErrorReleaseNotFound, "an explicit release is required")
	}
	normalized, err := validateSamples(items)
	if err != nil {
		return nil, err
	}
	if err := s.available(ctx, true); err != nil {
		return nil, err
	}
	r, err := s.releases.Release(ctx, p, spaceID, releaseID)
	if err != nil {
		var typed *release.Error
		if errors.As(err, &typed) && typed.Code == release.ErrorReleaseAccessDenied {
			return nil, failure(release.ErrorReleaseNotFound, "release was not found")
		}
		return nil, err
	}
	digests := make(map[string]string, len(r.Members))
	for _, m := range r.Members {
		digests[m.LogicalSlug] = m.MemberDigest
	}
	for _, item := range normalized {
		if _, ok := digests[item.Slug]; !ok {
			return nil, failure(release.ErrorMemberNotFound, "sample member was not found in the release")
		}
	}
	samples := make([]Sample, 0, len(normalized))
	for _, item := range normalized {
		samples = append(samples, Sample{
			ID: s.ids(), SpaceID: spaceID, ReleaseID: releaseID, LogicalSlug: item.Slug,
			MemberDigest: digests[item.Slug], Stratum: item.Stratum,
			CreatedBy: p.Subject, CreatedAt: s.clock(),
		})
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return s.store.InsertSamples(ctx, p.TenantID, samples)
}

func validateSamples(items []SampleInput) ([]SampleInput, error) {
	if len(items) == 0 || len(items) > 500 {
		return nil, failure(ErrorSampleInvalid, "a batch must contain 1 to 500 samples")
	}
	seen := make(map[string]bool, len(items))
	out := make([]SampleInput, 0, len(items))
	for _, item := range items {
		item.Slug = strings.TrimSpace(item.Slug)
		item.Stratum = strings.TrimSpace(item.Stratum)
		if item.Slug == "" || item.Stratum == "" || utf8.RuneCountInString(item.Stratum) > 64 || seen[item.Slug] {
			return nil, failure(ErrorSampleInvalid, "sample slug and stratum must be valid and slugs unique")
		}
		seen[item.Slug] = true
		out = append(out, item)
	}
	return out, nil
}

// List returns scoped samples with latest verdicts in creation and ID order.
func (s *Service) List(ctx context.Context, p release.Principal, spaceID string, f Filter) ([]Sample, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return nil, err
	}
	if f.Status != "" && f.Status != "pending" && f.Status != "decided" {
		return nil, failure(ErrorSampleInvalid, "status must be pending or decided")
	}
	if err := s.available(ctx, false); err != nil {
		return nil, err
	}
	samples, err := s.store.ListSamples(ctx, p.TenantID, spaceID, f)
	if err != nil {
		return nil, err
	}
	if s.spaceOnly {
		samples, err = s.readableSamples(ctx, p, spaceID, samples)
		if err != nil {
			return nil, err
		}
	}
	// Copy before sorting: adapters may reuse their backing slice.
	out := append(make([]Sample, 0, len(samples)), samples...)
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].CreatedAt.Equal(out[j].CreatedAt) {
			return out[i].ID < out[j].ID
		}
		return out[i].CreatedAt.Before(out[j].CreatedAt)
	})
	return out, nil
}

// Decide appends a verdict attributed to the authenticated principal.
func (s *Service) Decide(
	ctx context.Context, p release.Principal, spaceID, sampleID, outcome, note string,
) (Verdict, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return Verdict{}, err
	}
	note = strings.TrimSpace(note)
	if (outcome != "correct" && outcome != "incomplete" && outcome != "wrong") || utf8.RuneCountInString(note) > 1000 {
		return Verdict{}, failure(ErrorVerdictInvalid, "outcome or note is invalid")
	}
	if err := s.available(ctx, false); err != nil {
		return Verdict{}, err
	}
	sample, found, err := s.store.SampleByID(ctx, p.TenantID, spaceID, sampleID)
	if err != nil {
		return Verdict{}, err
	}
	if !found {
		return Verdict{}, failure(ErrorSampleNotFound, "sample was not found")
	}
	if s.spaceOnly {
		visible, err := s.readableSamples(ctx, p, spaceID, []Sample{sample})
		if err != nil {
			return Verdict{}, err
		}
		if len(visible) == 0 {
			return Verdict{}, failure(ErrorSampleNotFound, "sample was not found")
		}
	}
	v := Verdict{
		ID: s.ids(), SampleID: sampleID, Outcome: outcome, Note: note,
		Reviewer: p.Subject, DecidedAt: s.clock(),
	}
	if err := ctx.Err(); err != nil {
		return Verdict{}, err
	}
	if err := s.store.AppendVerdict(ctx, p.TenantID, spaceID, v); err != nil {
		return Verdict{}, err
	}
	return v, nil
}

func checkAccess(p release.Principal, spaceID string) error {
	if p.TenantID == 0 || strings.TrimSpace(p.Subject) == "" || strings.TrimSpace(spaceID) == "" {
		return failure(release.ErrorReleaseAccessDenied, "tenant, subject and Space are required")
	}
	return nil
}

func (s *Service) available(ctx context.Context, needRelease bool) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if s == nil || s.store == nil || ((needRelease || s.spaceOnly) && s.releases == nil) {
		return failure(release.ErrorServiceUnavailable, "spot checks are not configured")
	}
	return nil
}

func failure(code, detail string) error { return &release.Error{Code: code, Detail: detail} }
