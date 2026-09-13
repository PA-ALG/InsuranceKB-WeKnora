package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
)

// CreateBatchConceptDraftAutomated830G3 is restricted to the explicitly enabled
// isolated policy and the actual authenticated tenant API key. It cannot create
// a human access proof, skip source checks, or manufacture a Ready preparation.
func (s *SchemaWikiService) CreateBatchConceptDraftAutomated830G3(ctx context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope, id string, raw json.RawMessage) (*types.WikiReleasePreparation, error) {
	if s == nil || s.releaseAuthority == nil {
		return nil, ErrWikiReleaseAccessDenied
	}
	authority := s.releaseAuthority
	policy, err := authority.requireSystemPolicy(ctx, p, scope, "create-draft")
	if err != nil {
		return nil, err
	}
	if err := authority.verifyAccess(ctx, p, scope, "create-draft"); err != nil {
		return nil, err
	}
	return s.createBatchConceptDraft830G3(ctx, p, scope, id, raw, func() error {
		return authority.recheckSystemPolicy(ctx, p, scope, "create-draft", policy.Digest)
	}, func(input *types.WikiReleasePreparation) (*types.WikiReleasePreparation, error) {
		return authority.createOrReplaySystemDraft(ctx, p, input, policy.Digest)
	})
}

// The HTTP response may be lost after the immutable Draft commits. Only this
// system entry allows exact request replay, after the shared source/base checks.
// It returns the original timestamp used by deterministic downstream signing.
func (s *WikiReleaseService) createOrReplaySystemDraft(ctx context.Context, p types.WikiReleasePrincipal, input *types.WikiReleasePreparation, policyDigest string) (*types.WikiReleasePreparation, error) {
	stored, err := s.repository.GetDraftPreparation(ctx, input.WikiReleaseScope, input.ID)
	if err == nil {
		return s.replaySystemDraft(ctx, p, input, stored, policyDigest)
	}
	if !errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if err := s.recheckSystemPolicy(ctx, p, input.WikiReleaseScope, "create-draft", policyDigest); err != nil {
		return nil, err
	}
	_, createErr := s.createDraftAtExpectedHead(ctx, p, input, &wikiReleaseDraftExpectedHead{
		releaseID: input.ExpectedReleaseID, activationEpoch: input.ExpectedActivationEpoch,
	})
	if createErr == nil {
		// Return database time precision on the first response as well as replay;
		// Python derives its deterministic signing timestamps from this metadata.
		stored, err = s.repository.GetDraftPreparation(ctx, input.WikiReleaseScope, input.ID)
		if err != nil {
			return nil, mapWikiReleaseRepositoryError(err)
		}
		return s.replaySystemDraft(ctx, p, input, stored, policyDigest)
	}
	// Another generation may have committed the same request between the read
	// and insert. An occupied ID is acceptable only for this exact validated Draft.
	stored, err = s.repository.GetDraftPreparation(ctx, input.WikiReleaseScope, input.ID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(createErr)
	}
	return s.replaySystemDraft(ctx, p, input, stored, policyDigest)
}

