package release

import (
	"context"
	"errors"
)

// ActivationReceipt carries the identity of an approved decision's committed activation.
type ActivationReceipt struct {
	ID             string `json:"id"`
	Epoch          uint64 `json:"epoch"`
	BaseReleaseID  string `json:"base_release_id"`
	CandidateID    string `json:"candidate_id"`
	DecisionID     string `json:"decision_id"`
	DecisionDigest string `json:"decision_digest"`
}

type activationReceiptReader interface {
	ActivationByNonce(ctx context.Context, tenantID uint64, spaceID, nonce, decisionDigest string) (Release, error)
}

// ActivateReceipt uses the same transaction and complete readback as Activate.
func (s *Service) ActivateReceipt(
	ctx context.Context, p Principal, spaceID, candidateID, decisionID string,
) (ActivationReceipt, error) {
	r, err := s.Activate(ctx, p, spaceID, candidateID, decisionID)
	if err != nil {
		return ActivationReceipt{}, err
	}
	decision, err := s.publisher.DecisionByID(ctx, p.TenantID, spaceID, decisionID)
	if err != nil {
		return ActivationReceipt{}, err
	}
	return activationReceipt(r, decision, p, spaceID, candidateID, decisionID)
}

// ActivationReceipt reads the original decision's durable receipt independently of the Head.
func (s *Service) ActivationReceipt(
	ctx context.Context, p Principal, spaceID, candidateID, decisionID string,
) (ActivationReceipt, error) {
	if err := s.canPublish(p, spaceID); err != nil {
		return ActivationReceipt{}, err
	}
	c, err := s.store.CandidateByID(ctx, p.TenantID, spaceID, candidateID)
	if err != nil {
		return ActivationReceipt{}, err
	}
	if err := checkCandidateAccess(c, p, spaceID); err != nil {
		return ActivationReceipt{}, err
	}
	d, err := s.publisher.DecisionByID(ctx, p.TenantID, spaceID, decisionID)
	if err != nil {
		return ActivationReceipt{}, err
	}
	if c.ID != candidateID || c.BundleDigest == "" || d.BundleDigest != c.BundleDigest ||
		!activationDecisionMatches(d, p, spaceID, candidateID, decisionID) {
		return ActivationReceipt{}, &Error{
			Code: ErrorDecisionNotFound, Detail: "decision does not belong to this candidate",
		}
	}
	if d.Outcome != "approve" {
		return ActivationReceipt{}, &Error{Code: ErrorCandidateNotApproved, Detail: "candidate is not approved"}
	}
	reader, ok := s.publisher.(activationReceiptReader)
	if !ok {
		return ActivationReceipt{}, &Error{
			Code: ErrorServiceUnavailable, Detail: "activation receipt lookup is unavailable",
		}
	}
	r, err := reader.ActivationByNonce(ctx, p.TenantID, spaceID, activationNonce(c.ID, d.Digest), d.Digest)
	if err != nil {
		return ActivationReceipt{}, err
	}
	return activationReceipt(r, d, p, spaceID, candidateID, decisionID)
}

func activationNonce(candidateID, decisionDigest string) string {
	return sha256Hex(candidateID + ":" + decisionDigest)
}

func activationDecisionMatches(d Decision, p Principal, spaceID, candidateID, decisionID string) bool {
	return d.ID == decisionID && d.CandidateID == candidateID && d.TenantID == p.TenantID &&
		d.SpaceID == spaceID && d.Digest != ""
}

func activationReceipt(
	r Release, d Decision, p Principal, spaceID, candidateID, decisionID string,
) (ActivationReceipt, error) {
	if !activationDecisionMatches(d, p, spaceID, candidateID, decisionID) || d.Outcome != "approve" ||
		r.ID == "" || r.Epoch == 0 || r.CandidateID != candidateID {
		return ActivationReceipt{}, errors.New("invalid activation identity")
	}
	if r.DecisionDigest != d.Digest {
		return ActivationReceipt{}, &Error{
			Code: ErrorReleaseConflict, Detail: "release belongs to a different decision",
		}
	}
	return ActivationReceipt{
		ID: r.ID, Epoch: r.Epoch, BaseReleaseID: r.BaseReleaseID, CandidateID: r.CandidateID,
		DecisionID: d.ID, DecisionDigest: d.Digest,
	}, nil
}
