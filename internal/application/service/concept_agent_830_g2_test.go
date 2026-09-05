package service

import (
	"context"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	agenttools "github.com/Tencent/WeKnora/internal/agent/tools"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func conceptAgentFixtureDB830G2(t *testing.T) *gorm.DB {
	t.Helper()
	name := strings.NewReplacer("/", "-", " ", "-").Replace(t.Name())
	db, err := gorm.Open(sqlite.Open("file:"+name+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	return db
}

func activateConceptAgentRelease830G2(
	t *testing.T,
	fixture *wikiReleaseFixture,
	schema *SchemaWikiService,
) *types.WikiReleaseReceipt {
	t.Helper()
	draft, err := schema.CreateConceptFreeWikiDraft830G2(
		fixture.ctx, fixture.principal1, fixture.scope, "agent-g2-preparation", conceptBundleVector830G2(t),
	)
	require.NoError(t, err)
	fixture.service.humanDecisionVerifier = NewEd25519HumanBatchDecisionVerifier(
		map[string]ed25519.PublicKey{"human-1": fixture.privateKey.Public().(ed25519.PublicKey)},
	)
	decision := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: fixture.principal1.ID,
		WikiReleaseScope: fixture.scope, CandidateHash: draft.CandidateDigest,
		HumanBatchHash: draft.ReadyReceiptDigest, ReviewPolicyHash: draft.ReviewPolicyID,
		IssuedAt: 1_000, ExpiresAt: 2_000, Nonce: "agent-g2-review", SignerKeyID: "human-1",
	}
	unsignedDecision, err := CanonicalHumanBatchDecisionReceiptV1(decision, false)
	require.NoError(t, err)
	decision.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsignedDecision))
	rawDecision, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	require.NoError(t, err)
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	authorization := &types.PublishAuthorizationV0{
		Version: "0", Action: "activate", PreparationID: ready.ID,
		CandidateDigest: ready.CandidateDigest, ManifestDigest: ready.ManifestDigest,
		ReadyReceiptDigest: ready.ReadyReceiptDigest, ReviewDecisionDigest: ready.ReviewDecisionDigest,
		ReviewPolicyID: ready.ReviewPolicyID, TenantID: fixture.scope.TenantID,
		SpaceID: fixture.scope.SpaceID, RawKBID: fixture.scope.RawKBID, WikiKBID: fixture.scope.WikiKBID,
		ExpectedReleaseID: ready.ExpectedReleaseID, ExpectedActivationEpoch: ready.ExpectedActivationEpoch,
		ExpiresAt: 2_000, Nonce: "agent-g2-review", SignerKeyID: "signer-1",
	}
	unsignedAuthorization, err := CanonicalPublishAuthorizationV0(authorization, false)
	require.NoError(t, err)
	authorization.Signature = EncodeWikiReleaseSignature(ed25519.Sign(fixture.privateKey, unsignedAuthorization))
	rawAuthorization, err := CanonicalPublishAuthorizationV0(authorization, true)
	require.NoError(t, err)
	receipt, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision, rawAuthorization,
	)
	require.NoError(t, err)
	return receipt
}

type conceptAgentTurnProviderStub830G2 struct {
	turn   *interfaces.ConceptAgentTurn830G2
	err    error
	calls  int
	scopes []interfaces.ConceptAgentWikiScope830G2
}

func (s *conceptAgentTurnProviderStub830G2) PinConceptAgentTurn830G2(
	_ context.Context,
	scopes []interfaces.ConceptAgentWikiScope830G2,
) (*interfaces.ConceptAgentTurn830G2, error) {
	s.calls++
	s.scopes = append([]interfaces.ConceptAgentWikiScope830G2(nil), scopes...)
	return s.turn, s.err
}

type conceptAgentKBServiceStub830G2 struct {
	interfaces.KnowledgeBaseService
	kbs map[string]*types.KnowledgeBase
}

func (s *conceptAgentKBServiceStub830G2) GetKnowledgeBaseByIDOnly(
	_ context.Context,
	id string,
) (*types.KnowledgeBase, error) {
	kb := s.kbs[id]
	if kb == nil {
		return nil, errors.New("knowledge base not found")
	}
	return kb, nil
}

type conceptAgentMutableWikiStub830G2 struct {
	interfaces.WikiPageService
	searchCalls int
	readCalls   int
}

func (s *conceptAgentMutableWikiStub830G2) SearchPages(
	context.Context,
	string,
	string,
	int,
) ([]*types.WikiPage, error) {
	s.searchCalls++
	return []*types.WikiPage{{Slug: "mutable-candidate", Content: "mutable candidate"}}, nil
}

