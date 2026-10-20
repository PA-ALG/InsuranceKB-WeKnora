package release

import "context"

// Reference describes the mutable header of an immutable published member set.
type Reference struct {
	ID      string
	Retired bool
}

// ReferenceReader resolves a version without fetching or decoding its members.
type ReferenceReader interface {
	ReleaseReference(context.Context, uint64, string, string) (Reference, error)
}

// ReleaseReference checks the same access boundary as Release. Publishers without
// a lightweight reader return nil, so their callers perform a normal full read.
func (s *Service) ReleaseReference(ctx context.Context, p Principal, spaceID, id string) (*Reference, error) {
	if err := s.canPublish(p, spaceID); err != nil {
		return nil, err
	}
	if s.references == nil {
		return nil, nil
	}
	ref, err := s.references.ReleaseReference(ctx, p.TenantID, spaceID, id)
	if err != nil {
		return nil, err
	}
	return &ref, nil
}
