package release

import (
	"context"
	"strings"
)

// Limits and the corresponding public code for fixed-version reads.
const (
	MaxMemberIndex        = 20000
	MaxMemberLookup       = 256
	MaxMemberReadBytes    = 8 << 20
	ErrorReleaseReadLimit = "RELEASE_READ_LIMIT"
)

type memberReader interface {
	ReleaseSummary(context.Context, uint64, string) (Release, error)
	MemberIndex(context.Context, uint64, string, string) (Release, []Member, error)
	LookupMembers(context.Context, uint64, string, string, []string) (Release, []Member, error)
}

func (s *Service) memberReader(p Principal, spaceID string) (memberReader, error) {
	if err := s.canPublish(p, spaceID); err != nil {
		return nil, err
	}
	reader, ok := s.publisher.(memberReader)
	if !ok {
		return nil, &Error{Code: ErrorServiceUnavailable, Detail: "fixed release reads are unavailable"}
	}
	return reader, nil
}

// ActiveSummary resolves the Space's current published version without member bodies.
func (s *Service) ActiveSummary(ctx context.Context, p Principal, spaceID string) (Release, error) {
	r, err := s.memberReader(p, spaceID)
	if err != nil {
		return Release{}, err
	}
	return r.ReleaseSummary(ctx, p.TenantID, spaceID)
}

// FixedMemberIndex returns the validated, body-free index of one explicit version.
func (s *Service) FixedMemberIndex(ctx context.Context, p Principal, spaceID, id string) (Release, []Member, error) {
	if id == "" || id == "active" {
		return Release{}, nil, invalidMemberRead()
	}
	r, err := s.memberReader(p, spaceID)
	if err != nil {
		return Release{}, nil, err
	}
	return r.MemberIndex(ctx, p.TenantID, spaceID, id)
}

// FixedMemberLookup returns bodies only for the requested keys in one explicit version.
func (s *Service) FixedMemberLookup(
	ctx context.Context, p Principal, spaceID, id string, slugs []string,
) (Release, []Member, error) {
	if id == "" || id == "active" || len(slugs) == 0 || len(slugs) > MaxMemberLookup {
		return Release{}, nil, invalidMemberRead()
	}
	seen := make(map[string]bool, len(slugs))
	for _, slug := range slugs {
		if strings.TrimSpace(slug) == "" || strings.ContainsRune(slug, 0) || seen[slug] {
			return Release{}, nil, invalidMemberRead()
		}
		seen[slug] = true
	}
	r, err := s.memberReader(p, spaceID)
	if err != nil {
		return Release{}, nil, err
	}
	return r.LookupMembers(ctx, p.TenantID, spaceID, id, slugs)
}

func invalidMemberRead() *Error {
	return &Error{Code: ErrorInvalidRequest, Detail: "invalid fixed release member request"}
}

// MemberReadLimit reports a bounded-read refusal without exposing content.
func MemberReadLimit() *Error {
	return &Error{Code: ErrorReleaseReadLimit, Detail: "fixed release read exceeds its budget"}
}
