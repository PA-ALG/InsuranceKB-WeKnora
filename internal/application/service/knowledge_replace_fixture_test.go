package service

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/access"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/hibiken/asynq"
	"github.com/stretchr/testify/require"
)

// replaceFileRepo is a single-row knowledge store. UpdateKnowledgeColumns can
// fail on a chosen call, either before applying the write or after it (a write
// that committed but reported an error).
type replaceFileRepo struct {
	interfaces.KnowledgeRepository
	row                  types.Knowledge
	columnsCalls         int
	failColumnsCall      int
	commitThenFail       bool
	allocatedKnowledgeID string
	allocatedModelID     string
	allocatedFileSHA256  string
	sourceSnapshots      []types.Knowledge
}

func (r *replaceFileRepo) GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error) {
	row := r.row
	return &row, nil
}

func (r *replaceFileRepo) UpdateKnowledge(_ context.Context, knowledge *types.Knowledge) error {
	r.row = *knowledge
	return nil
}

func (r *replaceFileRepo) UpdateKnowledgeColumn(_ context.Context, _ string, column string, value interface{}) error {
	r.apply(map[string]interface{}{column: value})
	return nil
}

func (r *replaceFileRepo) UpdateKnowledgeColumns(_ context.Context, _ string, values map[string]interface{}) error {
	r.columnsCalls++
	if r.columnsCalls != r.failColumnsCall {
		r.apply(values)
		r.sourceSnapshots = append(r.sourceSnapshots, r.row)
		return nil
	}
	if r.commitThenFail {
		r.apply(values)
		r.sourceSnapshots = append(r.sourceSnapshots, r.row)
	}
	return errors.New("database unavailable")
}

// Allocation records the service-supplied source identity without recomputing it.
func (r *replaceFileRepo) AllocateParseAttempt(
	_ context.Context, knowledgeID, modelID, fileSHA256 string,
) (int64, error) {
	if knowledgeID != r.row.ID {
		return 0, errors.New("unexpected knowledge allocation")
	}
	r.allocatedKnowledgeID, r.allocatedModelID, r.allocatedFileSHA256 = knowledgeID, modelID, fileSHA256
	r.row.CurrentParseAttempt++
	r.row.EmbeddingModelID = modelID
	r.row.FileSHA256 = fileSHA256
	r.row.ErrorMessage = ""
	return r.row.CurrentParseAttempt, nil
}

func (*replaceFileRepo) CommitDirectRevision(
	context.Context, string, types.RevisionCommitBinding,
) (*types.KnowledgeRevision, error) {
	return nil, errors.New("unexpected direct revision commit during enqueue")
}

func (*replaceFileRepo) FinalizeSubtaskRevision(
	context.Context, string, types.RevisionCommitBinding,
) (int, bool, error) {
	return 0, false, errors.New("unexpected revision finalization during enqueue")
}

func (r *replaceFileRepo) apply(values map[string]interface{}) {
	for column, value := range values {
		switch column {
		case "title":
			r.row.Title = value.(string)
		case "file_name":
			r.row.FileName = value.(string)
		case "folder_path":
			r.row.FolderPath = value.(string)
		case "file_type":
			r.row.FileType = value.(string)
		case "file_size":
			r.row.FileSize = value.(int64)
		case "file_sha256":
			r.row.FileSHA256 = value.(string)
		case "file_hash":
			r.row.FileHash = value.(string)
		case "file_path":
			r.row.FilePath = value.(string)
		case "metadata":
			r.row.Metadata = value.(types.JSON)
		case "parse_status":
			r.row.ParseStatus = value.(string)
		case "enable_status":
			r.row.EnableStatus = value.(string)
		case "error_message":
			r.row.ErrorMessage = value.(string)
		}
	}
}

type replaceFileStore struct {
	interfaces.FileService
	saveErr error
	saved   int
	files   map[string][]byte
	deleted []string
	events  *[]string
}

func (f *replaceFileStore) SaveFile(_ context.Context, file *multipart.FileHeader, _ uint64, _ string) (string, error) {
	if f.saveErr != nil {
		return "", f.saveErr
	}
	reader, err := file.Open()
	if err != nil {
		return "", err
	}
	content, readErr := io.ReadAll(reader)
	closeErr := reader.Close()
	if err := errors.Join(readErr, closeErr); err != nil {
		return "", err
	}
	f.files["new/file.md"] = content
	f.saved++
	*f.events = append(*f.events, "save")
	return "new/file.md", nil
}

func (f *replaceFileStore) GetFile(_ context.Context, filePath string) (io.ReadCloser, error) {
	content, ok := f.files[filePath]
	if !ok {
		return nil, fmt.Errorf("file not found: %s", filePath)
	}
	return io.NopCloser(bytes.NewReader(content)), nil
}

