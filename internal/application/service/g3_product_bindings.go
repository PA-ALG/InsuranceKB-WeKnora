package service

import (
	"context"
	"encoding/json"
	"errors"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
)

// BatchProductBindingsRead830G3 is a projection of existing immutable custody.
// There is no independently writable product registry or second serving head.
type BatchProductBindingsRead830G3 struct {
	Contract        string                            `json:"contract"`
	BindingState    string                            `json:"binding_state"`
	TenantID        uint64                            `json:"tenant_id"`
	SpaceID         string                            `json:"space_id"`
	RawKBID         string                            `json:"raw_kb_id"`
	WikiKBID        string                            `json:"wiki_kb_id"`
	PreparationID   string                            `json:"preparation_id"`
	ReleaseID       string                            `json:"release_id"`
	ActivationEpoch uint64                            `json:"activation_epoch"`
	CandidateSHA256 string                            `json:"candidate_sha256"`
	CatalogID       string                            `json:"catalog_id"`
	CatalogVersion  string                            `json:"catalog_version"`
	CatalogSHA256   string                            `json:"catalog_sha256"`
	Bindings        []types.EntityCompileBinding830G3 `json:"bindings"`
	ReadSHA256      string                            `json:"read_sha256,omitempty"`
}

// ReadBatchProductBindings830G3 reads Candidate bindings for an explicit admin
// preparation, or published bindings at the sole serving pin when ID is empty.
// New-material consumers must still verify issuer/code/version evidence; a
// display-name match never authorizes a material-version association.
func (s *SchemaWikiService) ReadBatchProductBindings830G3(
	ctx context.Context, principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope, preparationID string,
) (*BatchProductBindingsRead830G3, error) {
	if s == nil || s.releaseAuthority == nil || s.releaseAuthority.repository == nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	var preparation *types.WikiReleasePreparation
	var release *types.WikiRelease
	var members []types.WikiReleaseMemberSnapshot
	var epoch uint64
	var err error
	status := types.WikiReleasePreparationDraft
	if preparationID != "" {
		if err = requireSchemaWikiHumanAdmin(ctx, principal, scope); err != nil {
			return nil, err
		}
		if !validBatchConceptPreparationID830G3(preparationID) {
			return nil, ErrSchemaWikiPreparationInvalid
		}
		preparation, err = s.releaseAuthority.repository.GetDraftPreparation(ctx, scope, preparationID)
		if errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
			preparation, err = s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
			status = types.WikiReleasePreparationReady
		}
	} else {
		pin, pinErr := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
		if pinErr != nil {
			return nil, pinErr
		}
		members, err = s.releaseAuthority.SearchPinned(ctx, principal, pin, "")
		if err != nil {
			return nil, err
		}
		release, err = s.releaseAuthority.repository.GetRelease(ctx, scope, pin.ReleaseID())
		if err != nil {
			return nil, mapWikiReleaseRepositoryError(err)
		}
		if release == nil || release.ID != pin.ReleaseID() || release.WikiReleaseScope != scope {
			return nil, ErrSchemaWikiPreparationInvalid
		}
		preparationID = release.PreparationID
		epoch = pin.ActivationEpoch()
		status = types.WikiReleasePreparationReady
		preparation, err = s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, preparationID)
	}
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if preparation == nil || preparation.ID != preparationID {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	bundle, expected, err := validateBatchConceptPreparation830G3(preparation, status, scope)
	if err != nil {
		return nil, err
	}
	state := "CANDIDATE"
	releaseID := ""
	if release != nil {
		if release.CandidateDigest != bundle.CandidateHash ||
			release.ManifestDigest != preparation.ManifestDigest ||
			release.BaseReleaseID != preparation.ExpectedReleaseID ||
			release.BaseActivationEpoch != preparation.ExpectedActivationEpoch ||
			release.BaseActivationEpoch == ^uint64(0) ||
			epoch != release.BaseActivationEpoch+1 ||
			!conceptMemberSnapshotSetsEqual830G2(expected, members) {
			return nil, ErrSchemaWikiPreparationInvalid
		}
		state, releaseID = "PUBLISHED", release.ID
	}
	result := &BatchProductBindingsRead830G3{
		Contract: "g3-product-bindings-read.830.v1", BindingState: state,
		TenantID: scope.TenantID, SpaceID: scope.SpaceID, RawKBID: scope.RawKBID, WikiKBID: scope.WikiKBID,
		PreparationID: preparationID, ReleaseID: releaseID, ActivationEpoch: epoch,
		CandidateSHA256: bundle.CandidateHash, CatalogID: bundle.Request.Catalog.CatalogID,
		CatalogVersion: bundle.Request.Catalog.CatalogVersion,
		CatalogSHA256:  bundle.Request.Catalog.CatalogSHA256, Bindings: bundle.Request.EntityBindings,
	}
	raw, err := json.Marshal(result)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	result.ReadSHA256 = digestWikiReleaseBytes(raw)
	return result, nil
}
