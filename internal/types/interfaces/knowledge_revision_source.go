package interfaces

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// KnowledgeRevisionSourceExact3Authority is one server-owned database view
// used by the medical 596-1 exact3 preflight. Physical paths never leave the
// service boundary.
type KnowledgeRevisionSourceExact3Authority struct {
	Knowledge            *types.Knowledge
	Current              *types.KnowledgeRevision
	Last                 *types.KnowledgeRevision
	Resource             *types.StoredResource
	ResourceBindingCount int64
	ExistingSource       *types.KnowledgeRevisionSource
}

// KnowledgeRevisionSourceExact3SnapshotReader is intentionally narrower than
// the repository: it exposes no mutation while a read-only snapshot is open.
type KnowledgeRevisionSourceExact3SnapshotReader interface {
	GetExact3RevisionSourceAuthority(
		context.Context, uint64, string, string, int64,
	) (*KnowledgeRevisionSourceExact3Authority, error)
}

// KnowledgeRevisionSourceRepository is the narrow authority used to seal and
// replay immutable attempt-bound source rows. It deliberately excludes current
// preview/presigned URL methods.
type KnowledgeRevisionSourceRepository interface {
	KnowledgeRevisionSourceExact3SnapshotReader
	WithExact3ReadSnapshot(
		context.Context,
		func(KnowledgeRevisionSourceExact3SnapshotReader) error,
	) error
	GetRevisionState(context.Context, string) (
		*types.Knowledge,
		*types.KnowledgeRevision,
		*types.KnowledgeRevision,
		error,
	)
	GetRevisionSource(context.Context, uint64, string, int64) (
		*types.KnowledgeRevisionSource,
		*types.StoredResource,
		error,
	)
	SealRevisionSourceBinding(
		context.Context,
		types.KnowledgeRevisionSource,
	) (*types.KnowledgeRevisionSource, error)
	HasPinnedRevisionSource(context.Context, uint64, string) (bool, error)
}
