package service

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type selectionClassifier struct {
	role    managed.Role
	err     error
	tenants []uint64
}

func (c *selectionClassifier) Classify(_ context.Context, tenant uint64, _ string) (managed.Role, error) {
	c.tenants = append(c.tenants, tenant)
	return c.role, c.err
}

type selectionKBService struct {
	interfaces.KnowledgeBaseService
	kb          *types.KnowledgeBase
	targetReads int
}

func (s *selectionKBService) GetKnowledgeBaseByID(context.Context, string) (*types.KnowledgeBase, error) {
	return s.kb, nil
}
func (s *selectionKBService) GetKnowledgeBaseByIDOnly(context.Context, string) (*types.KnowledgeBase, error) {
	return s.kb, nil
}
func (s *selectionKBService) GetKnowledgeBasesByIDsOnly(context.Context, []string) ([]*types.KnowledgeBase, error) {
	s.targetReads++
	return []*types.KnowledgeBase{s.kb}, nil
}

type selectionDocs struct{ interfaces.KnowledgeService }

func (*selectionDocs) GetKnowledgeBatchWithSharedAccess(context.Context, uint64, []string) ([]*types.Knowledge, error) {
	return []*types.Knowledge{{ID: "doc", KnowledgeBaseID: "library", TenantID: 1}}, nil
}

type selectionModels struct {
	interfaces.ModelService
	err   error
	calls int
}

func (s *selectionModels) ListModels(context.Context) ([]*types.Model, error) {
	s.calls++
	return nil, s.err
}

type selectionTenants struct{ interfaces.TenantService }

func (*selectionTenants) GetTenantByID(context.Context, uint64) (*types.Tenant, error) {
	return &types.Tenant{ID: 1}, nil
}

func TestSessionReadRejectsManagedSelections(t *testing.T) {
	for _, entry := range []string{"qa", "search"} {
		for _, selection := range []string{"kb", "document", "tag"} {
			for _, unavailable := range []bool{false, true} {
				t.Run(entry+"/"+selection+map[bool]string{true: "/unavailable", false: "/managed"}[unavailable], func(t *testing.T) {
					c := &selectionClassifier{role: managed.Role{Kind: managed.KindRaw, State: managed.StatePending}}
					code := managed.ErrorCodeReleaseManaged
					if unavailable {
						c.err = errors.New("private database error")
						code = managed.ErrorCodeClassificationUnavailable
					}
					original := &selectionKBService{kb: &types.KnowledgeBase{ID: "library", TenantID: 1}}
					svc := &sessionService{knowledgeBaseService: managed.DecorateKnowledgeBaseService(original, c), knowledgeService: &selectionDocs{}}
					ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(1))
					req := &types.QARequest{Session: &types.Session{ID: "session", TenantID: 1}, TurnLeaseHeld: true}
					switch selection {
					case "kb":
						req.KnowledgeBaseIDs = []string{"library"}
					case "document":
						req.KnowledgeIDs = []string{"doc"}
					case "tag":
						req.TagScopes = []types.TagScope{{KnowledgeBaseID: "library", TagIDs: []string{"tag"}}}
					}
					var err error
					if entry == "qa" {
						err = svc.KnowledgeQA(ctx, req, nil)
					} else {
						_, err = svc.SearchKnowledge(ctx, req.KnowledgeBaseIDs, req.KnowledgeIDs, req.TagScopes, "query")
					}
					var denial *managed.ReadError
					require.ErrorAs(t, err, &denial)
					require.Equal(t, code, denial.Code)
					require.Zero(t, original.targetReads, "must reject before target building")
					require.Equal(t, []uint64{1}, c.tenants)
				})
			}
		}
	}
}

func TestSessionReadPreservesUnmanagedPath(t *testing.T) {
	sentinel := errors.New("model catalog boundary reached")
	for _, entry := range []string{"qa", "search"} {
		t.Run(entry, func(t *testing.T) {
			c := &selectionClassifier{role: managed.Role{Kind: managed.KindNone, State: managed.StateUnmanaged}}
			original := &selectionKBService{kb: &types.KnowledgeBase{ID: "library", TenantID: 1}}
			models := &selectionModels{err: sentinel}
			svc := &sessionService{cfg: &config.Config{Conversation: &config.ConversationConfig{}}, knowledgeBaseService: managed.DecorateKnowledgeBaseService(original, c), knowledgeService: &selectionDocs{}, modelService: models, tenantService: &selectionTenants{}}
			ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(1))
			ctx = types.WithCaller(ctx, types.Caller{TenantID: 1, UserID: "viewer", Role: types.TenantRoleViewer})
			var err error
			if entry == "qa" {
				err = svc.KnowledgeQA(ctx, &types.QARequest{Session: &types.Session{ID: "session", TenantID: 1}, TurnLeaseHeld: true, KnowledgeBaseIDs: []string{"library"}}, nil)
			} else {
				_, err = svc.SearchKnowledge(ctx, []string{"library"}, nil, nil, "query")
			}
			require.ErrorIs(t, err, sentinel)
			require.Equal(t, 1, models.calls)
			require.Equal(t, []uint64{1}, c.tenants)
		})
	}
}