func (s *conceptAgentMutableWikiStub830G2) GetPageBySlug(
	context.Context,
	string,
	string,
) (*types.WikiPage, error) {
	s.readCalls++
	return &types.WikiPage{Slug: "concept-a", Content: "mutable candidate"}, nil
}

func conceptAgentPinnedTurnStub830G2() *interfaces.ConceptAgentTurn830G2 {
	return &interfaces.ConceptAgentTurn830G2{Releases: map[string]interfaces.ConceptAgentRelease830G2{
		"wiki-a": {
			WikiKBID: "wiki-a", SpaceID: "space-a", RawKBID: "raw-a",
			ReleaseID: "release-a", ActivationEpoch: 3,
			Members: []interfaces.ConceptAgentMember830G2{{
				Kind: "concept", MemberID: "concept-a", OwnerID: "space-a",
				Title: "Concept A", Content: "body-only release phrase", MemberDigest: "digest-a",
			}},
		},
	}}
}

func TestRegisterToolsPinsManagedWikiOnceAndRemovesRawFallback(t *testing.T) {
	pinner := &conceptAgentTurnProviderStub830G2{turn: conceptAgentPinnedTurnStub830G2()}
	mutable := &conceptAgentMutableWikiStub830G2{}
	service := &agentService{
		knowledgeBaseService: &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
			"wiki-a": {
				ID: "wiki-a", TenantID: 1,
				IndexingStrategy: types.IndexingStrategy{WikiEnabled: true, VectorEnabled: true},
			},
		}},
		wikiPageService:               mutable,
		conceptAgentTurnProvider830G2: pinner,
	}
	registry := agenttools.NewToolRegistry()
	config := &types.AgentConfig{
		AllowedTools: []string{
			agenttools.ToolWikiSearch,
			agenttools.ToolWikiReadPage,
			agenttools.ToolWikiReadSourceDoc,
			agenttools.ToolKnowledgeSearch,
		},
		SearchTargets: types.SearchTargets{{
			Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "wiki-a", TenantID: 1,
		}},
	}

	require.NoError(t, service.registerTools(context.Background(), registry, config, nil, nil, "session-a"))
	require.Equal(t, 1, pinner.calls, "search and read must share one turn pin")
	require.Equal(t, []interfaces.ConceptAgentWikiScope830G2{{WikiKBID: "wiki-a", TenantID: 1}}, pinner.scopes)
	_, err := registry.GetTool(agenttools.ToolWikiReadSourceDoc)
	require.Error(t, err, "managed Wiki must not register a RAW source reader")
	_, err = registry.GetTool(agenttools.ToolKnowledgeSearch)
	require.Error(t, err, "managed Wiki must not register mutable/RAG retrieval")

	search, err := registry.GetTool(agenttools.ToolWikiSearch)
	require.NoError(t, err)
	searchResult, err := search.Execute(context.Background(), json.RawMessage(`{"queries":["body-only release phrase"]}`))
	require.NoError(t, err)
	require.True(t, searchResult.Success)
	require.Contains(t, searchResult.Output, "release-a")

	read, err := registry.GetTool(agenttools.ToolWikiReadPage)
	require.NoError(t, err)
	readResult, err := read.Execute(context.Background(), json.RawMessage(`{"slugs":["concept-a"]}`))
	require.NoError(t, err)
	require.True(t, readResult.Success)
	require.Contains(t, readResult.Output, "activation_epoch=\"3\"")
	require.Zero(t, mutable.searchCalls)
	require.Zero(t, mutable.readCalls)
}

func TestRegisterToolsFailsClosedWhenManagedPinFails(t *testing.T) {
	pinner := &conceptAgentTurnProviderStub830G2{err: errors.New("pin integrity failed")}
	mutable := &conceptAgentMutableWikiStub830G2{}
	service := &agentService{
		knowledgeBaseService: &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
			"wiki-a": {ID: "wiki-a", TenantID: 1, IndexingStrategy: types.IndexingStrategy{WikiEnabled: true}},
		}},
		wikiPageService:               mutable,
		conceptAgentTurnProvider830G2: pinner,
	}
	registry := agenttools.NewToolRegistry()
	config := &types.AgentConfig{
		AllowedTools: []string{agenttools.ToolWikiSearch, agenttools.ToolWikiReadPage, agenttools.ToolWikiReadSourceDoc},
		SearchTargets: types.SearchTargets{{
			Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "wiki-a", TenantID: 1,
		}},
	}

	err := service.registerTools(context.Background(), registry, config, nil, nil, "session-a")
	require.ErrorContains(t, err, "pin integrity failed")
	require.Empty(t, registry.ListTools())
	require.Zero(t, mutable.searchCalls)
	require.Zero(t, mutable.readCalls)
}

