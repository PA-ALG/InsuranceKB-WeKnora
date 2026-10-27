package release

import (
	"context"
	"errors"
	"math"
	"sort"
	"time"
)

func (s *Service) pointQueue(ctx context.Context, p Principal, space, status string) ([]ReviewSummary, error) {
	entries, err := s.queue.Queue(ctx, p.TenantID, space, "pending", math.MaxInt)
	if err != nil {
		return nil, err
	}
	if status == "decided" {
		decided, readErr := s.queue.Queue(ctx, p.TenantID, space, "decided", math.MaxInt)
		if readErr != nil {
			return nil, readErr
		}
		entries = append(entries, decided...)
	}
	type item struct {
		summary ReviewSummary
		last    time.Time
	}
	byID := map[string]item{}
	reads := newPointReads(s, p, space)
	for _, e := range entries {
		if err := reviewEntryAccess(e, p, space); err != nil {
			return nil, err
		}
		b, err := s.store.BundleOf(ctx, p.TenantID, space, e.Candidate.ID)
		if err != nil {
			return nil, err
		}
		points, err := reads.load(ctx, e, b)
		if err != nil {
			return nil, err
		}
		summary, last, err := points.summary(e, b)
		if err != nil {
			return nil, err
		}
		byID[e.Candidate.ID] = item{summary, last}
	}
	items := make([]item, 0, len(byID))
	for _, value := range byID {
		if (status == "pending") == (value.summary.Status == "pending") {
			items = append(items, value)
		}
	}
	sort.Slice(items, func(i, j int) bool {
		left, right := items[i], items[j]
		if status == "pending" {
			if left.summary.CreatedAt.Equal(right.summary.CreatedAt) {
				return left.summary.CandidateID < right.summary.CandidateID
			}
			return left.summary.CreatedAt.Before(right.summary.CreatedAt)
		}
		if left.last.Equal(right.last) {
			return left.summary.CandidateID > right.summary.CandidateID
		}
		return left.last.After(right.last)
	})
	if status == "decided" && len(items) > 100 {
		items = items[:100]
	}
	out := make([]ReviewSummary, 0, len(items))
	for _, v := range items {
		out = append(out, v.summary)
	}
	return out, nil
}

func (s *Service) pointDetail(
	ctx context.Context, p Principal, space string, e QueueEntry, b Bundle,
) (ReviewDetail, error) {
	reads := newPointReads(s, p, space)
	points, err := reads.load(ctx, e, b)
	if err != nil {
		return ReviewDetail{}, err
	}
	summary, _, err := points.summary(e, b)
	if err != nil {
		return ReviewDetail{}, err
	}
	head, active, err := reads.head(ctx)
	if err != nil {
		return ReviewDetail{}, err
	}
	views, err := points.views(e, active)
	if err != nil {
		return ReviewDetail{}, err
	}
	out := ReviewDetail{
		ReviewSummary: summary, HeadReleaseID: optionalString(head.ReleaseID),
		BundleMembers: b.Members, BundleRemovals: b.Removals, Points: views,
	}
	if len(points.decisions) > 0 || e.Candidate.Status == "rejected" || e.Candidate.Status == "released" {
		out.Blocker = ErrorCandidateDecided
		return out, nil
	}
	err = checkBase(b, head)
	if err == nil {
		_, err = materialize(active.Members, b)
	} else if b.BaseReleaseID != head.ReleaseID {
		_, err = rebasePointDelta(points.base, b, active)
	}
	if err != nil {
		var failure *Error
		if !errors.As(err, &failure) {
			return ReviewDetail{}, err
		}
		out.Blocker = failure.Code
	}
	return out, nil
}