func (f *replaceFileStore) DeleteFile(_ context.Context, filePath string) error {
	delete(f.files, filePath)
	f.deleted = append(f.deleted, filePath)
	*f.events = append(*f.events, "delete:"+filePath)
	return nil
}

type replaceFileEnqueuer struct {
	err      error
	payloads []types.DocumentProcessPayload
	events   *[]string
}

func (e *replaceFileEnqueuer) Enqueue(task *asynq.Task, _ ...asynq.Option) (*asynq.TaskInfo, error) {
	if e.err != nil {
		return nil, e.err
	}
	var payload types.DocumentProcessPayload
	if err := json.Unmarshal(task.Payload(), &payload); err != nil {
		return nil, err
	}
	e.payloads = append(e.payloads, payload)
	*e.events = append(*e.events, "enqueue")
	return &asynq.TaskInfo{ID: "task-1", Queue: types.QueueDefault}, nil
}

type replaceFileChunks struct{ interfaces.ChunkRepository }

func (replaceFileChunks) ListImageInfoByKnowledgeIDs(
	context.Context, uint64, []string,
) ([]interfaces.ChunkImageInfo, error) {
	return nil, nil
}

func (replaceFileChunks) DeleteChunksByKnowledgeID(context.Context, uint64, string) error { return nil }

type replaceFileChunkService struct{ interfaces.ChunkService }

func (replaceFileChunkService) GetRepository() interfaces.ChunkRepository { return replaceFileChunks{} }

type replaceFileGraph struct {
	interfaces.RetrieveGraphRepository
}

func (replaceFileGraph) DelGraph(context.Context, []types.NameSpace) error { return nil }

type replaceFileInspector struct {
	fakeTaskInspector
	events *[]string
}

func (i *replaceFileInspector) CancelTasksForKnowledge(_ context.Context, knowledgeID string) (int, int, error) {
	*i.events = append(*i.events, "dequeue:"+knowledgeID)
	return 1, 0, nil
}

type replaceFileHarness struct {
	svc      *knowledgeService
	repo     *replaceFileRepo
	store    *replaceFileStore
	tasks    *replaceFileEnqueuer
	events   []string
	original types.Knowledge
	ctx      context.Context
}

const replaceFileOldContent = "old"

func newReplaceFileHarness(t *testing.T) *replaceFileHarness {
	t.Helper()
	kb := &types.KnowledgeBase{ID: "kb-1", TenantID: 7}
	h := &replaceFileHarness{}
	h.original = types.Knowledge{
		ID:              "knowledge-1",
		TenantID:        7,
		KnowledgeBaseID: "kb-1",
		Type:            "file",
		Title:           "a.md",
		FileName:        "a.md",
		FolderPath:      "notes",
		FileType:        "md",
		FileSize:        int64(len(replaceFileOldContent)),
		FileHash:        md5Hex(replaceFileOldContent),
		FilePath:        "old/file.md",
		ParseStatus:     types.ParseStatusCompleted,
		EnableStatus:    "enabled",
		Metadata:        types.JSON(`{"external_id":"notes/a.md","extra":{"nested":true}}`),
	}
	h.repo = &replaceFileRepo{row: h.original}
	h.store = &replaceFileStore{
		events: &h.events, files: map[string][]byte{"old/file.md": []byte(replaceFileOldContent)},
	}
	h.tasks = &replaceFileEnqueuer{events: &h.events}
	h.svc = &knowledgeService{
		repo:          h.repo,
		kbService:     &reparseFailureKBService{kb: kb},
		fileSvc:       h.store,
		task:          h.tasks,
		taskInspector: &replaceFileInspector{events: &h.events},
		chunkService:  replaceFileChunkService{},
		chunkRepo:     replaceFileChunks{},
		graphEngine:   replaceFileGraph{},
	}
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
	ctx = context.WithValue(ctx, types.TenantInfoContextKey, &types.Tenant{ID: 7})
	ctx, err := access.WithKBTaskWrite(ctx, kb, 7)
	require.NoError(t, err)
	h.ctx = ctx
	return h
}

func (h *replaceFileHarness) replace(
	t *testing.T, content, customFileName string, metadata map[string]string,
) (*types.Knowledge, error) {
	t.Helper()
	return h.replaceNamed(t, content, "upload.md", customFileName, metadata)
}

func (h *replaceFileHarness) replaceNamed(
	t *testing.T, content, filename, customFileName string, metadata map[string]string,
) (*types.Knowledge, error) {
	t.Helper()
	fh, err := bytesToFileHeader([]byte(content), filename)
	require.NoError(t, err)
	return h.svc.ReplaceKnowledgeFile(h.ctx, h.original.ID, fh, customFileName, metadata)
}

func md5Hex(content string) string {
	return fmt.Sprintf("%x", md5.Sum([]byte(content)))
}
