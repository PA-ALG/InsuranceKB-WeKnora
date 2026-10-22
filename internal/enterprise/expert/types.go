// Package expert records expert revisions of published claims and publishes them (S9a).
//
// An edit is validated against the Active release, stored as an immutable revision record,
// and published at once through the release service as an expert_edit candidate whose claim
// cites the record (EXPERT_REVISION) and carries expert_lock. The package only manipulates
// the generic claim contract fields; it knows no insurance terms.
package expert

import (
	"context"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// Error codes specific to expert edits; other failures use the release package codes.
const (
	ErrorStale   = "EXPERT_EDIT_STALE"
	ErrorInvalid = "EXPERT_EDIT_INVALID"
)

// MaxReasonRunes bounds the free-text reason an expert gives for an edit.
const MaxReasonRunes = 2000

// Value is a claim's state and value before or after an edit.
type Value struct {
	State string `json:"state"`
	Value any    `json:"value"`
}

// Revision is one immutable expert revision record.
type Revision struct {
	ID               string
	TenantID         uint64
	SpaceID          string
	BaseReleaseID    string
	MemberSlug       string
	BaseMemberDigest string
	Actor            string
	Role             string
	RecordedAt       time.Time
	Before           Value
	After            Value
	Reason           string
	RecordSHA256     string
}

// Store persists revision records. Records are never updated or deleted. RevisionByID must
// isolate by tenant and Space and return a *release.Error with ErrorEvidenceNotFound when the
// record does not exist in that scope.
type Store interface {
	CreateRevision(ctx context.Context, r Revision) error
	RevisionByID(ctx context.Context, tenantID uint64, spaceID, id string) (Revision, error)
}

// EditInput is one expert edit of a claim of the Active release.
type EditInput struct {
	BaseReleaseID    string `json:"base_release_id"`
	MemberSlug       string `json:"member_slug"`
	BaseMemberDigest string `json:"base_member_digest"`
	State            string `json:"state"`
	Value            string `json:"value"`
	Reason           string `json:"reason"`
}

// Result is the release an edit produced and the revision record it cites.
type Result struct {
	Release  release.Release
	Revision Revision
}

func failure(code, detail string) error { return &release.Error{Code: code, Detail: detail} }
