package release

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Publishing failures, in addition to the receive and preview codes.
const (
	ErrorDecisionInvalid      = "DECISION_INVALID"
	ErrorDecisionNotFound     = "DECISION_NOT_FOUND"
	ErrorCandidateNotApproved = "CANDIDATE_NOT_APPROVED"
	ErrorNeedsRebase          = "NEEDS_REBASE"
	ErrorReleaseConflict      = "RELEASE_CONFLICT"
	ErrorReleaseNotFound      = "RELEASE_NOT_FOUND"
	ErrorServiceUnavailable   = "SERVICE_UNAVAILABLE"
	ErrorReleaseActive        = "RELEASE_ACTIVE"
	ErrorRetirementInvalid    = "RETIREMENT_INVALID"
	ErrorSourceUnavailable    = "SOURCE_UNAVAILABLE"
	ErrorInvalidRequest       = "INVALID_REQUEST"
)

// DecisionInput is a review outcome reported for one candidate. Quality scoring and
// thresholds belong to the compiler: the platform records which versioned policy decided.
type DecisionInput struct {
	Outcome   string `json:"outcome"`
	Mode      string `json:"mode"`
	PolicyRef string `json:"policy_ref"`
	Score     string `json:"score,omitempty"`
	Reason    string `json:"reason,omitempty"`
}

// Decision is a stored review outcome bound to the candidate's bundle digest.
type Decision struct {
	ID           string    `json:"id"`
	TenantID     uint64    `json:"tenant_id"`
	SpaceID      string    `json:"space_id"`
	CandidateID  string    `json:"candidate_id"`
	BundleDigest string    `json:"bundle_digest"`
	Outcome      string    `json:"outcome"`
	Mode         string    `json:"mode"`
	PolicyRef    string    `json:"policy_ref"`
	Score        string    `json:"score,omitempty"`
	Reason       string    `json:"reason,omitempty"`
	Subject      string    `json:"subject"`
	Digest       string    `json:"digest"`
	CreatedAt    time.Time `json:"created_at"`
}

// Release is an activated, complete set of members of one Space.
type Release struct {
	ID             string   `json:"id"`
	Epoch          uint64   `json:"epoch"`
	BaseReleaseID  string   `json:"base_release_id"`
	CandidateID    string   `json:"candidate_id"`
	DecisionDigest string   `json:"decision_digest"`
	Members        []Member `json:"members"`

	RetiredAt *time.Time `json:"retired_at,omitempty"`
}

// ActivationWrite is everything the platform needs to publish atomically: the
// complete member set and the Head the service based it on.
type ActivationWrite struct {
	TenantID       uint64
	SpaceID        string
	Subject        string
	CandidateID    string
	BundleDigest   string
	DecisionID     string
	DecisionDigest string
	Nonce          string
	Expected       Head
	Members        []Member
}

// Publisher writes and reads releases through the platform's single Head of a
// Space. SaveDecision is idempotent by (tenant, Space, Digest). Activate is a
// compare-and-swap on Expected (a moved Head is ErrorReleaseConflict) and returns
// the same release when the Nonce or (tenant, Space, BundleDigest) was already
// activated, even under another decision. Candidate lookup and Head publication
// must share one atomic transaction. ReleaseByID with an
// empty ID reads the active release; a missing one is ErrorReleaseNotFound.
type Publisher interface {
	SaveDecision(ctx context.Context, d Decision) (Decision, error)
	DecisionByID(ctx context.Context, tenantID uint64, spaceID, id string) (Decision, error)
	ReleaseByID(ctx context.Context, tenantID uint64, spaceID, releaseID string) (Release, error)
	Activate(ctx context.Context, w ActivationWrite) (Release, error)
}

// CandidateReleaseReader finds a candidate's committed release before rebase checks.
// Publishers without this read optimization still enforce candidate idempotency in Activate.
type CandidateReleaseReader interface {
	PublishedCandidate(ctx context.Context, tenantID uint64, spaceID, bundleDigest string) (Release, bool, error)
}

