package interfaces

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// KnowledgeRevisionSourceRepository is the narrow authority used to seal and
// replay immutable attempt-bound source rows. It deliberately excludes current
// preview/presigned URL methods.
type KnowledgeRevisionSourceRepository interface {
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
