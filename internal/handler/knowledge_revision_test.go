package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

type revisionReaderStub struct {
	interfaces.KnowledgeRepository
	states []revisionStubState
	chunks []*types.Chunk
	total  int64
	calls  int
}

type revisionStubState struct {
	knowledge *types.Knowledge
	current   *types.KnowledgeRevision
	last      *types.KnowledgeRevision
	err       error
}

func (s *revisionReaderStub) GetRevisionState(
	context.Context, string,
) (*types.Knowledge, *types.KnowledgeRevision, *types.KnowledgeRevision, error) {
	if len(s.states) == 0 {
		return nil, nil, nil, repository.ErrKnowledgeNotFound
	}
	index := s.calls
	if index >= len(s.states) {
		index = len(s.states) - 1
	}
	s.calls++
	state := s.states[index]
	return state.knowledge, state.current, state.last, state.err
}

func (s *revisionReaderStub) ListRevisionChunks(
	_ context.Context, _ string, _ int64, page *types.Pagination,
) ([]*types.Chunk, int64, error) {
	start := page.Offset()
	if start >= len(s.chunks) {
		return nil, s.total, nil
	}
	end := min(start+page.Limit(), len(s.chunks))
	return s.chunks[start:end], s.total, nil
}

func (s *revisionReaderStub) GetRevision(
	_ context.Context, _ string, attempt int64,
) (*types.KnowledgeRevision, error) {
	for _, state := range s.states {
		for _, revision := range []*types.KnowledgeRevision{state.current, state.last} {
			if revision != nil && revision.ParseAttempt == attempt {
				return revision, nil
			}
		}
	}
	return nil, repository.ErrKnowledgeNotFound
}

type revisionKnowledgeServiceStub struct {
	interfaces.KnowledgeService
	repo interfaces.KnowledgeRepository
}

func (s *revisionKnowledgeServiceStub) GetRepository() interfaces.KnowledgeRepository {
	return s.repo
}

type revisionKBServiceStub struct {
	interfaces.KnowledgeBaseService
	tenantID uint64
}

func (s *revisionKBServiceStub) GetKnowledgeBaseByID(
	_ context.Context, id string,
) (*types.KnowledgeBase, error) {
	tenantID := uint64(7)
	if s.tenantID != 0 {
		tenantID = s.tenantID
	}
	return &types.KnowledgeBase{ID: id, TenantID: tenantID}, nil
}

func revisionRouterWithKBTenant(t *testing.T, repo *revisionReaderStub, kbTenantID uint64) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.Use(middleware.ErrorHandler())
	router.Use(func(c *gin.Context) {
		c.Set(types.TenantIDContextKey.String(), uint64(7))
		c.Next()
	})
	handler := &KnowledgeHandler{
		kgService: &revisionKnowledgeServiceStub{repo: repo},
		kbService: &revisionKBServiceStub{tenantID: kbTenantID},
	}
	router.GET("/knowledge/:id/revision", handler.GetKnowledgeRevision)
	router.GET("/knowledge/:id/revisions/:attempt/chunks", handler.ListKnowledgeRevisionChunks)
	return router
}

func revisionRouter(t *testing.T, repo *revisionReaderStub) *gin.Engine {
	return revisionRouterWithKBTenant(t, repo, 7)
}

func revisionFixture(status string, attempt int64) (*types.Knowledge, *types.KnowledgeRevision) {
	knowledge := &types.Knowledge{
		ID: "knowledge-1", TenantID: 7, KnowledgeBaseID: "kb-1",
		ParseStatus: status, CurrentParseAttempt: attempt, FilePath: "/input.pdf",
	}
	revision := &types.KnowledgeRevision{
		KnowledgeID: "knowledge-1", ParseAttempt: attempt,
		FileSHA256:        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ManifestAlgorithm: types.RevisionManifestAlgorithm,
		ManifestDigest:    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
		ChunkCount:        2, CompletedAt: time.Unix(10, 0).UTC(),
	}
	return knowledge, revision
}

func decodeRevisionResponse(t *testing.T, recorder *httptest.ResponseRecorder) map[string]interface{} {
	t.Helper()
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &body))
	return body
}

func TestGetKnowledgeRevisionReturnsCommittedDescriptor(t *testing.T) {
	knowledge, revision := revisionFixture(types.ParseStatusCompleted, 3)
	router := revisionRouter(t, &revisionReaderStub{
		states: []revisionStubState{{knowledge: knowledge, current: revision, last: revision}},
	})
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/knowledge/knowledge-1/revision", nil))

	require.Equal(t, http.StatusOK, recorder.Code)
	data := decodeRevisionResponse(t, recorder)["data"].(map[string]interface{})
	require.Equal(t, float64(3), data["parse_attempt"])
	require.Equal(t, revision.ManifestDigest, data["chunk_manifest"].(map[string]interface{})["digest"])
	require.Equal(t, revision.FileSHA256, data["file_digest"].(map[string]interface{})["value"])
}

