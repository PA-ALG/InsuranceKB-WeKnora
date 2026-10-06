package release

import (
	"context"
	"errors"
	"fmt"
	"sort"
)

// Preview compares an immutable candidate against the current active release.
func (s *Service) Preview(ctx context.Context, p Principal, spaceID, candidateID string) (Preview, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return Preview{}, err
	}
	if err := ctx.Err(); err != nil {
		return Preview{}, err
	}
	ctx = context.WithValue(ctx, scopeKey{}, Scope{Principal: p, SpaceID: spaceID})
	if s.store == nil {
		return Preview{}, errors.New("candidate store unavailable")
	}
	c, err := s.store.CandidateByID(ctx, p.TenantID, spaceID, candidateID)
	if err != nil {
		return Preview{}, fmt.Errorf("read candidate: %w", err)
	}
	if err := checkCandidateAccess(c, p, spaceID); err != nil {
		return Preview{}, err
	}
	if c.ID != candidateID {
		return Preview{}, errors.New("candidate store returned an inconsistent record")
	}
	b, err := s.store.BundleOf(ctx, p.TenantID, spaceID, candidateID)
	if err != nil {
		return Preview{}, fmt.Errorf("read candidate bundle: %w", err)
	}
	head, err := s.store.Head(ctx, p.TenantID, spaceID)
	if err != nil {
		return Preview{}, fmt.Errorf("read active head: %w", err)
	}
	var members map[string]string
	if head.ReleaseID != "" {
		members, err = s.store.MembersOf(ctx, p.TenantID, spaceID, head.ReleaseID)
		if err != nil {
			return Preview{}, fmt.Errorf("read active members: %w", err)
		}
	}
	return Preview{
		CandidateID: c.ID, BaseReleaseID: c.BaseReleaseID, HeadReleaseID: head.ReleaseID,
		// There is no competing release to rebase onto before first activation.
		NeedsRebase: head.ReleaseID != "" && head.ReleaseID != c.BaseReleaseID,
		Delta:       compareMembers(b, members),
	}, nil
}

func compareMembers(b Bundle, head map[string]string) Delta {
	delta := Delta{Added: []string{}, Changed: []string{}, Removed: []string{}, Unchanged: []string{}}
	touched := make(map[string]bool, len(b.Members)+len(b.Removals))
	for _, m := range b.Members {
		touched[m.LogicalSlug] = true
		previous, exists := head[m.LogicalSlug]
		switch {
		case !exists:
			delta.Added = append(delta.Added, m.LogicalSlug)
		case previous != m.MemberDigest:
			delta.Changed = append(delta.Changed, m.LogicalSlug)
		default:
			delta.Unchanged = append(delta.Unchanged, m.LogicalSlug)
		}
	}
	for _, slug := range b.Removals {
		touched[slug] = true
		if _, exists := head[slug]; exists {
			delta.Removed = append(delta.Removed, slug)
		}
	}
	for slug := range head {
		if !touched[slug] {
			delta.Unchanged = append(delta.Unchanged, slug)
		}
	}
	sort.Strings(delta.Added)
	sort.Strings(delta.Changed)
	sort.Strings(delta.Removed)
	sort.Strings(delta.Unchanged)
	return delta
}
