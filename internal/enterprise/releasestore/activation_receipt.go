package releasestore

import (
	"context"
	"errors"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// ActivationByNonce proves a specific commit using the durable receipt and its
// fixed Release. Retiring that Release or advancing Head does not erase the receipt.
func (s *Store) ActivationByNonce(
	ctx context.Context, tenantID uint64, spaceID, nonce, decisionDigest string,
) (release.Release, error) {
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return release.Release{}, err
	}
	receipt, err := s.releases.GetReceipt(ctx, scope, nonce)
	if err != nil {
		return release.Release{}, notFound(err)
	}
	if receipt.WikiReleaseScope != scope || receipt.Nonce != nonce ||
		receipt.AuthorizationDigest != decisionDigest || receipt.ReleaseID == "" {
		return release.Release{}, errors.New("invalid committed activation receipt")
	}
	r, err := s.ReleaseByID(ctx, tenantID, spaceID, receipt.ReleaseID)
	if err != nil {
		var missing *release.Error
		if errors.As(err, &missing) && missing.Code == release.ErrorReleaseNotFound {
			return release.Release{}, errors.New("committed activation has no readable release")
		}
		return release.Release{}, err
	}
	if r.ID != receipt.ReleaseID || r.Epoch != receipt.ActivationEpoch ||
		r.BaseReleaseID != receipt.PreviousReleaseID || r.DecisionDigest != decisionDigest {
		return release.Release{}, errors.New("activation receipt differs from committed release")
	}
	return r, nil
}
