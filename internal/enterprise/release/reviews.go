package release

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sort"
	"strings"
	"time"
	"unicode/utf8"
)

// ErrorCandidateDecided refuses a new decision on a terminal review candidate.
const ErrorCandidateDecided = "CANDIDATE_DECIDED"

// QueueEntry is one candidate with its read-time status and latest decision.
type QueueEntry struct {
	Candidate Candidate
	CreatedAt time.Time
	CreatedBy string
	Decision  *Decision
	ReleaseID string
}

// QueueStore isolates candidates, decisions and releases by tenant and Space.
// Pending returns all entries oldest first; decided returns newest first up to limit.
type QueueStore interface {
	Queue(ctx context.Context, tenantID uint64, spaceID, status string, limit int) ([]QueueEntry, error)
}

// ReviewDecision is the browser view of an attributed decision.
type ReviewDecision struct {
	DecisionID string    `json:"decision_id"`
	Outcome    string    `json:"outcome"`
	Mode       string    `json:"mode"`
	Reason     string    `json:"reason"`
	Subject    string    `json:"subject"`
	CreatedAt  time.Time `json:"created_at"`
}

// ReviewSummary contains only the candidate metadata needed by the review list.
type ReviewSummary struct {
	CandidateID   string          `json:"candidate_id"`
	CreatedAt     time.Time       `json:"created_at"`
	CreatedBy     string          `json:"created_by"`
	BaseReleaseID string          `json:"base_release_id"`
	Status        string          `json:"status"`
	Subjects      []string        `json:"subjects"`
	Members       int             `json:"members"`
	Removals      int             `json:"removals"`
	Decision      *ReviewDecision `json:"decision"`
	ReleaseID     *string         `json:"release_id"`
}

// ReviewDetail adds the unchanged bundle and the current activation blocker.
type ReviewDetail struct {
	ReviewSummary
	HeadReleaseID  *string  `json:"head_release_id"`
	Blocker        string   `json:"blocker"`
	BundleMembers  []Member `json:"bundle_members"`
	BundleRemovals []string `json:"bundle_removals"`
}

// ReviewResult describes a human rejection or a successful activation.
type ReviewResult struct {
	DecisionID string  `json:"decision_id"`
	Status     string  `json:"status"`
	ReleaseID  *string `json:"release_id"`
	Epoch      *uint64 `json:"epoch"`
}

