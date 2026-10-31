package service

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

func revisionSourceExact3Fixture(t *testing.T) (
	*KnowledgeRevisionSourceService,
	*revisionSourceRepositoryStub,
	*revisionSourceFileServiceStub,
	KnowledgeRevisionSourceExact3RequestV1,
) {
	t.Helper()
	pdf, err := os.ReadFile(filepath.Join(
		"..", "..", "..", "dataset", "shouxian_product",
		"平安e生保（尊享版）医疗保险", "费率表.pdf",
	))
	require.NoError(t, err)
	fileSHA := fmt.Sprintf("%x", sha256.Sum256(pdf))
	repo := &revisionSourceRepositoryStub{
		states:       map[string]revisionSourceState{},
		snapshotRows: map[string]interfaces.KnowledgeRevisionSourceExact3Authority{},
	}
	resources := &revisionSourceResourceCatalogStub{resources: map[string]*types.StoredResource{}}
	files := &revisionSourceFileServiceStub{dataByPath: map[string][]byte{}}
	request := KnowledgeRevisionSourceExact3RequestV1{
		Contract: KnowledgeRevisionSourceExact3ContractV1,
		Sources:  make([]KnowledgeRevisionSourceExact3ItemV1, 0, 3),
	}
	for index, role := range []string{
		KnowledgeRevisionSourceRoleTerms,
		KnowledgeRevisionSourceRoleBrochure,
		KnowledgeRevisionSourceRoleRateTable,
	} {
		knowledgeID := fmt.Sprintf("knowledge-%d", index+1)
		handle := strings.Repeat(string(rune('a'+index)), types.ResourceHandleLength)
		path := types.BuildResourcePath(handle)
		manifest := strings.Repeat(fmt.Sprintf("%x", index+1), 64)
		knowledge := &types.Knowledge{
			ID: knowledgeID, TenantID: 10003, KnowledgeBaseID: "raw-kb-1",
			ParseStatus: types.ParseStatusCompleted, CurrentParseAttempt: 2,
			FilePath: path, FileSHA256: fileSHA, FileType: "pdf",
		}
		revision := &types.KnowledgeRevision{
			KnowledgeID: knowledgeID, ParseAttempt: 2, FileSHA256: fileSHA,
			ManifestAlgorithm: types.RevisionManifestAlgorithm,
			ManifestDigest:    manifest, ChunkCount: index + 1,
		}
		repo.states[knowledgeID] = revisionSourceState{
			knowledge: knowledge, current: revision, last: revision,
		}
		resources.resources[path] = &types.StoredResource{
			ID: fmt.Sprintf("resource-%d", index+1), Handle: handle, TenantID: 10003,
			Provider: "local", PhysicalPath: fmt.Sprintf("object-%d", index+1),
			MimeType: "application/pdf", Size: int64(len(pdf)), ContentHash: fileSHA,
			Lifecycle: types.ResourceLifecyclePersistent, State: types.ResourceStateActive,
		}
		files.dataByPath[path] = pdf
		repo.snapshotRows[knowledgeID] = interfaces.KnowledgeRevisionSourceExact3Authority{
			Knowledge: knowledge, Current: revision, Last: revision,
			Resource: resources.resources[path], ResourceBindingCount: 1,
		}
		request.Sources = append(request.Sources, KnowledgeRevisionSourceExact3ItemV1{
			Role: role, KnowledgeID: knowledgeID, ParseAttempt: 2,
			ExpectedFileSHA256: fileSHA, ExpectedManifestDigest: manifest,
		})
	}
	service := NewKnowledgeRevisionSourceService(
		&config.Config{KnowledgeRevisionSource: &config.KnowledgeRevisionSourceConfig{
			BackfillEnabled: true, MaxObjectBytes: 2 << 20,
		}},
		repo,
		files,
		resources,
		nil, nil,
	)
	return service, repo, files, request
}