func TestRegisterToolsRejectsWikiSearchTargetTenantDrift(t *testing.T) {
	pinner := &conceptAgentTurnProviderStub830G2{turn: conceptAgentPinnedTurnStub830G2()}
	service := &agentService{
		knowledgeBaseService: &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
			"wiki-a": {ID: "wiki-a", TenantID: 1, IndexingStrategy: types.IndexingStrategy{WikiEnabled: true}},
		}},
		conceptAgentTurnProvider830G2: pinner,
	}
	config := &types.AgentConfig{
		AllowedTools: []string{agenttools.ToolWikiSearch},
		SearchTargets: types.SearchTargets{{
			Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "wiki-a", TenantID: 2,
		}},
	}

	err := service.registerTools(context.Background(), agenttools.NewToolRegistry(), config, nil, nil, "session-a")
	require.ErrorContains(t, err, "tenant does not match")
	require.Zero(t, pinner.calls)
}

func TestRegisterToolsExcludesManagedReleaseRawKBFromGenericRetrieval(t *testing.T) {
	pinner := &conceptAgentTurnProviderStub830G2{turn: conceptAgentPinnedTurnStub830G2()}
	service := &agentService{
		knowledgeBaseService: &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
			"wiki-a": {ID: "wiki-a", TenantID: 1, IndexingStrategy: types.IndexingStrategy{WikiEnabled: true}},
			"raw-a":  {ID: "raw-a", TenantID: 1, IndexingStrategy: types.IndexingStrategy{VectorEnabled: true}},
		}},
		conceptAgentTurnProvider830G2: pinner,
	}
	registry := agenttools.NewToolRegistry()
	config := &types.AgentConfig{
		AllowedTools: []string{agenttools.ToolWikiSearch, agenttools.ToolKnowledgeSearch},
		SearchTargets: types.SearchTargets{
			{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "wiki-a", TenantID: 1},
			{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "raw-a", TenantID: 1},
		},
	}

	require.NoError(t, service.registerTools(context.Background(), registry, config, nil, nil, "session-a"))
	_, err := registry.GetTool(agenttools.ToolKnowledgeSearch)
	require.Error(t, err, "managed release RAW KB must not remain in generic retrieval")
}

func TestRegisterToolsFailsClosedWhenManagedWikiProviderIsMissing(t *testing.T) {
	service := &agentService{
		knowledgeBaseService: &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
			"wiki-a": {ID: "wiki-a", TenantID: 1, IndexingStrategy: types.IndexingStrategy{WikiEnabled: true}},
		}},
	}
	registry := agenttools.NewToolRegistry()
	config := &types.AgentConfig{
		AllowedTools: []string{agenttools.ToolWikiSearch},
		SearchTargets: types.SearchTargets{{
			Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "wiki-a", TenantID: 1,
		}},
	}

	err := service.registerTools(context.Background(), registry, config, nil, nil, "session-a")
	require.ErrorContains(t, err, "release service unavailable")
	require.Empty(t, registry.ListTools())
}

func TestRegisterToolsPreservesUnmanagedWikiPath(t *testing.T) {
	pinner := &conceptAgentTurnProviderStub830G2{turn: &interfaces.ConceptAgentTurn830G2{}}
	mutable := &conceptAgentMutableWikiStub830G2{}
	service := &agentService{
		knowledgeBaseService: &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
			"wiki-a": {ID: "wiki-a", TenantID: 1, IndexingStrategy: types.IndexingStrategy{WikiEnabled: true}},
		}},
		wikiPageService:               mutable,
		conceptAgentTurnProvider830G2: pinner,
	}
	registry := agenttools.NewToolRegistry()
	config := &types.AgentConfig{
		AllowedTools: []string{agenttools.ToolWikiSearch},
		SearchTargets: types.SearchTargets{{
			Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: "wiki-a", TenantID: 1,
		}},
	}

	require.NoError(t, service.registerTools(context.Background(), registry, config, nil, nil, "session-a"))
	search, err := registry.GetTool(agenttools.ToolWikiSearch)
	require.NoError(t, err)
	result, err := search.Execute(context.Background(), json.RawMessage(`{"queries":["candidate"]}`))
	require.NoError(t, err)
	require.True(t, result.Success)
	require.Equal(t, 1, pinner.calls)
	require.Equal(t, 1, mutable.searchCalls)
}

