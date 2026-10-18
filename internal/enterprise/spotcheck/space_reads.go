package spotcheck

import (
	"context"
	"errors"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// SpaceReadView returns an independent service view that only lists or confirms
// members readable by a browser session. The original retains API Key access.
func (s *Service) SpaceReadView() *Service {
	if s == nil {
		return nil
	}
	view := *s
	view.spaceOnly = true
	return &view
}

// readableSamples fixes each lookup to the sample's own release and caches its
// visible members for this call only, never across requests or principals.
func (s *Service) readableSamples(
	ctx context.Context, p release.Principal, spaceID string, samples []Sample,
) ([]Sample, error) {
	byRelease := make(map[string]map[string]string)
	out := make([]Sample, 0, len(samples))
	for _, sample := range samples {
		if sample.SpaceID != spaceID || strings.TrimSpace(sample.ReleaseID) == "" ||
			strings.TrimSpace(sample.ReleaseID) == "active" {
			continue
		}
		digests, cached := byRelease[sample.ReleaseID]
		if !cached {
			r, err := s.releases.Release(ctx, p, spaceID, sample.ReleaseID)
			if err != nil {
				var typed *release.Error
				if !errors.As(err, &typed) ||
					(typed.Code != release.ErrorReleaseNotFound && typed.Code != release.ErrorReleaseAccessDenied) {
					return nil, err
				}
			}
			digests = make(map[string]string)
			if err == nil {
				for _, m := range r.Members {
					if m.AccessScope == "space" {
						digests[m.LogicalSlug] = m.MemberDigest
					}
				}
			}
			byRelease[sample.ReleaseID] = digests
		}
		// Samples bind both member identity and content. A corrupted or stale
		// digest must not let the session confirm different content.
		if digest, ok := digests[sample.LogicalSlug]; ok && digest == sample.MemberDigest {
			out = append(out, sample)
		}
	}
	return out, nil
}