// Option configures optional collaborators of the Service.
type Option func(*Service)

// WithPublisher enables decisions, activation and release reads.
func WithPublisher(p Publisher) Option {
	return func(s *Service) {
		s.publisher = p
		s.references, _ = p.(ReferenceReader)
	}
}

// Decide records a review outcome for a stored candidate of the caller's Space.
func (s *Service) Decide(
	ctx context.Context, p Principal, spaceID, candidateID string, in DecisionInput,
) (Decision, error) {
	if err := s.canPublish(p, spaceID); err != nil {
		return Decision{}, err
	}
	if err := validateDecision(in); err != nil {
		return Decision{}, err
	}
	c, err := s.store.CandidateByID(ctx, p.TenantID, spaceID, candidateID)
	if err != nil {
		return Decision{}, err
	}
	if err := checkCandidateAccess(c, p, spaceID); err != nil {
		return Decision{}, err
	}
	d := Decision{
		TenantID: p.TenantID, SpaceID: spaceID, CandidateID: c.ID, BundleDigest: c.BundleDigest,
		Outcome: in.Outcome, Mode: in.Mode, PolicyRef: in.PolicyRef, Score: in.Score,
		Reason: in.Reason, Subject: p.Subject,
	}
	d.Digest = decisionDigest(d)
	saved, err := s.publisher.SaveDecision(ctx, d)
	if err != nil {
		return Decision{}, err
	}
	if saved.ID == "" || saved.Digest != d.Digest || saved.CandidateID != c.ID ||
		saved.TenantID != p.TenantID || saved.SpaceID != spaceID {
		return Decision{}, errors.New("decision store returned an inconsistent record")
	}
	return saved, nil
}

// Activate publishes an approved candidate on top of the current Head of its Space.
func (s *Service) Activate(ctx context.Context, p Principal, spaceID, candidateID, decisionID string) (Release, error) {
	if err := s.canPublish(p, spaceID); err != nil {
		return Release{}, err
	}
	c, err := s.store.CandidateByID(ctx, p.TenantID, spaceID, candidateID)
	if err != nil {
		return Release{}, err
	}
	if err := checkCandidateAccess(c, p, spaceID); err != nil {
		return Release{}, err
	}
	d, err := s.publisher.DecisionByID(ctx, p.TenantID, spaceID, decisionID)
	if err != nil {
		return Release{}, err
	}
	if d.CandidateID != c.ID || d.BundleDigest != c.BundleDigest || d.TenantID != p.TenantID || d.SpaceID != spaceID {
		return Release{}, &Error{Code: ErrorDecisionNotFound, Detail: "decision does not belong to this candidate"}
	}
	if d.Outcome != "approve" {
		return Release{}, &Error{Code: ErrorCandidateNotApproved, Detail: "decision outcome is " + d.Outcome}
	}
	if committed, ok, err := s.publishedCandidate(ctx, p, spaceID, c); ok || err != nil {
		return committed, err
	}
	head, base, err := s.activationHead(ctx, p, spaceID)
	if err != nil {
		return Release{}, err
	}
	if head.ReleaseID != "" && base.CandidateID == c.ID {
		return base, nil
	}
	b, err := s.store.BundleOf(ctx, p.TenantID, spaceID, c.ID)
	if err != nil {
		return Release{}, err
	}
	if err := checkBase(b, head); err != nil {
		if b.BaseReleaseID == head.ReleaseID {
			return Release{}, err // same base, different epoch: the reference contradicts itself
		}
		if replayed, ok, replayErr := s.replay(ctx, p, spaceID, c, d, b); ok || replayErr != nil {
			return replayed, replayErr
		}
	}
	members, err := s.activationMembers(ctx, p, spaceID, b, head, base)
	if err != nil {
		return Release{}, err
	}
	return s.publisher.Activate(ctx, s.write(p, spaceID, c, d, head, members))
}