func TestExact3BackfillPreflightsAllSourcesBeforeStrictSerialSeal(t *testing.T) {
	service, repo, _, request := revisionSourceExact3Fixture(t)
	request.DryRun = true

	result, err := service.BackfillExact3(
		revisionSourceContext(), "raw-kb-1", request,
	)
	require.NoError(t, err)
	require.True(t, result.DryRun)
	require.Equal(t, []string{
		KnowledgeRevisionSourceRoleTerms,
		KnowledgeRevisionSourceRoleBrochure,
		KnowledgeRevisionSourceRoleRateTable,
	}, result.ValidatedRoles)
	require.Zero(t, repo.stateCalls, "dry-run database authority must come only from the snapshot")
	require.Equal(t, 1, repo.snapshotCalls)
	require.Zero(t, repo.sealCalls)
	encoded, err := json.Marshal(result)
	require.NoError(t, err)
	var receipt map[string]any
	require.NoError(t, json.Unmarshal(encoded, &receipt))
	require.Equal(t, true, receipt["snapshot_read_only"])
	require.Equal(t, "REPEATABLE_READ", receipt["snapshot_isolation"])
	require.Equal(t, float64(3), receipt["planned_rows"])
	require.Equal(t, float64(0), receipt["duplicate_rows"])
	require.Equal(t, float64(0), receipt["conflict_rows"])
	require.Equal(t, float64(0), receipt["writes"])
	require.NotEmpty(t, receipt["snapshot_sha256"])
	require.NotContains(t, string(encoded), "retention_state")
	require.NotContains(t, string(encoded), "knowledge_id")
	require.NotContains(t, string(encoded), "resource")
	require.NotContains(t, string(encoded), "locator")

	service, repo, _, request = revisionSourceExact3Fixture(t)
	repo.sealErrAt = 2
	result, err = service.BackfillExact3(
		revisionSourceContext(), "raw-kb-1", request,
	)
	require.Nil(t, result)
	var roleErr *KnowledgeRevisionSourceExact3Error
	require.ErrorAs(t, err, &roleErr)
	require.Equal(t, KnowledgeRevisionSourceRoleBrochure, roleErr.FailedRole)
	require.Equal(t, 2, repo.stateCalls, "actual writes must fresh-check only reached serial rows")
	require.Equal(t, 2, repo.sealCalls, "rate_table must not seal after brochure failure")
	require.Equal(t, []string{
		"knowledge-1", "knowledge-2",
	}, []string{repo.sealed[0].KnowledgeID, repo.sealed[1].KnowledgeID})

	service, repo, _, request = revisionSourceExact3Fixture(t)
	request.Sources[1].ExpectedManifestDigest = strings.Repeat("f", 64)
	result, err = service.BackfillExact3(
		revisionSourceContext(), "raw-kb-1", request,
	)
	require.Nil(t, result)
	require.Error(t, err)
	require.Zero(t, repo.sealCalls, "preflight failure must keep all source rows unwritten")
}

func TestExact3DryRunClassifiesExactExistingRowsAndStopsOnConflict(t *testing.T) {
	service, repo, files, request := revisionSourceExact3Fixture(t)
	request.DryRun = true
	for _, item := range request.Sources {
		candidate, err := service.prepareCurrentCompleted(
			revisionSourceContext(), 10003, "raw-kb-1", item.KnowledgeID, item.ParseAttempt,
		)
		require.NoError(t, err)
		row := repo.snapshotRows[item.KnowledgeID]
		row.ExistingSource = &candidate
		repo.snapshotRows[item.KnowledgeID] = row
	}
	files.calls = 0

	result, err := service.BackfillExact3(revisionSourceContext(), "raw-kb-1", request)
	require.NoError(t, err)
	require.Equal(t, 1, repo.snapshotCalls)
	require.Equal(t, 0, result.PlannedRows)
	require.Equal(t, 3, result.DuplicateRows)
	require.Equal(t, 0, result.ConflictRows)
	require.Equal(t, 0, result.Writes)
	for _, source := range result.Sources {
		require.Equal(t, KnowledgeRevisionSourceExact3PlanNoop, source.PlanCode)
		require.NotEmpty(t, source.SourceSHA256)
		require.NotEmpty(t, source.ResultSHA256)
	}
	require.Zero(t, repo.sealCalls)
	repo.source = repo.snapshotRows["knowledge-1"].ExistingSource
	repo.resource = repo.snapshotRows["knowledge-1"].Resource

	row := repo.snapshotRows["knowledge-2"]
	drift := *row.ExistingSource
	drift.BindingDigest = strings.Repeat("f", 64)
	row.ExistingSource = &drift
	repo.snapshotRows["knowledge-2"] = row
	files.calls = 0
	result, err = service.BackfillExact3(revisionSourceContext(), "raw-kb-1", request)
	require.Nil(t, result)
	var conflict *KnowledgeRevisionSourceExact3Error
	require.ErrorAs(t, err, &conflict)
	require.ErrorIs(t, err, ErrRevisionSourceExact3Conflict)
	require.NotNil(t, conflict.Receipt)
	require.Equal(t, 0, conflict.Receipt.PlannedRows)
	require.Equal(t, 1, conflict.Receipt.DuplicateRows)
	require.Equal(t, 1, conflict.Receipt.ConflictRows)
	require.Equal(t, 0, conflict.Receipt.Writes)
	require.Equal(t, KnowledgeRevisionSourceRoleBrochure, conflict.FailedRole)
	require.Equal(t, 2, files.calls, "rate object must not be read after brochure conflict")
	require.Zero(t, repo.sealCalls)
}
