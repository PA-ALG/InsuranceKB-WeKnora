// Package memberstore persists complete release snapshots without changing business identity.
package memberstore

import (
	"errors"
	"sync"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

var (
	// ErrIntegrity indicates damaged or mismatched immutable storage.
	ErrIntegrity = errors.New("member storage integrity failure")
	// ErrState indicates an invalid migration phase or incomplete observation.
	ErrState = errors.New("member storage state conflict")
)

// Store implements the repository's member storage port. It owns no Head or serving authority.
type Store struct {
	memoMu sync.Mutex
	memo   *writeMemo
	verify HistoryVerifier
}

// HistoryVerifier validates the owner protocol without coupling storage to its producer.
type HistoryVerifier func(types.WikiRelease, types.WikiReleasePreparation, []types.WikiReleaseMemberSnapshot) error

// New constructs a storage adapter. A verifier is mandatory for certification/cleanup.
func New(verifier ...HistoryVerifier) *Store {
	s := &Store{}
	if len(verifier) == 1 {
		s.verify = verifier[0]
	}
	return s
}

type scopeRow struct {
	ID int64 `gorm:"column:id;primaryKey"`
	types.WikiReleaseScope
	Mode                     string     `gorm:"column:mode"`
	ObservationStartedAt     *time.Time `gorm:"column:observation_started_at"`
	ObservationWindowSeconds int64      `gorm:"column:observation_window_seconds;default:604800"`
	ReadFailures             int64      `gorm:"column:read_failures"`
}

func (scopeRow) TableName() string { return "enterprise_member_scopes" }

type contentRow struct {
	ScopeID      int64  `gorm:"column:scope_id;primaryKey"`
	Digest       []byte `gorm:"column:digest;primaryKey"`
	Codec        int    `gorm:"column:codec"`
	Kind         string `gorm:"column:kind"`
	LogicalSlug  string `gorm:"column:logical_slug"`
	RevisionID   string `gorm:"column:revision_id"`
	MemberDigest string `gorm:"column:member_digest"`
	Title        string `gorm:"column:title"`
	Content      string `gorm:"column:content"`
	PayloadJSON  string `gorm:"column:payload_json"`
}

func (contentRow) TableName() string { return "enterprise_member_contents" }

type chunkRow struct {
	ScopeID int64  `gorm:"column:scope_id;primaryKey"`
	Digest  []byte `gorm:"column:digest;primaryKey"`
	Codec   int    `gorm:"column:codec"`
	Count   int    `gorm:"column:count"`
	Refs    []byte `gorm:"column:refs"`
}

func (chunkRow) TableName() string { return "enterprise_member_chunks" }

type setRow struct {
	ScopeID     int64  `gorm:"column:scope_id;primaryKey"`
	Digest      []byte `gorm:"column:digest;primaryKey"`
	Codec       int    `gorm:"column:codec"`
	OrderMode   string `gorm:"column:order_mode"`
	MemberCount int64  `gorm:"column:member_count"`
	ChunkCount  int    `gorm:"column:chunk_count"`
	Blocks      []byte `gorm:"column:blocks"`
}

func (setRow) TableName() string { return "enterprise_member_sets" }

type releaseMap struct {
	ReleaseID string `gorm:"column:release_id;primaryKey"`
	ScopeID   int64  `gorm:"column:scope_id"`
	types.WikiReleaseScope
	RootDigest []byte `gorm:"column:root_digest"`
	Verified   bool   `gorm:"column:verified"`
}

func (releaseMap) TableName() string { return "enterprise_member_releases" }

type preparationMap struct {
	PreparationID string `gorm:"column:preparation_id;primaryKey"`
	ScopeID       int64  `gorm:"column:scope_id"`
	types.WikiReleaseScope
	RootDigest []byte `gorm:"column:root_digest"`
	Verified   bool   `gorm:"column:verified"`
}

func (preparationMap) TableName() string { return "enterprise_member_preparations" }

type progressRow struct {
	ReleaseID    string `gorm:"column:release_id;primaryKey"`
	ScopeID      int64  `gorm:"column:scope_id"`
	SourceDigest []byte `gorm:"column:source_digest"`
	Phase        string `gorm:"column:phase"`
	SourceBytes  int64  `gorm:"column:source_bytes"`
}

func (progressRow) TableName() string { return "enterprise_member_progress" }

type layoutEntry struct {
	Slug   string
	Digest []byte
}
type layoutChunk struct{ Entries []layoutEntry }
