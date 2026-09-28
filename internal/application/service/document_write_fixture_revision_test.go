package service

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// The spy embeds the public repository interface, so forward its revision
// extension explicitly to keep these fixtures on the real SQLite implementation.
func (r *documentKnowledgeSpy) AllocateParseAttempt(
	ctx context.Context, knowledgeID, modelID, fileSHA256 string,
) (int64, error) {
	repo, err := requireRevisionRepository(r.KnowledgeRepository)
	if err != nil {
		return 0, err
	}
	r.writes++
	return repo.AllocateParseAttempt(ctx, knowledgeID, modelID, fileSHA256)
}

func (r *documentKnowledgeSpy) CommitDirectRevision(
	ctx context.Context, knowledgeID string, binding types.RevisionCommitBinding,
) (*types.KnowledgeRevision, error) {
	repo, err := requireRevisionRepository(r.KnowledgeRepository)
	if err != nil {
		return nil, err
	}
	r.writes++
	return repo.CommitDirectRevision(ctx, knowledgeID, binding)
}

func (r *documentKnowledgeSpy) FinalizeSubtaskRevision(
	ctx context.Context, knowledgeID string, binding types.RevisionCommitBinding,
) (int, bool, error) {
	repo, err := requireRevisionRepository(r.KnowledgeRepository)
	if err != nil {
		return 0, false, err
	}
	r.writes++
	return repo.FinalizeSubtaskRevision(ctx, knowledgeID, binding)
}
