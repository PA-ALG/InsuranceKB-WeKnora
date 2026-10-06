// Package release receives generic candidate bundles and previews their delta.
// Persistence and evidence verification are supplied by the platform adapter.
package release

import (
	"context"
	"encoding/json"
)

const (
	SupportedContractVersion = "1"
	MaxBundleBytes           = 2 << 20
	ErrorCandidateInvalid    = "CANDIDATE_INVALID"
	ErrorCandidateNotFound   = "CANDIDATE_NOT_FOUND"
	ErrorReleaseAccessDenied = "RELEASE_ACCESS_DENIED"
)

// Principal is the identity resolved by the platform's authentication layer.
type Principal struct {
	TenantID uint64
	Subject  string
}

// Scope carries the explicit service identity to injected adapters. Evidence
// resolvers must use this scope, rather than trusting tenant IDs in a reference.
type Scope struct {
	Principal Principal
	SpaceID   string
}

type scopeKey struct{}

// ScopeFromContext returns the request scope attached by Receive or Preview.
func ScopeFromContext(ctx context.Context) (Scope, bool) {
	scope, ok := ctx.Value(scopeKey{}).(Scope)
	return scope, ok
}

// Member is a generic content-addressed record with opaque payload and scope.
type Member struct {
	Kind         string          `json:"kind"`
	LogicalSlug  string          `json:"logical_slug"`
	Payload      json.RawMessage `json:"payload"`
	MemberDigest string          `json:"member_digest"`
	EvidenceRefs []string        `json:"evidence_refs,omitempty"`
	AccessScope  string          `json:"access_scope"`
}

// Bundle retains the submitted contract and its governance metadata.
type Bundle struct {
	// RawJSON is the validated original document. Adapters persist these bytes
	// to retain omitted/null fields and the exact input bound by BundleDigest.
	RawJSON          json.RawMessage   `json:"-"`
	ContractVersion  string            `json:"contract_version"`
	BaseReleaseID    string            `json:"base_release_id"`
	BaseEpoch        *json.Number      `json:"base_epoch"`
	Origin           string            `json:"origin"`
	Members          []Member          `json:"members"`
	Removals         []string          `json:"removals"`
	ReviewPlan       []json.RawMessage `json:"review_plan"`
	CompilerIdentity string            `json:"compiler_identity"`
}

// Candidate is the stable metadata view of a stored submission.
type Candidate struct {
	ID              string `json:"id"`
	SpaceID         string `json:"space_id"`
	TenantID        uint64 `json:"tenant_id"`
	ContractVersion string `json:"contract_version"`
	BundleDigest    string `json:"bundle_digest"`
	BaseReleaseID   string `json:"base_release_id"`
	Status          string `json:"status"`
}

// Head identifies the active release observed during preview.
type Head struct {
	ReleaseID string
	Epoch     uint64
}

// Delta partitions the resulting members into lexically sorted slug lists.
type Delta struct {
	Added     []string `json:"added"`
	Changed   []string `json:"changed"`
	Removed   []string `json:"removed"`
	Unchanged []string `json:"unchanged"`
}

// Preview describes a candidate relative to the observed active release.
type Preview struct {
	CandidateID   string `json:"candidate_id"`
	BaseReleaseID string `json:"base_release_id"`
	HeadReleaseID string `json:"head_release_id"`
	NeedsRebase   bool   `json:"needs_rebase"`
	Delta         Delta  `json:"delta"`
}

// Error is a typed, caller-safe failure of validation, lookup or access checks.
type Error struct{ Code, Detail string }

func (e *Error) Error() string { return e.Code + ": " + e.Detail }

// Store must isolate all records by tenant and Space. CreateCandidate atomically
// stores the complete bundle and deduplicates by (tenant, Space, BundleDigest),
// including concurrent submissions. It must never deduplicate across scopes.
// Missing candidates return ErrorCandidateNotFound. Head returns an empty Head
// only if no release is active, not when a storage operation fails.
type Store interface {
	CreateCandidate(ctx context.Context, c Candidate, b Bundle) (Candidate, error)
	CandidateByID(ctx context.Context, tenantID uint64, spaceID, id string) (Candidate, error)
	BundleOf(ctx context.Context, tenantID uint64, spaceID, candidateID string) (Bundle, error)
	Head(ctx context.Context, tenantID uint64, spaceID string) (Head, error)
	MembersOf(ctx context.Context, tenantID uint64, spaceID, releaseID string) (map[string]string, error)
}

// EvidenceResolver verifies both existence and quote hash. The adapter must
// enforce the authenticated request's access scope; a missing or inaccessible
// reference returns false. Any resolution error rejects the entire bundle.
type EvidenceResolver interface {
	Resolve(ctx context.Context, ref string) (bool, error)
}