func (s *WikiReleaseService) replaySystemDraft(ctx context.Context, p types.WikiReleasePrincipal, input, stored *types.WikiReleasePreparation, policyDigest string) (*types.WikiReleasePreparation, error) {
	scope := input.WikiReleaseScope
	// JSONB and GORM's JSON serializer may reorder keys or escape HTML. The
	// existing strict canonicalizer rejects ambiguous JSON; comparing its bytes
	// to the fully validated input retains exact values, quotes and evidence.
	canonicalManifest, err := types.CanonicalConceptMemberPayload830G2(stored.Manifest)
	if err != nil || stored.Status != types.WikiReleasePreparationDraft || stored.CreatedAt.IsZero() ||
		stored.ReviewDecisionDigest != "" ||
		stored.PreparationDigest != digestWikiReleasePreparation(stored) ||
		stored.PreparationDigest != digestWikiReleasePreparation(input) ||
		!bytes.Equal(canonicalManifest, input.Manifest) ||
		!conceptMemberSnapshotsEqual830G2(stored.Members, input.Members) {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	if err := s.verifyAccess(ctx, p, scope, "create-draft"); err != nil {
		return nil, err
	}
	if err := s.verifySpaceBinding(ctx, scope); err != nil {
		return nil, err
	}
	head, err := s.repository.GetHead(ctx, scope)
	if err != nil || head == nil || head.WikiReleaseScope != scope ||
		head.ActiveReleaseID != input.ExpectedReleaseID || head.ActivationEpoch != input.ExpectedActivationEpoch {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	if err := s.recheckSystemPolicy(ctx, p, scope, "create-draft", policyDigest); err != nil {
		return nil, err
	}
	return stored, nil
}

func (s *WikiReleaseService) recheckSystemPolicy(ctx context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope, capability, digest string) error {
	policy, err := s.requireSystemPolicy(ctx, p, scope, capability)
	if err != nil {
		return err
	}
	if policy.Digest != digest {
		return ErrWikiReleaseAccessDenied
	}
	return nil
}

// ReviewDraftAutomated stores the system receipt digest in the existing Ready
// row; the compiler's inner ReviewPolicyID remains unchanged. Exact Ready replay
// is read-only, but still rechecks current policy, ACL and immutable sources.
func (s *WikiReleaseService) ReviewDraftAutomated(ctx context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope, id string, raw []byte) (*types.WikiReleasePreparation, error) {
	policy, err := s.requireSystemPolicy(ctx, p, scope, "review")
	if err != nil {
		return nil, err
	}
	if s.repository == nil {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	decision, digest, err := s.verifySystemDecision(raw, policy, false)
	if err != nil {
		return nil, err
	}
	if decision.PreparationID != id {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	if err := s.verifyAccess(ctx, p, scope, "review-draft"); err != nil {
		return nil, err
	}
	draft, err := s.repository.GetDraftPreparation(ctx, scope, id)
	if errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
		return s.replaySystemReady(ctx, p, scope, id, decision, digest, policy.Digest)
	}
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if err := validateSystemPreparation(draft, types.WikiReleasePreparationDraft, scope, decision, digest); err != nil {
		return nil, err
	}
	if err := s.verifyConceptSourceAuthority830G2(ctx, p, scope, draft, "review"); err != nil {
		return nil, err
	}
	if err := s.verifyAccess(ctx, p, scope, "review-draft"); err != nil {
		return nil, err
	}
	if err := s.recheckSystemPolicy(ctx, p, scope, "review", policy.Digest); err != nil {
		return nil, err
	}
	// Source verification can outlive the receipt. Check again at the Ready write edge.
	if decision.ExpiresAt <= s.now().Unix() {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	ready := *draft
	ready.Status = types.WikiReleasePreparationReady
	ready.ReviewDecisionDigest = digest
	ready.PreparationDigest = digestWikiReleasePreparation(&ready)
	stored, err := s.repository.ReviewDraft(ctx, scope, id, draft, digest, ready.PreparationDigest)
	if errors.Is(err, wikirepository.ErrWikiReleaseConflict) {
		return s.replaySystemReady(ctx, p, scope, id, decision, digest, policy.Digest)
	}
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	return stored, nil
}

func (s *WikiReleaseService) replaySystemReady(ctx context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope, id string, d *SystemPolicyDecisionReceiptV1, digest, policyDigest string) (*types.WikiReleasePreparation, error) {
	ready, err := s.repository.GetReadyPreparation(ctx, scope, id)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if err := validateSystemPreparation(ready, types.WikiReleasePreparationReady, scope, d, digest); err != nil {
		return nil, err
	}
	if err := s.verifyAccess(ctx, p, scope, "review-draft"); err != nil {
		return nil, err
	}
	// Existing source authority opens the Ready row for this operation. The
	// review operation deliberately only opens Draft rows.
	if err := s.verifyConceptSourceAuthority830G2(ctx, p, scope, ready, "activate"); err != nil {
		return nil, err
	}
	if err := s.recheckSystemPolicy(ctx, p, scope, "review", policyDigest); err != nil {
		return nil, err
	}
	if d.ExpiresAt <= s.now().Unix() {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	return ready, nil
}

func validateSystemPreparation(preparation *types.WikiReleasePreparation, status string, scope types.WikiReleaseScope, d *SystemPolicyDecisionReceiptV1, receiptDigest string) error {
	if _, _, err := validateBatchConceptPreparation830G3(preparation, status, scope); err != nil {
		return err
	}
	if preparation.ID != d.PreparationID || preparation.CandidateDigest != d.CandidateDigest || preparation.ManifestDigest != d.ManifestDigest ||
		preparation.ReadyReceiptDigest != d.ReadyReceiptDigest || preparation.ReviewPolicyID != d.InnerReviewPolicyID ||
		preparation.ExpectedReleaseID != d.ExpectedReleaseID || preparation.ExpectedActivationEpoch != d.ExpectedActivationEpoch {
		return ErrWikiReleaseInvalidAuthorization
	}
	draft := *preparation
	if status == types.WikiReleasePreparationReady {
		if preparation.ReviewDecisionDigest != receiptDigest {
			return ErrWikiReleaseInvalidAuthorization
		}
		draft.Status = types.WikiReleasePreparationDraft
		draft.ReviewDecisionDigest = ""
	}
	if digestWikiReleasePreparation(&draft) != d.DraftPreparationDigest {
		return ErrWikiReleaseInvalidAuthorization
	}
	return nil
}

// ActivateAutomated uses the existing PublishAuthorizationV0 and the single
// private activation transaction. A distinct system receipt never mints a
// publish authorization, and cannot substitute for the human review endpoint.
func (s *WikiReleaseService) ActivateAutomated(ctx context.Context, p types.WikiReleasePrincipal, rawDecision, rawAuthorization []byte) (*types.WikiReleaseReceipt, error) {
	auth, err := ParsePublishAuthorizationV0(rawAuthorization)
	if err != nil {
		return nil, err
	}
	canonical, err := CanonicalPublishAuthorizationV0(auth, true)
	if err != nil || !bytes.Equal(canonical, rawAuthorization) {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	scope := types.WikiReleaseScope{TenantID: auth.TenantID, SpaceID: auth.SpaceID, RawKBID: auth.RawKBID, WikiKBID: auth.WikiKBID}
	policy, err := s.requireSystemPolicy(ctx, p, scope, "activate")
	if err != nil {
		return nil, err
	}
	if s.repository == nil {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	if err := s.verifyAccess(ctx, p, scope, "activate"); err != nil {
		return nil, err
	}
	exactRetry := false
	if prior, err := s.repository.GetReceipt(ctx, scope, auth.Nonce); err == nil {
		if prior.AuthorizationDigest != digestWikiReleaseBytes(canonical) {
			return nil, &WikiReleaseConflictError{Cause: errors.New("nonce digest mismatch")}
		}
		exactRetry = true
	} else if !errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
		return nil, err
	}
	decision, digest, err := s.verifySystemDecision(rawDecision, policy, exactRetry)
	if err != nil {
		return nil, err
	}
	if auth.Action != "activate" || auth.PreparationID != decision.PreparationID || auth.Nonce != decision.Nonce || auth.ReviewDecisionDigest != digest {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	ready, err := s.repository.GetReadyPreparation(ctx, scope, auth.PreparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if err := validateSystemPreparation(ready, types.WikiReleasePreparationReady, scope, decision, digest); err != nil {
		return nil, err
	}
	if err := s.verifyConceptSourceAuthority830G2(ctx, p, scope, ready, "activate"); err != nil {
		return nil, err
	}
	if err := s.publishedBatchReuse830G3().rememberValidated(ready, scope); err != nil {
		return nil, err
	}
	if err := s.recheckSystemPolicy(ctx, p, scope, "activate", policy.Digest); err != nil {
		return nil, err
	}
	if !exactRetry && decision.ExpiresAt <= s.now().Unix() {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	return s.activate(ctx, p, rawAuthorization)
}
