package service

import (
	"context"
	"encoding/json"

	"github.com/Tencent/WeKnora/internal/types"
)

// The transfer is only an alternative wire encoding. It cannot declare Ready,
// replace source authority, or avoid the canonical candidate/review contract.
func (s *SchemaWikiService) CreateBatchConceptDraftTransferAutomated830G3(ctx context.Context, principal types.WikiReleasePrincipal, scope types.WikiReleaseScope, id string, raw json.RawMessage) (*types.WikiReleasePreparation, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrWikiReleaseAccessDenied
	}
	authority := s.releaseAuthority
	if _, err := authority.requireSystemPolicy(ctx, principal, scope, "create-draft"); err != nil {
		return nil, err
	}
	if err := authority.verifyAccess(ctx, principal, scope, "create-draft"); err != nil {
		return nil, err
	}
	transfer, err := types.ParseG3CandidateTransfer(raw)
	if err != nil || transfer.Base.Scope != scope {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	snapshot, err := authority.loadG3PlatformBaseSnapshot(ctx, scope, transfer.Base.ReleaseID, transfer.Base.ActivationEpoch)
	if err != nil {
		return nil, err
	}
	base := types.G3CandidateTransferBase{
		Scope: scope, ReleaseID: snapshot.ReleaseID, ActivationEpoch: snapshot.ActivationEpoch,
		CandidateSHA256: snapshot.CandidateSHA256, ManifestDigest: snapshot.ManifestDigest,
	}
	// Marshal only the four reusable collections, never the parent's model/audit
	// responses. The existing projection cache remains the sole reuse owner.
	rawMembers, err := json.Marshal(map[string]any{
		"sources":     snapshot.PublishedProjection.Sources,
		"definitions": snapshot.PublishedProjection.Definitions,
		"fields":      snapshot.PublishedProjection.Fields,
		"pages":       snapshot.PublishedProjection.Pages,
	})
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	var members map[string][]json.RawMessage
	if json.Unmarshal(rawMembers, &members) != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	candidate, err := types.ExpandG3CandidateTransfer(transfer, base, members)
	if err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	return s.CreateBatchConceptDraftAutomated830G3(ctx, principal, scope, id, candidate)
}
