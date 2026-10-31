package service

import (
	"context"
	"errors"

	"github.com/Tencent/WeKnora/internal/types"
)

// Reparse now allocates a parse attempt through the repository (our revision fencing). These
// methods complete the upstream reparse fixture (knowledge_batch_reparse_test.go, kept
// byte-identical). Allocation records the service boundary; no worker commits run in these tests.
func (r *reparseFailureKnowledgeRepo) AllocateParseAttempt(
	_ context.Context, knowledgeID, modelID, fileSHA256 string,
) (int64, error) {
	if knowledgeID != r.knowledge.ID {
		return 0, errors.New("unexpected knowledge allocation")
	}
	r.knowledge.CurrentParseAttempt++
	r.knowledge.EmbeddingModelID = modelID
	r.knowledge.FileSHA256 = fileSHA256
	r.knowledge.ErrorMessage = ""
	return r.knowledge.CurrentParseAttempt, nil
}

func (*reparseFailureKnowledgeRepo) CommitDirectRevision(
	context.Context, string, types.RevisionCommitBinding,
) (*types.KnowledgeRevision, error) {
	return nil, errors.New("unexpected direct revision commit during enqueue")
}

func (*reparseFailureKnowledgeRepo) FinalizeSubtaskRevision(
	context.Context, string, types.RevisionCommitBinding,
) (int, bool, error) {
	return 0, false, errors.New("unexpected revision finalization during enqueue")
}
