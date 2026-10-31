package service

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// The revision-source pin check before a reparse move is ours. The test wraps the upstream move
// fixture (knowledge_move_wiki_test.go, kept byte-identical) instead of adding fields to it.
type pinnedMoveWikiKnowledgeRepo struct {
	*moveWikiKnowledgeRepo
	pinned      bool
	pinnedCalls int
	updateCalls int
}

func (r *pinnedMoveWikiKnowledgeRepo) HasPinnedRevisionSource(
	_ context.Context, _ uint64, _ string,
) (bool, error) {
	r.pinnedCalls++
	return r.pinned, nil
}

func (r *pinnedMoveWikiKnowledgeRepo) UpdateKnowledge(ctx context.Context, k *types.Knowledge) error {
	r.updateCalls++
	return r.moveWikiKnowledgeRepo.UpdateKnowledge(ctx, k)
}

func TestMoveReparseRejectsPinnedRevisionSourceBeforeMutation(t *testing.T) {
	svc, wikiRepo, pendingRepo, chunkRepo := newMoveWikiService(t)
	repo := &pinnedMoveWikiKnowledgeRepo{moveWikiKnowledgeRepo: svc.repo.(*moveWikiKnowledgeRepo), pinned: true}
	svc.repo = repo
	repo.knowledge.Type = "file"
	repo.knowledge.FilePath = "source/document.md"
	repo.knowledge.FileName = "document.md"
	repo.knowledge.FileType = "md"

	err := svc.moveOneKnowledge(
		moveWikiCtx(), "kn-1", wikiEnabledKB("kb-src"), wikiEnabledKB("kb-dst"), "reparse",
	)

	require.ErrorIs(t, err, ErrKnowledgeRevisionSourcePinned)
	require.Equal(t, 1, repo.pinnedCalls)
	require.Zero(t, repo.updateCalls)
	require.Empty(t, wikiRepo.listedKBs)
	require.Empty(t, pendingRepo.ops)
	require.Empty(t, chunkRepo.movedToKB)
	require.Equal(t, types.ParseStatusCompleted, repo.knowledge.ParseStatus)
}
