package service

import (
	"context"
	"fmt"
	"io"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type revisionSourceRepositoryStub struct {
	interfaces.KnowledgeRepository
	knowledge      *types.Knowledge
	current        *types.KnowledgeRevision
	last           *types.KnowledgeRevision
	source         *types.KnowledgeRevisionSource
	resource       *types.StoredResource
	stateErr       error
	stateCalls     int
	sourceErr      error
	sealErr        error
	sealCalls      int
	captured       types.KnowledgeRevisionSource
	pinned         bool
	pinnedCalls    int
	knowledgeCalls int
	states         map[string]revisionSourceState
	sealErrAt      int
	sealed         []types.KnowledgeRevisionSource
	snapshotCalls  int
	snapshotErr    error
	snapshotRows   map[string]interfaces.KnowledgeRevisionSourceExact3Authority
}

type revisionSourceState struct {
	knowledge *types.Knowledge
	current   *types.KnowledgeRevision
	last      *types.KnowledgeRevision
}

func (s *revisionSourceRepositoryStub) GetKnowledgeByID(
	context.Context, uint64, string,
) (*types.Knowledge, error) {
	s.knowledgeCalls++
	return s.knowledge, s.stateErr
}

func (s *revisionSourceRepositoryStub) GetRevisionState(
	_ context.Context, knowledgeID string,
) (*types.Knowledge, *types.KnowledgeRevision, *types.KnowledgeRevision, error) {
	s.stateCalls++
	if state, ok := s.states[knowledgeID]; ok {
		return state.knowledge, state.current, state.last, s.stateErr
	}
	return s.knowledge, s.current, s.last, s.stateErr
}

func (s *revisionSourceRepositoryStub) GetRevisionSource(
	context.Context, uint64, string, int64,
) (*types.KnowledgeRevisionSource, *types.StoredResource, error) {
	return s.source, s.resource, s.sourceErr
}

func (s *revisionSourceRepositoryStub) WithExact3ReadSnapshot(
	_ context.Context,
	read func(interfaces.KnowledgeRevisionSourceExact3SnapshotReader) error,
) error {
	s.snapshotCalls++
	if s.snapshotErr != nil {
		return s.snapshotErr
	}
	return read(s)
}

func (s *revisionSourceRepositoryStub) GetExact3RevisionSourceAuthority(
	_ context.Context,
	tenantID uint64,
	knowledgeBaseID string,
	knowledgeID string,
	parseAttempt int64,
) (*interfaces.KnowledgeRevisionSourceExact3Authority, error) {
	row, ok := s.snapshotRows[knowledgeID]
	if !ok || row.Knowledge == nil || row.Knowledge.TenantID != tenantID ||
		row.Knowledge.KnowledgeBaseID != knowledgeBaseID || parseAttempt != row.Current.ParseAttempt {
		return nil, repository.ErrKnowledgeNotFound
	}
	rowCopy := row
	return &rowCopy, nil
}

func (s *revisionSourceRepositoryStub) SealRevisionSourceBinding(
	_ context.Context, source types.KnowledgeRevisionSource,
) (*types.KnowledgeRevisionSource, error) {
	s.sealCalls++
	s.captured = source
	s.sealed = append(s.sealed, source)
	if s.sealErr != nil || (s.sealErrAt > 0 && s.sealCalls == s.sealErrAt) {
		if s.sealErr == nil {
			s.sealErr = fmt.Errorf("seal failed")
		}
		return nil, s.sealErr
	}
	sourceCopy := source
	return &sourceCopy, nil
}

func (s *revisionSourceRepositoryStub) HasPinnedRevisionSource(
	context.Context, uint64, string,
) (bool, error) {
	s.pinnedCalls++
	return s.pinned, nil
}

type revisionSourceResourceCatalogStub struct {
	interfaces.ResourceCatalog
	resource  *types.StoredResource
	resources map[string]*types.StoredResource
	err       error
	calls     int
}

func (s *revisionSourceResourceCatalogStub) Resolve(
	_ context.Context, path string,
) (*types.StoredResource, error) {
	s.calls++
	if resource, ok := s.resources[path]; ok {
		return resource, s.err
	}
	return s.resource, s.err
}

func (s *revisionSourceResourceCatalogStub) ResolvePath(
	ctx context.Context, path string,
) (string, *types.StoredResource, error) {
	r, err := s.Resolve(ctx, path)
	if err != nil || r == nil {
		return "", r, err
	}
	return r.PhysicalPath, r, nil
}

type revisionSourceFileServiceStub struct {
	interfaces.FileService
	data       []byte
	dataByPath map[string][]byte
	err        error
	calls      int
	paths      []string
}

func (s *revisionSourceFileServiceStub) GetFile(_ context.Context, path string) (io.ReadCloser, error) {
	s.calls++
	s.paths = append(s.paths, path)
	if s.err != nil {
		return nil, s.err
	}
	if data, ok := s.dataByPath[path]; ok {
		return io.NopCloser(strings.NewReader(string(data))), nil
	}
	return io.NopCloser(strings.NewReader(string(s.data))), nil
}