func TestGetKnowledgeRevisionDistinguishesNotCommittedDeletedAndMissing(t *testing.T) {
	knowledge, revision := revisionFixture(types.ParseStatusProcessing, 4)
	recorder := httptest.NewRecorder()
	revisionRouter(t, &revisionReaderStub{
		states: []revisionStubState{{knowledge: knowledge, last: revision}},
	}).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/knowledge/knowledge-1/revision", nil))
	require.Equal(t, http.StatusConflict, recorder.Code)
	require.Equal(t, "revision_not_committed",
		decodeRevisionResponse(t, recorder)["error"].(map[string]interface{})["code"])

	deleted := *knowledge
	deleted.DeletedAt = gorm.DeletedAt{Time: time.Unix(20, 0).UTC(), Valid: true}
	recorder = httptest.NewRecorder()
	revisionRouter(t, &revisionReaderStub{
		states: []revisionStubState{{knowledge: &deleted}},
	}).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/knowledge/knowledge-1/revision", nil))
	require.Equal(t, http.StatusGone, recorder.Code)
	require.Equal(t, "knowledge_deleted",
		decodeRevisionResponse(t, recorder)["error"].(map[string]interface{})["code"])

	recorder = httptest.NewRecorder()
	revisionRouter(t, &revisionReaderStub{
		states: []revisionStubState{{err: repository.ErrKnowledgeNotFound}},
	}).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/knowledge/missing/revision", nil))
	require.Equal(t, http.StatusNotFound, recorder.Code)
}

func TestGetKnowledgeRevisionNotCommittedReasonMatrix(t *testing.T) {
	base, last := revisionFixture(types.ParseStatusProcessing, 4)
	last.ParseAttempt = 3
	tests := []struct {
		name     string
		mutate   func(*types.Knowledge)
		want     string
		withLast bool
	}{
		{"file-less", func(k *types.Knowledge) { k.FilePath = "" }, "file_less_source", false},
		{"never completed", func(k *types.Knowledge) { k.CurrentParseAttempt = 0 }, "never_completed", false},
		{"non-parse completed", func(k *types.Knowledge) {
			k.ParseStatus = types.ParseStatusCompleted
		}, "non_parse_completed", false},
		{"failed after committed", func(k *types.Knowledge) {
			k.ParseStatus = types.ParseStatusFailed
		}, "attempt_terminal", true},
		{"in flight", func(*types.Knowledge) {}, "attempt_in_progress", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			knowledge := *base
			tt.mutate(&knowledge)
			state := revisionStubState{knowledge: &knowledge}
			if tt.withLast {
				state.last = last
			}
			recorder := httptest.NewRecorder()
			revisionRouter(t, &revisionReaderStub{states: []revisionStubState{state}}).
				ServeHTTP(recorder,
					httptest.NewRequest(http.MethodGet, "/knowledge/knowledge-1/revision", nil))
			require.Equal(t, http.StatusConflict, recorder.Code)
			details := decodeRevisionResponse(t, recorder)["error"].(map[string]interface{})
			require.Equal(t, tt.want, details["reason"])
			if tt.withLast {
				require.Equal(t, float64(3),
					details["last_committed"].(map[string]interface{})["parse_attempt"])
			}
		})
	}
}

func TestListKnowledgeRevisionChunksDoubleChecksAttempt(t *testing.T) {
	knowledge, revision := revisionFixture(types.ParseStatusCompleted, 3)
	superseded := *knowledge
	superseded.CurrentParseAttempt = 4
	superseded.ParseStatus = types.ParseStatusPending
	router := revisionRouter(t, &revisionReaderStub{
		states: []revisionStubState{
			{knowledge: knowledge, current: revision, last: revision},
			{knowledge: &superseded, last: revision},
		},
		chunks: []*types.Chunk{{ID: "c1", KnowledgeID: knowledge.ID, ParseAttempt: 3}},
		total:  2,
	})
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder,
		httptest.NewRequest(http.MethodGet, "/knowledge/knowledge-1/revisions/3/chunks?page=1&page_size=1", nil))
	require.Equal(t, http.StatusGone, recorder.Code)
	require.Equal(t, "revision_superseded",
		decodeRevisionResponse(t, recorder)["error"].(map[string]interface{})["code"])
}

func TestListKnowledgeRevisionChunksReturnsManifestBoundPage(t *testing.T) {
	knowledge, revision := revisionFixture(types.ParseStatusCompleted, 3)
	router := revisionRouter(t, &revisionReaderStub{
		states: []revisionStubState{{knowledge: knowledge, current: revision, last: revision}},
		chunks: []*types.Chunk{{ID: "c1", KnowledgeID: knowledge.ID, ParseAttempt: 3}},
		total:  2,
	})
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder,
		httptest.NewRequest(http.MethodGet, "/knowledge/knowledge-1/revisions/3/chunks?page=2&page_size=1", nil))

	require.Equal(t, http.StatusOK, recorder.Code)
	body := decodeRevisionResponse(t, recorder)
	require.Equal(t, float64(2), body["total"])
	require.Equal(t, float64(2), body["page"])
	require.Equal(t, revision.ManifestDigest, body["revision"].(map[string]interface{})["manifest_digest"])
}

