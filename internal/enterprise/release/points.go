package release

import (
	"context"
	"encoding/json"
	"sort"
	"strings"
	"time"
	"unicode/utf8"
)

// ErrorMemberDecided rejects a point that already has a committed decision.
const ErrorMemberDecided = "MEMBER_DECIDED"

// PointDecision records one attributed verdict; approvals are committed with their release.
type PointDecision struct {
	ID          string    `json:"id"`
	TenantID    uint64    `json:"tenant_id"`
	SpaceID     string    `json:"space_id"`
	CandidateID string    `json:"candidate_id"`
	Slug        string    `json:"slug"`
	Outcome     string    `json:"outcome"`
	Reason      string    `json:"reason"`
	Subject     string    `json:"subject"`
	ReleaseID   string    `json:"release_id"`
	CreatedAt   time.Time `json:"created_at"`
}

// PointStore persists approvals only through Publisher.Activate; rejection is all-or-none.
type PointStore interface {
	PointDecisions(context.Context, uint64, string, string) ([]PointDecision, error)
	RejectPoints(context.Context, []PointDecision) error
}

// PointStatus is the outcome of one selected point in the current batch.
type PointStatus struct {
	Slug   string `json:"slug"`
	Status string `json:"status"`
}

// PointResult returns the aggregate candidate status and this batch publication.
type PointResult struct {
	Status    string        `json:"status"`
	ReleaseID *string       `json:"release_id"`
	Epoch     *uint64       `json:"epoch"`
	Points    []PointStatus `json:"points"`
}

// ReviewPoints publishes only a selected delta. It deliberately never enters the
// whole-candidate activation/replay path: a previous batch is not the whole bundle.
func (s *Service) ReviewPoints(
	ctx context.Context, p Principal, spaceID, id string, slugs []string, outcome, reason string,
) (PointResult, error) {
	if err := s.canReview(ctx, p, spaceID); err != nil {
		return PointResult{}, err
	}
	store, ok := s.publisher.(PointStore)
	if !ok {
		return PointResult{}, &Error{Code: ErrorServiceUnavailable, Detail: "point review is not configured"}
	}
	reason = strings.TrimSpace(reason)
	if err := validatePoints(slugs, outcome, reason); err != nil {
		return PointResult{}, err
	}
	slugs = append([]string(nil), slugs...)
	sort.Strings(slugs)
	entry, err := s.reviewEntry(ctx, p, spaceID, id)
	if err != nil {
		return PointResult{}, err
	}
	if wholeReview(entry) {
		return PointResult{}, candidateDecided()
	}
	bundle, err := s.store.BundleOf(ctx, p.TenantID, spaceID, id)
	if err != nil {
		return PointResult{}, err
	}
	if bundle.Origin == OriginIdentityRefresh {
		return PointResult{}, machineDecisionOnly() // a selected delta skips the full-target check
	}
	reads := newPointReads(s, p, spaceID)
	points, err := reads.load(ctx, entry, bundle)
	if err != nil {
		return PointResult{}, err
	}
	for _, slug := range slugs {
		if _, ok := points.kinds[slug]; !ok {
			return PointResult{}, &Error{Code: ErrorDecisionInvalid, Detail: "slug is not a review point"}
		}
	}
	// Reconcile an exact previously approved batch before rejecting decided slugs.
	var activated Release
	if outcome == "approve" {
		if replayID := points.replay(slugs); replayID != "" {
			activated, err = reads.release(ctx, replayID)
			if err != nil {
				return PointResult{}, err
			}
			return pointResult(entry, points, slugs, outcome, activated), nil
		}
	}
	for _, slug := range slugs {
		if _, ok := points.decisions[slug]; ok {
			return PointResult{}, &Error{Code: ErrorMemberDecided, Detail: "point already decided"}
		}
	}
	decisions := make([]PointDecision, 0, len(slugs))
	for _, slug := range slugs {
		decisions = append(decisions, PointDecision{
			TenantID: p.TenantID, SpaceID: spaceID, CandidateID: id,
			Slug: slug, Outcome: outcome, Reason: reason, Subject: p.Subject,
		})
	}
	if outcome == "reject" {
		err = store.RejectPoints(ctx, decisions)
	} else {
		head, active, readErr := reads.head(ctx)
		if readErr != nil {
			return PointResult{}, readErr
		}
		members, checkErr := points.materialize(slugs, active)
		if checkErr != nil {
			// A concurrent copy of this batch may have committed between the decision
			// read and Head read. Reconcile before reporting a stale delta.
			latest, readErr := s.reviewEntry(ctx, p, spaceID, id)
			if readErr != nil {
				return PointResult{}, readErr
			}
			if wholeReview(latest) {
				return PointResult{}, candidateDecided()
			}
			saved, readErr := store.PointDecisions(ctx, p.TenantID, spaceID, id)
			if readErr != nil {
				return PointResult{}, readErr
			}
			if readErr := points.setDecisions(entry.Candidate, saved); readErr != nil {
				return PointResult{}, readErr
			}
			if replayID := points.replay(slugs); replayID != "" {
				replay, readErr := reads.release(ctx, replayID)
				if readErr != nil {
					return PointResult{}, readErr
				}
				return pointResult(entry, points, slugs, outcome, replay), nil
			}
			for _, slug := range slugs {
				if _, ok := points.decisions[slug]; ok {
					return PointResult{}, &Error{Code: ErrorMemberDecided, Detail: "point already decided"}
				}
			}
			return PointResult{}, checkErr
		}
		batchRaw, _ := json.Marshal([]any{entry.Candidate.BundleDigest, slugs})
		batch := sha256Hex(string(batchRaw))
		decisionRaw, _ := json.Marshal(decisions)
		digest := sha256Hex(string(decisionRaw))
		activated, err = s.publisher.Activate(ctx, ActivationWrite{
			TenantID: p.TenantID, SpaceID: spaceID, Subject: p.Subject, CandidateID: id, BundleDigest: batch,
			Nonce: sha256Hex(id + ":" + batch), DecisionID: "points_" + digest, DecisionDigest: digest,
			Expected: head, Members: members, Points: decisions,
		})
	}
	if err != nil {
		return PointResult{}, err
	}
	saved, err := store.PointDecisions(ctx, p.TenantID, spaceID, id)
	if err != nil {
		return PointResult{}, err
	}
	if err := points.setDecisions(entry.Candidate, saved); err != nil {
		return PointResult{}, err
	}
	return pointResult(entry, points, slugs, outcome, activated), nil
}