// replay answers a retried activation whose first attempt committed before the Head moved on.
// The port answers a committed nonce before its Head CAS (Spec §3.1), so the committed release
// comes back. A candidate that never committed expects its own, older base, so the CAS fails
// against the moved Head and nothing is written; the caller then reports NEEDS_REBASE.
func (s *Service) replay(
	ctx context.Context, p Principal, spaceID string, c Candidate, d Decision, b Bundle,
) (Release, bool, error) {
	expected := Head{}
	if b.BaseReleaseID != "" {
		base, err := s.publisher.ReleaseByID(ctx, p.TenantID, spaceID, b.BaseReleaseID)
		var failure *Error
		if errors.As(err, &failure) && failure.Code == ErrorReleaseNotFound {
			return Release{}, false, nil
		}
		if err != nil {
			return Release{}, false, err
		}
		expected = Head{ReleaseID: base.ID, Epoch: base.Epoch}
	}
	r, err := s.publisher.Activate(ctx, s.write(p, spaceID, c, d, expected, b.Members))
	var failure *Error
	if errors.As(err, &failure) && failure.Code == ErrorReleaseConflict {
		return Release{}, false, nil
	}
	if err != nil {
		return Release{}, false, err
	}
	if r.CandidateID != c.ID {
		return Release{}, false, errors.New("publisher replayed a different activation")
	}
	return r, true, nil
}

func (s *Service) write(
	p Principal, spaceID string, c Candidate, d Decision, expected Head, members []Member,
) ActivationWrite {
	return ActivationWrite{
		TenantID: p.TenantID, SpaceID: spaceID, Subject: p.Subject, CandidateID: c.ID,
		BundleDigest: c.BundleDigest, DecisionID: d.ID, DecisionDigest: d.Digest,
		Nonce: sha256Hex(c.ID + ":" + d.Digest), Expected: expected, Members: members,
	}
}

// Release reads the active release (empty ID) or a named release of the Space.
func (s *Service) Release(ctx context.Context, p Principal, spaceID, releaseID string) (Release, error) {
	if err := s.canPublish(p, spaceID); err != nil {
		return Release{}, err
	}
	return s.publisher.ReleaseByID(ctx, p.TenantID, spaceID, releaseID)
}

func (s *Service) canPublish(p Principal, spaceID string) error {
	if err := checkAccess(p, spaceID); err != nil {
		return err
	}
	if s.publisher == nil || s.store == nil {
		return &Error{Code: ErrorServiceUnavailable, Detail: "publishing is not configured"}
	}
	return nil
}

func validateDecision(in DecisionInput) error {
	switch {
	case in.Outcome != "approve" && in.Outcome != "reject" && in.Outcome != "manual":
		return &Error{Code: ErrorDecisionInvalid, Detail: "outcome must be approve, reject or manual"}
	case in.Mode != "machine" && in.Mode != "human":
		return &Error{Code: ErrorDecisionInvalid, Detail: "mode must be machine or human"}
	case in.Mode == "machine" && strings.TrimSpace(in.PolicyRef) == "":
		return &Error{Code: ErrorDecisionInvalid, Detail: "a machine decision must name its versioned policy"}
	}
	if in.Score != "" {
		score, err := strconv.ParseFloat(in.Score, 64)
		if err != nil || math.IsNaN(score) || math.IsInf(score, 0) {
			return &Error{Code: ErrorDecisionInvalid, Detail: "score must be a finite number"}
		}
	}
	return nil
}