// ReviewQueue lists a Space's pending candidates or its latest 100 decided candidates.
func (s *Service) ReviewQueue(ctx context.Context, p Principal, spaceID, status string) ([]ReviewSummary, error) {
	if err := s.canReview(ctx, p, spaceID); err != nil {
		return nil, err
	}
	if status != "pending" && status != "decided" {
		return nil, &Error{Code: ErrorDecisionInvalid, Detail: "status must be pending or decided"}
	}
	entries, err := s.queue.Queue(ctx, p.TenantID, spaceID, status, 100)
	if err != nil {
		return nil, err
	}
	items := make([]ReviewSummary, 0, len(entries))
	for _, entry := range entries {
		if err := reviewEntryAccess(entry, p, spaceID); err != nil {
			return nil, err
		}
		bundle, err := s.store.BundleOf(ctx, p.TenantID, spaceID, entry.Candidate.ID)
		if err != nil {
			return nil, err
		}
		item, err := reviewSummary(entry, bundle)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, nil
}

// ReviewCandidate reads any candidate, independently of the decided-list display limit.
func (s *Service) ReviewCandidate(ctx context.Context, p Principal, spaceID, id string) (ReviewDetail, error) {
	entry, err := s.reviewEntry(ctx, p, spaceID, id)
	if err != nil {
		return ReviewDetail{}, err
	}
	bundle, err := s.store.BundleOf(ctx, p.TenantID, spaceID, id)
	if err != nil {
		return ReviewDetail{}, err
	}
	summary, err := reviewSummary(entry, bundle)
	if err != nil {
		return ReviewDetail{}, err
	}
	head, err := s.store.Head(ctx, p.TenantID, spaceID)
	if err != nil {
		return ReviewDetail{}, err
	}
	detail := ReviewDetail{
		ReviewSummary: summary, HeadReleaseID: optionalString(head.ReleaseID),
		BundleMembers: bundle.Members, BundleRemovals: bundle.Removals,
	}
	if entry.Candidate.Status == "rejected" || entry.Candidate.Status == "released" {
		detail.Blocker = ErrorCandidateDecided
		return detail, nil
	}
	if err := checkBase(bundle, head); err != nil {
		if bundle.BaseReleaseID != head.ReleaseID {
			var active Release
			if head.ReleaseID != "" {
				active, err = s.publisher.ReleaseByID(ctx, p.TenantID, spaceID, head.ReleaseID)
				if err != nil {
					return ReviewDetail{}, err
				}
			}
			err = s.checkRebase(ctx, p, spaceID, bundle, active)
		}
		var failure *Error
		if errors.As(err, &failure) && failure.Code == ErrorNeedsRebase {
			detail.Blocker = ErrorNeedsRebase
		} else if err != nil {
			return ReviewDetail{}, err
		}
	}
	return detail, nil
}

// Review records a human decision, then delegates approval to the existing activation authority.
// A failed activation keeps its decision; another approve reuses that latest decision.
func (s *Service) Review(
	ctx context.Context, p Principal, spaceID, id, outcome, reason string,
) (ReviewResult, error) {
	if err := s.canReview(ctx, p, spaceID); err != nil {
		return ReviewResult{}, err
	}
	reason = strings.TrimSpace(reason)
	if (outcome != "approve" && outcome != "reject") || reason == "" || utf8.RuneCountInString(reason) > 2000 {
		return ReviewResult{}, &Error{
			Code: ErrorDecisionInvalid, Detail: "outcome and a reason of 1 to 2000 characters required",
		}
	}
	entry, err := s.reviewEntry(ctx, p, spaceID, id)
	if err != nil {
		return ReviewResult{}, err
	}
	var decided Decision
	switch entry.Candidate.Status {
	case "pending":
		decided, err = s.Decide(ctx, p, spaceID, id, DecisionInput{Outcome: outcome, Mode: "human", Reason: reason})
		if err != nil {
			return ReviewResult{}, err
		}
	case "approved":
		if outcome != "approve" {
			return ReviewResult{}, &Error{Code: ErrorCandidateDecided, Detail: "candidate already has a decision"}
		}
		decided = *entry.Decision
	default:
		return ReviewResult{}, &Error{Code: ErrorCandidateDecided, Detail: "candidate already has a decision"}
	}
	result := ReviewResult{DecisionID: decided.ID, Status: "rejected"}
	if outcome == "approve" {
		activated, err := s.Activate(ctx, p, spaceID, id, decided.ID)
		if err != nil {
			return ReviewResult{}, err
		}
		result.Status, result.ReleaseID, result.Epoch = "released", &activated.ID, &activated.Epoch
	}
	return result, nil
}

func (s *Service) canReview(ctx context.Context, p Principal, spaceID string) error {
	if err := checkAccess(p, spaceID); err != nil {
		return err
	}
	if s == nil || s.queue == nil || s.store == nil || s.publisher == nil {
		return &Error{Code: ErrorServiceUnavailable, Detail: "candidate review is not configured"}
	}
	return ctx.Err()
}

func (s *Service) reviewEntry(ctx context.Context, p Principal, spaceID, id string) (QueueEntry, error) {
	if err := s.canReview(ctx, p, spaceID); err != nil {
		return QueueEntry{}, err
	}
	candidate, err := s.store.CandidateByID(ctx, p.TenantID, spaceID, id)
	if err != nil {
		return QueueEntry{}, err
	}
	if candidate.ID != id || checkCandidateAccess(candidate, p, spaceID) != nil {
		return QueueEntry{}, &Error{Code: ErrorCandidateNotFound, Detail: "no such candidate in this Space"}
	}
	// QueueStore's frozen interface only filters by status. The public list caps decided
	// at 100, but locating an explicitly named old candidate must not use that display cap.
	for _, status := range []string{"pending", "decided"} {
		entries, err := s.queue.Queue(ctx, p.TenantID, spaceID, status, math.MaxInt)
		if err != nil {
			return QueueEntry{}, err
		}
		for _, entry := range entries {
			if entry.Candidate.ID == id {
				return entry, reviewEntryAccess(entry, p, spaceID)
			}
		}
	}
	return QueueEntry{}, &Error{Code: ErrorCandidateNotFound, Detail: "no such candidate in this Space"}
}

func reviewEntryAccess(entry QueueEntry, p Principal, spaceID string) error {
	c := entry.Candidate
	if checkCandidateAccess(c, p, spaceID) != nil {
		return &Error{Code: ErrorCandidateNotFound, Detail: "no such candidate in this Space"}
	}
	if d := entry.Decision; d != nil {
		if d.TenantID != p.TenantID || d.SpaceID != spaceID ||
			d.CandidateID != c.ID || d.BundleDigest != c.BundleDigest {
			return errors.New("review store returned an inconsistent decision")
		}
	}
	if c.Status == "approved" && (entry.Decision == nil || entry.Decision.Outcome != "approve") {
		return errors.New("review store returned an inconsistent approval")
	}
	return nil
}

func reviewSummary(entry QueueEntry, bundle Bundle) (ReviewSummary, error) {
	subjects := map[string]bool{}
	for _, member := range bundle.Members {
		if member.Kind != "claim" {
			continue
		}
		var claim map[string]any
		if err := json.Unmarshal(member.Payload, &claim); err != nil {
			return ReviewSummary{}, errors.New("stored claim cannot be read")
		}
		if subject, ok := claim["subject_ref"].(string); ok && subject != "" {
			subjects[subject] = true
		}
	}
	item := ReviewSummary{
		CandidateID: entry.Candidate.ID, CreatedAt: entry.CreatedAt, CreatedBy: entry.CreatedBy,
		BaseReleaseID: entry.Candidate.BaseReleaseID, Status: entry.Candidate.Status,
		Subjects: make([]string, 0, len(subjects)), Members: len(bundle.Members), Removals: len(bundle.Removals),
		ReleaseID: optionalString(entry.ReleaseID),
	}
	for subject := range subjects {
		item.Subjects = append(item.Subjects, subject)
	}
	sort.Strings(item.Subjects)
	if d := entry.Decision; d != nil {
		item.Decision = &ReviewDecision{d.ID, d.Outcome, d.Mode, d.Reason, d.Subject, d.CreatedAt}
	}
	return item, nil
}

func optionalString(value string) *string {
	if value == "" {
		return nil
	}
	return &value
}
