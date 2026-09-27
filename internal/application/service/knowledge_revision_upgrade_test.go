package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/hibiken/asynq"
	"github.com/stretchr/testify/require"
)

type upgradeFailedImageQueue struct{ post *asynq.Task }

func (q *upgradeFailedImageQueue) Enqueue(task *asynq.Task, _ ...asynq.Option) (*asynq.TaskInfo, error) {
	if task.Type() == types.TypeImageMultimodal {
		return nil, errors.New("queue unavailable")
	}
	q.post = task
	return &asynq.TaskInfo{}, nil
}
func TestUPGImageEnqueueFailurePreservesRevisionForCompletion(t *testing.T) {
	knowledge, kb, images, chunks := slotReleaseFixture(1)
	revision := &types.RevisionCommitBinding{ParseAttempt: 3, FileSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
	queue := &upgradeFailedImageQueue{}
	svc := &knowledgeService{task: queue}
	svc.enqueueImageMultimodalTasks(context.Background(), knowledge, kb, images, chunks, nil, revision)
	require.NotNil(t, queue.post)
	var payload types.KnowledgePostProcessPayload
	require.NoError(t, json.Unmarshal(queue.post.Payload(), &payload))
	require.Equal(t, revision, payload.Revision, "failed optional image task must not discard immutable source binding")
}

func TestUPGDeleteRequiresExecutionTenantBeforeSourceGuard(t *testing.T) {
	for _, multiple := range []bool{false, true} {
		t.Run(fmt.Sprint(multiple), func(t *testing.T) {
			svc := &knowledgeService{}
			require.NotPanics(t, func() {
				var err error
				if multiple {
					err = svc.DeleteKnowledgeList(context.Background(), []string{"knowledge"})
				} else {
					err = svc.DeleteKnowledge(context.Background(), "knowledge")
				}
				require.Error(t, err)
			})
		})
	}
}
