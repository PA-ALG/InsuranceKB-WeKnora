// Package spotcheck records samples of immutable release members and their
// append-only verdicts without interpreting member payloads or sampling strata.
package spotcheck

import (
	"context"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const (
	// ErrorSampleInvalid identifies an invalid sample batch or list filter.
	ErrorSampleInvalid = "SAMPLE_INVALID"
	// ErrorSampleNotFound hides missing samples and samples outside the caller's access.
	ErrorSampleNotFound = "SAMPLE_NOT_FOUND"
	// ErrorVerdictInvalid identifies an invalid verdict outcome or note.
	ErrorVerdictInvalid = "VERDICT_INVALID"
)

// Sample binds a selected member to its immutable release and content digest.
type Sample struct {
	ID           string    `json:"id"`
	SpaceID      string    `json:"space_id"`
	ReleaseID    string    `json:"release_id"`
	LogicalSlug  string    `json:"logical_slug"`
	MemberDigest string    `json:"member_digest"`
	Stratum      string    `json:"stratum"`
	CreatedBy    string    `json:"created_by"`
	CreatedAt    time.Time `json:"created_at"`
	Verdict      *Verdict  `json:"verdict,omitempty"`
}

// Verdict is an append-only, attributed assessment of a sample.
type Verdict struct {
	ID        string    `json:"id"`
	SampleID  string    `json:"sample_id"`
	Outcome   string    `json:"outcome"`
	Note      string    `json:"note"`
	Reviewer  string    `json:"reviewer"`
	DecidedAt time.Time `json:"decided_at"`
}

// SampleInput selects a release member and supplies its opaque sampling stratum.
type SampleInput struct{ Slug, Stratum string }

// Filter restricts samples by pending or decided status and optional release ID.
type Filter struct{ Status, ReleaseID string }

// ReleaseReader resolves releases within the caller's tenant and Space.
type ReleaseReader interface {
	Release(ctx context.Context, p release.Principal, spaceID, releaseID string) (release.Release, error)
}

// Store isolates every record by tenant and Space. Latest verdicts are selected
// by append order, independently of verdict timestamps and identifiers.
type Store interface {
	// InsertSamples preserves existing (tenant, Space, release, slug) records,
	// including concurrent inserts, and returns stored samples in input order.
	InsertSamples(ctx context.Context, tenantID uint64, samples []Sample) ([]Sample, error)
	// ListSamples includes latest verdicts and orders by CreatedAt, then ID.
	ListSamples(ctx context.Context, tenantID uint64, spaceID string, f Filter) ([]Sample, error)
	SampleByID(ctx context.Context, tenantID uint64, spaceID, id string) (Sample, bool, error)
	AppendVerdict(ctx context.Context, tenantID uint64, spaceID string, v Verdict) error
}
