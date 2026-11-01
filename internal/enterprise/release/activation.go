package release

import (
	"context"
	"errors"
)

func (s *Service) publishedCandidate(
	ctx context.Context, p Principal, spaceID string, c Candidate,
) (Release, bool, error) {
	reader, ok := s.publisher.(CandidateReleaseReader)
	if !ok {
		return Release{}, false, nil
	}
	committed, found, err := reader.PublishedCandidate(ctx, p.TenantID, spaceID, c.BundleDigest)
	if err == nil && found && committed.ID == "" {
		return Release{}, false, errors.New("publisher returned an empty committed release")
	}
	return committed, found, err
}

func (s *Service) activationHead(ctx context.Context, p Principal, spaceID string) (Head, Release, error) {
	head, err := s.store.Head(ctx, p.TenantID, spaceID)
	if err != nil || head.ReleaseID == "" {
		return head, Release{}, err
	}
	active, err := s.publisher.ReleaseByID(ctx, p.TenantID, spaceID, head.ReleaseID)
	return head, active, err
}

// activationMembers is shared by approval precheck, detail and activation. It never
// writes: an unchanged Head/base still validates removals through materialize. An identity
// refresh is checked against the exact active Release it names; it never rebases (PV-4a).
func (s *Service) activationMembers(
	ctx context.Context, p Principal, spaceID string, b Bundle, head Head, active Release,
) ([]Member, error) {
	refresh := b.Origin == OriginIdentityRefresh
	if err := checkBase(b, head); err != nil {
		if b.BaseReleaseID == head.ReleaseID || refresh {
			return nil, err
		}
		if err := s.checkRebase(ctx, p, spaceID, b, active); err != nil {
			return nil, err
		}
	}
	target, err := materialize(active.Members, b)
	if err == nil {
		err = checkMethodClaims(active.Members, target, b)
	}
	if err != nil || !refresh {
		return target, err
	}
	if err := s.checkIdentityRefresh(active.Members, b, target); err != nil {
		return nil, err
	}
	return target, nil
}

func (s *Service) precheckActivation(ctx context.Context, p Principal, spaceID string, c Candidate) error {
	if _, found, err := s.publishedCandidate(ctx, p, spaceID, c); found || err != nil {
		return err
	}
	b, err := s.store.BundleOf(ctx, p.TenantID, spaceID, c.ID)
	if err != nil {
		return err
	}
	head, active, err := s.activationHead(ctx, p, spaceID)
	if err != nil {
		return err
	}
	return s.precheckMembers(ctx, p, spaceID, c, b, head, active)
}

func (s *Service) precheckMembers(
	ctx context.Context, p Principal, spaceID string, c Candidate, b Bundle, head Head, active Release,
) error {
	if head.ReleaseID != "" && active.CandidateID == c.ID {
		return nil
	}
	_, err := s.activationMembers(ctx, p, spaceID, b, head, active)
	if err != nil {
		// Another approval may commit after the first lookup, even followed by
		// a different candidate. Its own publication cannot make this one stale.
		if _, found, lookupErr := s.publishedCandidate(ctx, p, spaceID, c); found || lookupErr != nil {
			return lookupErr
		}
	}
	return err
}
