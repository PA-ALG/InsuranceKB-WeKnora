package knowledge

import (
	"context"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

type releaseReader struct{ service *release.Service }

// NewReleaseReader keeps the release service's authorization and Space visibility
// boundary while requiring an explicit version and authenticated execution tenant.
func NewReleaseReader(service *release.Service) Reader {
	return &releaseReader{service: service.SpaceReadView()}
}

func (r *releaseReader) ReleaseByID(
	ctx context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	if err := validateRead(ctx, tenantID, spaceID, releaseID); err != nil {
		return release.Release{}, err
	}
	executingTenant, tenantOK := types.TenantIDFromContext(ctx)
	principal, principalOK := types.PrincipalFromContext(ctx)
	if !tenantOK || executingTenant != tenantID || !principalOK {
		return release.Release{}, &release.Error{
			Code: release.ErrorReleaseAccessDenied, Detail: "authenticated execution tenant and principal are required",
		}
	}
	if r == nil || r.service == nil {
		return release.Release{}, &release.Error{
			Code: release.ErrorServiceUnavailable, Detail: "release reader is unavailable",
		}
	}
	identity := release.Principal{TenantID: executingTenant, Subject: principal.StorageID()}
	value, err := r.service.Release(ctx, identity, spaceID, releaseID)
	if err != nil {
		return release.Release{}, err
	}
	if err := ctx.Err(); err != nil {
		return release.Release{}, err
	}
	if value.ID != releaseID {
		return release.Release{}, &release.Error{
			Code: release.ErrorReleaseConflict, Detail: "reader returned another release",
		}
	}
	return value, nil
}
