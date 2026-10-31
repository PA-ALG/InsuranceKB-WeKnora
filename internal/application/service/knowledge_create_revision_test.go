package service

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/hibiken/asynq"
	"github.com/stretchr/testify/require"
)

// Revision binding on create (parse attempt, source SHA-256, capacity check) is ours. These tests
// live here so the upstream knowledge_create_test.go stays byte-identical; they reuse its stubs and
// add an enqueuer that also records the task payloads.

type revisionCaptureEnqueuer struct {
	createKnowledgeTaskEnqueuerStub
	payload       types.DocumentProcessPayload
	manualPayload types.ManualProcessPayload
}

func (s *revisionCaptureEnqueuer) Enqueue(
	task *asynq.Task,
	opts ...asynq.Option,
) (*asynq.TaskInfo, error) {
	if task.Type() == types.TypeDocumentProcess {
		_ = json.Unmarshal(task.Payload(), &s.payload)
	}
	if task.Type() == types.TypeManualProcess {
		_ = json.Unmarshal(task.Payload(), &s.manualPayload)
	}
	return s.createKnowledgeTaskEnqueuerStub.Enqueue(task, opts...)
}

func TestManualProcessPayloadCarriesDatabaseParseAttempt(t *testing.T) {
	t.Parallel()
	task := &revisionCaptureEnqueuer{}
	svc := &knowledgeService{task: task}
	knowledge := &types.Knowledge{
		ID: "manual-1", TenantID: 7, KnowledgeBaseID: "kb-1", CurrentParseAttempt: 9,
	}
	_, err := svc.enqueueManualProcessing(
		context.Background(), knowledge, "content", true,
	)
	require.NoError(t, err)
	require.Equal(t, int64(9), task.manualPayload.ParseAttempt)
}

func TestCreateKnowledgeFromFileCapacityRejectsBeforeWriting(t *testing.T) {
	t.Setenv("DOCUMENT_STORAGE_MIN_FREE_BYTES", "18446744073709551615")
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	repo := &createKnowledgeFileRepoStub{}
	fileSvc := &createKnowledgeFileServiceStub{}
	svc := &knowledgeService{
		repo: repo, fileSvc: fileSvc,
		kbService: &createKnowledgeFileKBServiceStub{kb: &types.KnowledgeBase{ID: "kb-1"}},
	}
	knowledge, err := svc.CreateKnowledgeFromFile(newCreateKnowledgeFileContext(), "kb-1",
		newMultipartFileHeader(t, "doc.txt", "hello"), nil, nil, "", nil, "", nil)
	require.Error(t, err)
	require.Nil(t, knowledge)
	require.Zero(t, fileSvc.saveCalls)
	require.Zero(t, repo.createCalls)
}

func TestCreateKnowledgeFromFileBindsParseAttemptAndSourceSHA(t *testing.T) {
	t.Parallel()

	repo := &createKnowledgeFileRepoStub{}
	fileSvc := &createKnowledgeFileServiceStub{}
	task := &revisionCaptureEnqueuer{}
	svc := &knowledgeService{
		repo:      repo,
		kbService: &createKnowledgeFileKBServiceStub{kb: &types.KnowledgeBase{ID: "kb-1"}},
		fileSvc:   fileSvc,
		task:      task,
	}

	knowledge, err := svc.CreateKnowledgeFromFile(
		newCreateKnowledgeFileContext(),
		"kb-1",
		newMultipartFileHeader(t, "doc.txt", "hello"),
		nil,
		nil,
		"",
		nil,
		"",
		nil,
	)

	require.NoError(t, err)
	require.NotNil(t, knowledge)
	require.NotNil(t, repo.createdKnowledge)
	require.Equal(t, 1, task.calls)
	require.Equal(t, int64(1), repo.createdKnowledge.CurrentParseAttempt)
	require.Equal(t, "5d41402abc4b2a76b9719d911017c592", repo.createdKnowledge.FileHash)
	require.Equal(t,
		"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
		repo.createdKnowledge.FileSHA256,
	)
	require.NotNil(t, task.payload.Revision)
	require.Equal(t, int64(1), task.payload.Revision.ParseAttempt)
	require.Equal(t, repo.createdKnowledge.FileSHA256, task.payload.Revision.FileSHA256)
}