func TestListKnowledgeRevisionChunksRejectsManifestCountDriftWithStableCode(t *testing.T) {
	knowledge, revision := revisionFixture(types.ParseStatusCompleted, 3)
	router := revisionRouter(t, &revisionReaderStub{
		states: []revisionStubState{{knowledge: knowledge, current: revision, last: revision}},
		chunks: []*types.Chunk{{ID: "c1", KnowledgeID: knowledge.ID, ParseAttempt: 3}},
		total:  1,
	})
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder,
		httptest.NewRequest(http.MethodGet, "/knowledge/knowledge-1/revisions/3/chunks", nil))

	require.Equal(t, http.StatusConflict, recorder.Code)
	require.Equal(t, "revision_manifest_incomplete",
		decodeRevisionResponse(t, recorder)["error"].(map[string]interface{})["code"])
}

func TestDeletedKnowledgeRevisionDoesNotBypassKBACL(t *testing.T) {
	knowledge, _ := revisionFixture(types.ParseStatusCompleted, 3)
	knowledge.DeletedAt = gorm.DeletedAt{Time: time.Unix(20, 0).UTC(), Valid: true}
	router := revisionRouterWithKBTenant(t, &revisionReaderStub{
		states: []revisionStubState{{knowledge: knowledge}},
	}, 99)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder,
		httptest.NewRequest(http.MethodGet, "/knowledge/knowledge-1/revision", nil))

	require.NotEqual(t, http.StatusGone, recorder.Code)
	require.Equal(t, http.StatusForbidden, recorder.Code)
	require.NotContains(t, recorder.Body.String(), "deleted_at")
}

func TestRevisionPaginationStopsOnDeterministicReparseWithoutMixedPage(t *testing.T) {
	knowledge, revision := revisionFixture(types.ParseStatusCompleted, 3)
	revision.ChunkCount = 6
	repo := &revisionReaderStub{
		states: []revisionStubState{{knowledge: knowledge, current: revision, last: revision}},
		total:  6,
	}
	for index := range 6 {
		repo.chunks = append(repo.chunks, &types.Chunk{
			ID: "old-" + string(rune('a'+index)), KnowledgeID: knowledge.ID,
			ParseAttempt: 3, ChunkIndex: index,
		})
	}
	router := revisionRouter(t, repo)
	for page := 1; page <= 2; page++ {
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, httptest.NewRequest(
			http.MethodGet,
			"/knowledge/knowledge-1/revisions/3/chunks?page="+string(rune('0'+page))+"&page_size=2",
			nil,
		))
		require.Equal(t, http.StatusOK, recorder.Code)
		for _, chunk := range decodeRevisionResponse(t, recorder)["data"].([]interface{}) {
			require.Equal(t, float64(3), chunk.(map[string]interface{})["parse_attempt"])
		}
	}

	reparse := *knowledge
	reparse.CurrentParseAttempt = 4
	reparse.ParseStatus = types.ParseStatusPending
	repo.states = []revisionStubState{{knowledge: &reparse, last: revision}}
	repo.calls = 0
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(
		http.MethodGet, "/knowledge/knowledge-1/revisions/3/chunks?page=3&page_size=2", nil,
	))
	require.Equal(t, http.StatusGone, recorder.Code)
	require.Equal(t, "revision_superseded",
		decodeRevisionResponse(t, recorder)["error"].(map[string]interface{})["code"])
}

func TestRevisionPaginationStopsOnDeterministicDelete(t *testing.T) {
	knowledge, revision := revisionFixture(types.ParseStatusCompleted, 3)
	revision.ChunkCount = 3
	repo := &revisionReaderStub{
		states: []revisionStubState{{knowledge: knowledge, current: revision, last: revision}},
		chunks: []*types.Chunk{
			{ID: "c1", KnowledgeID: knowledge.ID, ParseAttempt: 3},
			{ID: "c2", KnowledgeID: knowledge.ID, ParseAttempt: 3},
			{ID: "c3", KnowledgeID: knowledge.ID, ParseAttempt: 3},
		},
		total: 3,
	}
	router := revisionRouter(t, repo)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(
		http.MethodGet, "/knowledge/knowledge-1/revisions/3/chunks?page=1&page_size=2", nil,
	))
	require.Equal(t, http.StatusOK, recorder.Code)

	deleted := *knowledge
	deleted.DeletedAt = gorm.DeletedAt{Time: time.Unix(20, 0).UTC(), Valid: true}
	repo.states = []revisionStubState{{knowledge: &deleted, last: revision}}
	repo.calls = 0
	recorder = httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(
		http.MethodGet, "/knowledge/knowledge-1/revisions/3/chunks?page=2&page_size=2", nil,
	))
	require.Equal(t, http.StatusGone, recorder.Code)
	require.Equal(t, "knowledge_deleted",
		decodeRevisionResponse(t, recorder)["error"].(map[string]interface{})["code"])
}
