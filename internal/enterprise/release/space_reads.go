package release

import "context"

// SpaceReadView reuses the configured read path with only Space-visible members.
// It never changes the original service or the publisher's stored member slice.
func (s *Service) SpaceReadView() *Service {
	if s == nil {
		return nil
	}
	view := *s
	if s.publisher != nil {
		view.publisher = spaceReadPublisher{Publisher: s.publisher}
	}
	return &view
}

type spaceReadPublisher struct{ Publisher }

func (p spaceReadPublisher) ReleaseByID(
	ctx context.Context, tenantID uint64, spaceID, releaseID string,
) (Release, error) {
	r, err := p.Publisher.ReleaseByID(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return Release{}, err
	}
	members := make([]Member, 0, len(r.Members))
	for _, m := range r.Members {
		if m.AccessScope == "space" {
			members = append(members, m)
		}
	}
	r.Members = members
	return r, nil
}