func validatePoints(slugs []string, outcome, reason string) error {
	if len(slugs) < 1 || len(slugs) > 500 || (outcome != "approve" && outcome != "reject") ||
		reason == "" || !utf8.ValidString(reason) || utf8.RuneCountInString(reason) > 2000 {
		return &Error{Code: ErrorDecisionInvalid, Detail: "1 to 500 distinct points, outcome and reason required"}
	}
	seen := map[string]bool{}
	for _, slug := range slugs {
		if strings.TrimSpace(slug) == "" || !utf8.ValidString(slug) || seen[slug] {
			return &Error{Code: ErrorDecisionInvalid, Detail: "points must be distinct nonempty slugs"}
		}
		seen[slug] = true
	}
	return nil
}

func (s *Service) noPointDecisions(ctx context.Context, p Principal, space, id string) error {
	if store, ok := s.publisher.(PointStore); ok {
		points, err := store.PointDecisions(ctx, p.TenantID, space, id)
		if err != nil {
			return err
		}
		if len(points) > 0 {
			return candidateDecided()
		}
	}
	return nil
}

func candidateDecided() error {
	return &Error{Code: ErrorCandidateDecided, Detail: "candidate already has a decision"}
}
func wholeReview(e QueueEntry) bool { return e.Decision != nil || e.ReleaseID != "" }

func pointResult(e QueueEntry, points *reviewPoints, slugs []string, outcome string, r Release) PointResult {
	status, _, _, _ := points.state(e)
	out := PointResult{Status: status, Points: make([]PointStatus, 0, len(slugs))}
	pointStatus := "rejected"
	if outcome == "approve" {
		pointStatus = "released"
		out.ReleaseID, out.Epoch = &r.ID, &r.Epoch
	}
	for _, slug := range slugs {
		out.Points = append(out.Points, PointStatus{slug, pointStatus})
	}
	return out
}
