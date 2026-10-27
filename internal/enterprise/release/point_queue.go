package release

import (
	"context"
	"errors"
	"math"
	"sort"
	"time"
)

func (s *Service) pointQueue(ctx context.Context, p Principal, space, status string) ([]ReviewSummary, error) {
	// Fully point-decided candidates remain SQL-pending under RV5a's frozen
	// QueueStore semantics, so classification reads grow with that history. This
	// is acceptable for dozens of manual candidates; once they reach hundreds,
	// replace this scan with a storage-level point-completion marker and bounded
	// ordering. Do not reinterpret QueueStore's whole-candidate state here.
	entries, err := s.queue.Queue(ctx, p.TenantID, space, "pending", math.MaxInt)
	if err != nil {
		return nil, err
	}
	type item struct {
		entry  QueueEntry
		bundle Bundle
		points *reviewPoints
		status string
		last   time.Time
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
		state, _, _, last := points.state(e)
		byID[e.Candidate.ID] = item{e, b, points, state, last}
	}
	if status == "decided" {
		decided, err := s.queue.Queue(ctx, p.TenantID, space, "decided", math.MaxInt)
		if err != nil {
			return nil, err
		}
		for _, e := range decided {
			if err := reviewEntryAccess(e, p, space); err != nil {
				return nil, err
			}
			// Rank whole decisions from metadata before reading their bundles.
			// If a decision landed between the queries, keep its newer metadata
			// while reusing the pending query's immutable bundle/point reads.
			value := byID[e.Candidate.ID]
			value.entry, value.status, value.last = e, e.Candidate.Status, e.CreatedAt
			if e.Decision != nil {
				value.last = e.Decision.CreatedAt
			}
			byID[e.Candidate.ID] = value
		}
	}
	items := make([]item, 0, len(byID))
	for _, value := range byID {
		if (status == "pending") == (value.status == "pending") {
			items = append(items, value)
		}
	}
	sort.Slice(items, func(i, j int) bool {
		left, right := items[i], items[j]
		if status == "pending" {
			if left.entry.CreatedAt.Equal(right.entry.CreatedAt) {
				return left.entry.Candidate.ID < right.entry.Candidate.ID
			}
			return left.entry.CreatedAt.Before(right.entry.CreatedAt)
		}
		if left.last.Equal(right.last) {
			return left.entry.Candidate.ID > right.entry.Candidate.ID
		}
		return left.last.After(right.last)
	})
	if status == "decided" && len(items) > 100 {
		items = items[:100]
	}
	out := make([]ReviewSummary, 0, len(items))
	for _, v := range items {
		if v.points == nil {
			v.bundle, err = s.store.BundleOf(ctx, p.TenantID, space, v.entry.Candidate.ID)
			if err != nil {
				return nil, err
			}
			v.points, err = reads.load(ctx, v.entry, v.bundle)
			if err != nil {
				return nil, err
			}
		}
		summary, _, err := v.points.summary(v.entry, v.bundle)
		if err != nil {
			return nil, err
		}
		out = append(out, summary)
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