func TestConceptAgentServicePinsValidatedReleaseAndSourceIdentity(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	receipt := activateConceptAgentRelease830G2(t, fixture, schema)
	kbs := &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
		fixture.scope.WikiKBID: {ID: fixture.scope.WikiKBID, TenantID: fixture.scope.TenantID},
		fixture.scope.RawKBID:  {ID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID},
	}}
	reader := NewConceptAgentService830G2(fixture.service, kbs, conceptAgentFixtureDB830G2(t))
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "agent-viewer"}
	ctx := context.WithValue(
		types.WithPrincipal(context.Background(), principal),
		types.TenantIDContextKey,
		fixture.scope.TenantID,
	)
	fixture.access.allowed[principal.StorageID()] = fixture.scope

	turn, err := reader.PinConceptAgentTurn830G2(ctx, conceptAgentWikiScopes830G2(fixture.scope))
	require.NoError(t, err)
	release, ok := turn.Releases[fixture.scope.WikiKBID]
	require.True(t, ok)
	require.Equal(t, receipt.ReleaseID, release.ReleaseID)
	require.Equal(t, receipt.ActivationEpoch, release.ActivationEpoch)
	require.Len(t, release.Members, 6)
	var sourced *interfaces.ConceptAgentMember830G2
	for index := range release.Members {
		if len(release.Members[index].Sources) > 0 {
			sourced = &release.Members[index]
			break
		}
	}
	require.NotNil(t, sourced)
	require.NotEmpty(t, sourced.MemberDigest)
	require.Equal(t, "knowledge-a", sourced.Sources[0].KnowledgeID)
	require.Equal(t, "r1", sourced.Sources[0].RevisionID)
}

func TestConceptAgentServiceKeepsCurrentG1ReleaseImmutable(t *testing.T) {
	fixture := newEntityPageGraphSuccessorFixture830G1(t)
	kbs := &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
		fixture.scope.WikiKBID: {ID: fixture.scope.WikiKBID, TenantID: fixture.scope.TenantID},
		fixture.scope.RawKBID:  {ID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID},
	}}
	reader := NewConceptAgentService830G2(fixture.service.releaseAuthority, kbs, fixture.db)
	ctx := context.WithValue(
		types.WithPrincipal(fixture.ctx, types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}),
		types.TenantIDContextKey,
		fixture.scope.TenantID,
	)

	turn, err := reader.PinConceptAgentTurn830G2(ctx, conceptAgentWikiScopes830G2(fixture.scope))
	require.NoError(t, err)
	release, ok := turn.Releases[fixture.scope.WikiKBID]
	require.True(t, ok)
	require.Equal(t, fixture.successorID, release.ReleaseID)
	require.Equal(t, fixture.manifest.ActivationEpoch+1, release.ActivationEpoch)
	require.Len(t, release.Members, len(fixture.manifest.Members))
	require.NotEmpty(t, release.Members[0].Content)
	for _, member := range fixture.manifest.Members {
		if member.PageKind != "field" {
			continue
		}
		payload, payloadErr := member.FieldAssertionPayload()
		require.NoError(t, payloadErr)
		if len(payload.Citations) == 0 {
			continue
		}
		for _, projected := range release.Members {
			if projected.MemberID != member.PageID {
				continue
			}
			require.NotEmpty(t, projected.Sources)
			require.Equal(t, payload.Citations[0].LocatorRef, projected.Sources[0].BlockID)
			require.Equal(t, payload.Citations[0].ParseManifestSHA256, projected.Sources[0].ParseHash)
			require.Equal(t, schemaWikiStringSHA256(payload.Citations[0].QuoteSnapshot), projected.Sources[0].QuoteHash)
			return
		}
	}
	t.Fatal("G1 fixture has no cited field projection")
}

func TestConceptAgentServiceRejectsManagedReleaseWhenRawKBOwnershipDrifts(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	activateConceptAgentRelease830G2(t, fixture, schema)
	kbs := &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
		fixture.scope.WikiKBID: {ID: fixture.scope.WikiKBID, TenantID: fixture.scope.TenantID},
		fixture.scope.RawKBID:  {ID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID + 1},
	}}
	reader := NewConceptAgentService830G2(fixture.service, kbs, conceptAgentFixtureDB830G2(t))
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "agent-viewer"}
	ctx := context.WithValue(
		types.WithPrincipal(context.Background(), principal),
		types.TenantIDContextKey,
		fixture.scope.TenantID,
	)
	fixture.access.allowed[principal.StorageID()] = fixture.scope

	_, err := reader.PinConceptAgentTurn830G2(ctx, conceptAgentWikiScopes830G2(fixture.scope))
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
}