// checkRebase allows a candidate built on an older release onto the current Head only when
// the Head has not touched any slug the candidate touches (S8b): each touched slug has the
// same digest in the candidate's base and in the Head, or is absent from both. The delta
// is then applied to the Head's members under the usual CAS. Anything else needs a rebase.
func (s *Service) checkRebase(ctx context.Context, p Principal, spaceID string, b Bundle, head Release) error {
	var baseMembers []Member
	if b.BaseReleaseID != "" {
		older, err := s.publisher.ReleaseByID(ctx, p.TenantID, spaceID, b.BaseReleaseID)
		var failure *Error
		if errors.As(err, &failure) && failure.Code == ErrorReleaseNotFound {
			return &Error{Code: ErrorNeedsRebase, Detail: "candidate base release is unknown"}
		}
		if err != nil {
			return err
		}
		baseMembers = older.Members
	}
	before, now := digestsBySlug(baseMembers), digestsBySlug(head.Members)
	touched := make([]string, 0, len(b.Members)+len(b.Removals))
	for _, m := range b.Members {
		touched = append(touched, m.LogicalSlug)
	}
	touched = append(touched, b.Removals...)
	conflicts := 0
	for _, slug := range touched {
		if before[slug] != now[slug] {
			conflicts++
		}
	}
	if conflicts > 0 {
		return &Error{Code: ErrorNeedsRebase, Detail: fmt.Sprintf(
			"the active release changed %d member(s) this candidate touches", conflicts)}
	}
	return nil
}

func digestsBySlug(members []Member) map[string]string {
	out := make(map[string]string, len(members))
	for _, m := range members {
		out[m.LogicalSlug] = m.MemberDigest
	}
	return out
}

// checkBase requires the candidate to be built on exactly the current Head.
func checkBase(b Bundle, head Head) error {
	if b.BaseReleaseID != head.ReleaseID {
		return &Error{Code: ErrorNeedsRebase, Detail: "candidate is based on another release than the active one"}
	}
	if b.BaseEpoch != nil {
		epoch, err := strconv.ParseUint(b.BaseEpoch.String(), 10, 64)
		if err != nil || epoch != head.Epoch {
			return &Error{Code: ErrorNeedsRebase, Detail: "candidate base epoch is not the active epoch"}
		}
	}
	return nil
}

// materialize applies a delta bundle to the base members: removals, then
// replacements and additions; the result is sorted by logical slug.
func materialize(base []Member, b Bundle) ([]Member, error) {
	bySlug := make(map[string]Member, len(base)+len(b.Members))
	for _, m := range base {
		bySlug[m.LogicalSlug] = m
	}
	for _, slug := range b.Removals {
		if _, ok := bySlug[slug]; !ok {
			return nil, invalid("removal names a member the active release does not have: " + slug)
		}
		delete(bySlug, slug)
	}
	for _, m := range b.Members {
		bySlug[m.LogicalSlug] = m
	}
	out := make([]Member, 0, len(bySlug))
	for _, m := range bySlug {
		out = append(out, m)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].LogicalSlug < out[j].LogicalSlug })
	return out, nil
}

func decisionDigest(d Decision) string {
	// Field order is fixed by the struct; the stored ID is not part of the content.
	raw, _ := json.Marshal(struct {
		CandidateID  string `json:"candidate_id"`
		BundleDigest string `json:"bundle_digest"`
		Outcome      string `json:"outcome"`
		Mode         string `json:"mode"`
		PolicyRef    string `json:"policy_ref"`
		Score        string `json:"score"`
		Reason       string `json:"reason"`
		Subject      string `json:"subject"`
	}{d.CandidateID, d.BundleDigest, d.Outcome, d.Mode, d.PolicyRef, d.Score, d.Reason, d.Subject})
	return sha256Hex(string(raw))
}

func sha256Hex(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}

// MemberDigest recomputes a member digest with the receive-time contract, so adapters
// can verify payload bytes read back from storage.
func MemberDigest(payload json.RawMessage) (string, error) {
	var value any
	if err := json.Unmarshal(payload, &value); err != nil {
		return "", err
	}
	return canonicalDigest(value), nil
}
