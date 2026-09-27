package service

import (
	"context"
	"errors"
	"fmt"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"testing"

	agenttools "github.com/Tencent/WeKnora/internal/agent/tools"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestUPGRawOnlyAgentChecksReleaseCustodyBeforeTools(t *testing.T) {
	pinner := &conceptAgentTurnProviderStub830G2{err: errors.New("custody unavailable")}
	svc := &agentService{
		knowledgeBaseService: &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
			"raw": {ID: "raw", TenantID: 1, IndexingStrategy: types.IndexingStrategy{VectorEnabled: true}},
		}},
		conceptAgentTurnProvider830G2: pinner,
	}
	registry := agenttools.NewToolRegistry()
	cfg := &types.AgentConfig{
		AllowedTools:  []string{agenttools.ToolSearchKnowledge, agenttools.ToolReadDocument},
		SearchTargets: types.SearchTargets{{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "raw", TenantID: 1}},
	}
	err := svc.registerTools(context.Background(), registry, cfg, nil, nil, "session")
	require.ErrorContains(t, err, "custody unavailable")
	require.Equal(t, 1, pinner.calls)
	require.Empty(t, registry.ListTools())
}

func TestUPGRawOnlyCustodySurvivesMissingHeadAndPluginOffline(t *testing.T) {
	for _, headPresent := range []bool{true, false} {
		t.Run(fmt.Sprint(headPresent), func(t *testing.T) {
			fixture, _ := conceptReleaseFixture830G2(t)
			db := conceptAgentFixtureDB830G2(t)
			record := &types.WikiReleasePreparation{ID: "frozen-preparation", WikiReleaseScope: fixture.scope}
			require.NoError(t, db.Create(record).Error)
			if headPresent {
				require.NoError(t, db.Create(&types.WikiReleaseHead{WikiReleaseScope: fixture.scope}).Error)
			}
			kbs := &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
				fixture.scope.RawKBID: {ID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID, IndexingStrategy: types.IndexingStrategy{VectorEnabled: true}},
			}}
			reader := NewConceptAgentService830G2(fixture.service, kbs, db)
			ctx := types.WithPrincipal(context.Background(), types.Principal{Type: types.PrincipalWebUser, ID: "viewer"})
			ctx = types.WithExecutionTenant(ctx, fixture.scope.TenantID)
			turn, err := reader.PinConceptAgentTurn830G2(ctx, []interfaces.ConceptAgentKnowledgeScope830G2{{KnowledgeBaseID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID}})
			require.NoError(t, err)
			require.Empty(t, turn.Releases, "raw-only selection does not authorize a Wiki release read")
			require.Equal(t, []string{fixture.scope.RawKBID}, turn.ManagedSourceKBIDs)
			svc := &agentService{knowledgeBaseService: kbs, conceptAgentTurnProvider830G2: reader}
			registry := agenttools.NewToolRegistry()
			cfg := &types.AgentConfig{AllowedTools: []string{agenttools.ToolSearchKnowledge, agenttools.ToolReadDocument, agenttools.ToolListDocuments}, SearchTargets: types.SearchTargets{{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID}}}
			require.NoError(t, svc.registerTools(ctx, registry, cfg, nil, nil, "session"))
			require.Empty(t, registry.ListTools(), "offline plugin must not expose unpublished source through raw tools")
		})
	}
}
