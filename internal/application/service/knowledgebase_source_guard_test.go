package service

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/hibiken/asynq"
	"github.com/stretchr/testify/require"
)

type sourceGuardKnowledgeRepo struct {
	interfaces.KnowledgeRepository
	pinned    bool
	err       error
	checks    []wikiKBDeleteCall
	lists     int
	deletes   int
	deleteErr error
}

func (r *sourceGuardKnowledgeRepo) HasPinnedRevisionSourceInKnowledgeBase(
	_ context.Context, tenantID uint64, kbID string,
) (bool, error) {
	r.checks = append(r.checks, wikiKBDeleteCall{tenantID, kbID})
	return r.pinned, r.err
}

func (r *sourceGuardKnowledgeRepo) ListKnowledgeByKnowledgeBaseID(
	context.Context, uint64, string,
) ([]*types.Knowledge, error) {
	r.lists++
	return nil, errors.New("delete passed the source guard")
}

func TestKnowledgeBaseSourceGuardsRejectBeforeAnyCleanup(t *testing.T) {
	for _, failure := range []error{nil, errors.New("source query failed")} {
		for _, async := range []bool{false, true} {
			name := "pinned"
			if failure != nil {
				name = "query error"
			}
			t.Run(name+map[bool]string{false: "/sync", true: "/async"}[async],
				func(t *testing.T) {
					knowledge := &sourceGuardKnowledgeRepo{pinned: failure == nil, err: failure}
					kb := &kbDeleteKBRepo{fakeKBRepo: *newFakeKBRepo()}
					kb.rows["kb-1"] = &types.KnowledgeBase{ID: "kb-1", TenantID: 1}
					wiki := &recordingWikiRepo{}
					svc := &knowledgeBaseService{
						repo: kb, kgRepo: knowledge, wikiRepo: wiki, asynqClient: kbDeleteTaskEnqueuer{},
					}
					var err error
					if async {
						err = svc.ProcessKBDelete(context.Background(), kbDeletePayload(t, "kb-1", 1))
					} else {
						err = svc.DeleteKnowledgeBase(ctxWithTenantStorage(1, "local"), "kb-1")
					}
					require.Error(t, err)
					if failure != nil {
						require.ErrorIs(t, err, failure)
						require.NotErrorIs(t, err, asynq.SkipRetry)
					} else if async {
						require.ErrorIs(t, err, asynq.SkipRetry)
					} else {
						require.ErrorIs(t, err, ErrKnowledgeRevisionSourcePinned)
					}
					require.Equal(t, []wikiKBDeleteCall{{1, "kb-1"}}, knowledge.checks)
					require.Zero(t, knowledge.lists)
					require.Empty(t, kb.deletedID)
					require.Contains(t, kb.rows, "kb-1")
					require.Empty(t, wiki.pagesCalls)
					require.Empty(t, wiki.foldersCalls)
					require.Empty(t, wiki.revisionsCalls)
					require.Empty(t, wiki.issuesCalls)
				})
		}
	}
}

// Existing cleanup fixtures have no published sources.
func (emptyKBKnowledgeRepo) HasPinnedRevisionSourceInKnowledgeBase(context.Context, uint64, string) (bool, error) {
	return false, nil
}

func (populatedKBKnowledgeRepo) HasPinnedRevisionSourceInKnowledgeBase(context.Context, uint64, string) (bool, error) {
	return false, nil
}

func (r *sourceGuardKnowledgeRepo) DeleteKnowledgeBaseUnlessPinned(context.Context, uint64, string) error {
	r.deletes++
	return r.deleteErr
}

// Sync deletion fixtures share the same fake KB repository for the atomic
// admission write and the subsequent metadata/cleanup assertions.
type kbDeletionKnowledgeRepo struct {
	emptyKBKnowledgeRepo
	kb interfaces.KnowledgeBaseRepository
}

func (r kbDeletionKnowledgeRepo) DeleteKnowledgeBaseUnlessPinned(ctx context.Context, _ uint64, id string) error {
	return r.kb.DeleteKnowledgeBase(ctx, id)
}

func TestKnowledgeBaseAtomicAdmissionRefusesBeforeCleanup(t *testing.T) {
	for _, failure := range []error{repository.ErrResourcePinned, errors.New("KB admission failed")} {
		kb := &kbDeleteKBRepo{fakeKBRepo: *newFakeKBRepo()}
		kb.rows["kb-1"] = &types.KnowledgeBase{ID: "kb-1", TenantID: 1}
		knowledge := &sourceGuardKnowledgeRepo{deleteErr: failure}
		wiki := &recordingWikiRepo{}
		svc := &knowledgeBaseService{
			repo: kb, kgRepo: knowledge, wikiRepo: wiki, asynqClient: kbDeleteTaskEnqueuer{},
		}
		err := svc.DeleteKnowledgeBase(ctxWithTenantStorage(1, "local"), "kb-1")
		if errors.Is(failure, repository.ErrResourcePinned) {
			require.ErrorIs(t, err, ErrKnowledgeRevisionSourcePinned)
		} else {
			require.ErrorIs(t, err, failure)
		}
		require.Equal(t, 1, knowledge.deletes)
		require.Empty(t, kb.deletedID)
		require.Contains(t, kb.rows, "kb-1")
		require.Empty(t, wiki.pagesCalls)
	}
}