func TestConceptAgentServiceCannotMintCrossTenantAccessProof(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	activateConceptAgentRelease830G2(t, fixture, schema)
	fixture.service.accessVerifier = NewContextWikiReleaseAccessVerifier()
	kbs := &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
		fixture.scope.WikiKBID: {ID: fixture.scope.WikiKBID, TenantID: fixture.scope.TenantID},
		fixture.scope.RawKBID:  {ID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID},
	}}
	reader := NewConceptAgentService830G2(fixture.service, kbs, conceptAgentFixtureDB830G2(t))
	ctx := context.WithValue(
		types.WithPrincipal(context.Background(), types.Principal{Type: types.PrincipalWebUser, ID: "foreign-viewer"}),
		types.TenantIDContextKey,
		uint64(99),
	)

	_, err := reader.PinConceptAgentTurn830G2(ctx, conceptAgentWikiScopes830G2(fixture.scope))
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
}

func TestConceptAgentServiceLeavesUnmanagedCrossTenantWikiOnLegacyPath(t *testing.T) {
	fixture := newWikiReleaseFixture(t, WikiReleaseFaults{})
	fixture.service.accessVerifier = NewContextWikiReleaseAccessVerifier()
	kbs := &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
		fixture.scope.WikiKBID: {ID: fixture.scope.WikiKBID, TenantID: fixture.scope.TenantID},
	}}
	reader := NewConceptAgentService830G2(fixture.service, kbs, conceptAgentFixtureDB830G2(t))
	ctx := context.WithValue(
		types.WithPrincipal(context.Background(), types.Principal{Type: types.PrincipalWebUser, ID: "foreign-viewer"}),
		types.TenantIDContextKey,
		uint64(99),
	)

	turn, err := reader.PinConceptAgentTurn830G2(ctx, conceptAgentWikiScopes830G2(fixture.scope))
	require.NoError(t, err)
	require.Empty(t, turn.Releases)
}

func TestConceptAgentServiceDoesNotFallbackWhenManagedHeadIsMissing(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	activateConceptAgentRelease830G2(t, fixture, schema)
	db := conceptAgentFixtureDB830G2(t)
	require.NoError(t, db.Where("tenant_id = ? AND wiki_kb_id = ?", fixture.scope.TenantID, fixture.scope.WikiKBID).
		Delete(&types.WikiReleaseHead{}).Error)
	kbs := &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
		fixture.scope.WikiKBID: {ID: fixture.scope.WikiKBID, TenantID: fixture.scope.TenantID},
		fixture.scope.RawKBID:  {ID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID},
	}}
	reader := NewConceptAgentService830G2(fixture.service, kbs, db)
	ctx := context.WithValue(
		types.WithPrincipal(context.Background(), types.Principal{Type: types.PrincipalWebUser, ID: "agent-viewer"}),
		types.TenantIDContextKey,
		fixture.scope.TenantID,
	)

	_, err := reader.PinConceptAgentTurn830G2(ctx, conceptAgentWikiScopes830G2(fixture.scope))
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
}

func TestConceptAgentServiceRejectsHeadActivationEpochDrift(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	activateConceptAgentRelease830G2(t, fixture, schema)
	db := conceptAgentFixtureDB830G2(t)
	require.NoError(t, db.Model(&types.WikiReleaseHead{}).
		Where("tenant_id = ? AND wiki_kb_id = ?", fixture.scope.TenantID, fixture.scope.WikiKBID).
		Update("activation_epoch", 9).Error)
	kbs := &conceptAgentKBServiceStub830G2{kbs: map[string]*types.KnowledgeBase{
		fixture.scope.WikiKBID: {ID: fixture.scope.WikiKBID, TenantID: fixture.scope.TenantID},
		fixture.scope.RawKBID:  {ID: fixture.scope.RawKBID, TenantID: fixture.scope.TenantID},
	}}
	reader := NewConceptAgentService830G2(fixture.service, kbs, db)
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "agent-viewer"}
	ctx := context.WithValue(
		types.WithPrincipal(context.Background(), principal),
		types.TenantIDContextKey,
		fixture.scope.TenantID,
	)
	fixture.access.allowed[principal.StorageID()] = fixture.scope

	_, err := reader.PinConceptAgentTurn830G2(ctx, conceptAgentWikiScopes830G2(fixture.scope))
	require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
}

func conceptAgentWikiScopes830G2(scope types.WikiReleaseScope) []interfaces.ConceptAgentWikiScope830G2 {
	return []interfaces.ConceptAgentWikiScope830G2{{WikiKBID: scope.WikiKBID, TenantID: scope.TenantID}}
}
