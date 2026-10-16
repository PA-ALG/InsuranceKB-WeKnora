package release

import (
	"context"
	"strings"
	"time"
	"unicode/utf8"
)

// Retirement removes a non-active release from the set of rollback targets.
type Retirement struct {
	ReleaseID string    `json:"release_id"`
	Reason    string    `json:"reason"`
	Subject   string    `json:"subject"`
	RetiredAt time.Time `json:"retired_at"`
}

// SourcePin identifies one non-retired release citing an exact parse attempt.
type SourcePin struct {
	ReleaseID    string `json:"release_id"`
	ParseAttempt int64  `json:"parse_attempt"`
	Active       bool   `json:"active"`
}

// RetirementWrite carries the authenticated scope and administrator's reason.
type RetirementWrite struct {
	TenantID  uint64
	SpaceID   string
	ReleaseID string
	Reason    string
	Subject   string
}

// Retirer must check the active Head again inside its transaction, and return
// the original record on a repeated retirement.
type Retirer interface {
	Retire(context.Context, RetirementWrite) (Retirement, error)
	SourcePins(context.Context, uint64, string, string) ([]SourcePin, error)
}

// WithRetirer enables retirement and source pin queries.
func WithRetirer(r Retirer) Option { return func(s *Service) { s.retirer = r } }

func (s *Service) canRetire(p Principal, spaceID string) error {
	if err := s.canPublish(p, spaceID); err != nil {
		return err
	}
	if s.retirer == nil {
		return &Error{Code: ErrorServiceUnavailable, Detail: "retirement is not configured"}
	}
	return nil
}

// Retire removes an older release from the rollback set after access checks.
func (s *Service) Retire(
	ctx context.Context, p Principal, spaceID, releaseID, reason string,
) (Retirement, error) {
	if err := s.canRetire(p, spaceID); err != nil {
		return Retirement{}, err
	}
	if strings.TrimSpace(releaseID) == "" {
		return Retirement{}, &Error{Code: ErrorReleaseNotFound, Detail: "release_id is required"}
	}
	reason = strings.TrimSpace(reason)
	if reason == "" || utf8.RuneCountInString(reason) > 500 {
		return Retirement{}, &Error{Code: ErrorRetirementInvalid, Detail: "reason must contain 1 to 500 characters"}
	}
	head, err := s.store.Head(ctx, p.TenantID, spaceID)
	if err != nil {
		return Retirement{}, err
	}
	if head.ReleaseID == releaseID {
		return Retirement{}, &Error{Code: ErrorReleaseActive, Detail: "the active release cannot be retired"}
	}
	return s.retirer.Retire(ctx, RetirementWrite{
		TenantID: p.TenantID, SpaceID: spaceID, ReleaseID: releaseID, Reason: reason, Subject: p.Subject,
	})
}

// SourcePins lists the releases preventing deletion of a knowledge.
func (s *Service) SourcePins(
	ctx context.Context, p Principal, spaceID, knowledgeID string,
) ([]SourcePin, error) {
	if err := s.canRetire(p, spaceID); err != nil {
		return nil, err
	}
	if strings.TrimSpace(knowledgeID) == "" {
		return nil, &Error{Code: ErrorInvalidRequest, Detail: "knowledge_id is required"}
	}
	return s.retirer.SourcePins(ctx, p.TenantID, spaceID, knowledgeID)
}
