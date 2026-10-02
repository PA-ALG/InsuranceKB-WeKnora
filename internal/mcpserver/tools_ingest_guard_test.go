package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/stretchr/testify/require"
)

type recordingManagedClassifier struct {
	role     managed.Role
	err      error
	calls    int
	tenantID uint64
	kbID     string
}

func (c *recordingManagedClassifier) Classify(_ context.Context, tenantID uint64, kbID string) (managed.Role, error) {
	c.calls++
	c.tenantID, c.kbID = tenantID, kbID
	return c.role, c.err
}

type documentMutation struct {
	operation string
	tenantID  uint64
	kbID      string
	docID     string
	payload   *types.ManualKnowledgePayload
	url       string
}

type recordingDocumentService struct {
	stubKnowledgeService
	mutations []documentMutation
}

func (s *recordingDocumentService) CreateKnowledgeFromManual(
	ctx context.Context, kbID string, payload *types.ManualKnowledgePayload, _ string,
) (*types.Knowledge, error) {
	s.mutations = append(s.mutations, documentMutation{
		operation: "add_text", tenantID: types.MustTenantIDFromContext(ctx), kbID: kbID, payload: payload,
	})
	return &types.Knowledge{ID: "created", KnowledgeBaseID: kbID, Title: payload.Title}, nil
}

func (s *recordingDocumentService) CreateKnowledgeFromURL(
	ctx context.Context, kbID, url, _, _ string, _ *bool, title string, _ []string, _ string,
	_ *types.KnowledgeProcessOverrides,
) (*types.Knowledge, error) {
	s.mutations = append(s.mutations, documentMutation{
		operation: "add_url", tenantID: types.MustTenantIDFromContext(ctx), kbID: kbID, url: url,
	})
	return &types.Knowledge{ID: "created", KnowledgeBaseID: kbID, Title: title}, nil
}

func (s *recordingDocumentService) UpdateManualKnowledge(
	ctx context.Context, id string, payload *types.ManualKnowledgePayload,
) (*types.Knowledge, error) {
	s.mutations = append(s.mutations, documentMutation{
		operation: "update", tenantID: types.MustTenantIDFromContext(ctx), docID: id, payload: payload,
	})
	return &types.Knowledge{ID: id, Title: payload.Title}, nil
}

func (s *recordingDocumentService) DeleteKnowledge(ctx context.Context, id string) error {
	s.mutations = append(s.mutations, documentMutation{
		operation: "delete", tenantID: types.MustTenantIDFromContext(ctx), docID: id,
	})
	return nil
}

type documentWriteCase struct {
	name    string
	tool    string
	handler func(*Server, context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error)
	args    map[string]any
}

func documentWriteCases() []documentWriteCase {
	return []documentWriteCase{
		{"add_text", types.MCPEndpointToolAddDocument, (*Server).handleAddDocument, map[string]any{
			"knowledge_base_id": "Owner library", "title": "New document", "content": "Updated body", "publish": false,
		}},
		{"add_url", types.MCPEndpointToolAddDocument, (*Server).handleAddDocument, map[string]any{
			"knowledge_base_id": "Owner library", "title": "Imported document", "url": "https://example.com/source",
		}},
		{"update", types.MCPEndpointToolUpdateDocument, (*Server).handleUpdateDocument, map[string]any{
			"knowledge_id": "document", "content": "Updated body", "publish": false,
		}},
		{"delete", types.MCPEndpointToolDeleteDocument, (*Server).handleDeleteDocument, map[string]any{
			"knowledge_id": "document",
		}},
	}
}

func newDocumentWriteFixture(
	ownerTenantID uint64, classifier managed.Classifier, write documentWriteCase,
) (*Server, *recordingDocumentService, context.Context, mcp.CallToolRequest) {
	kb := &types.KnowledgeBase{ID: "owner-kb", TenantID: ownerTenantID, Name: "Owner library"}
	srv := newScopeTestServer(kb)
	srv.WithManagedClassifier(classifier)
	srv.kbShareService = &stubKBShareService{shared: map[string]types.OrgMemberRole{kb.ID: types.OrgRoleEditor}}
	srv.tenantService = &stubTenantService{tenants: map[uint64]*types.Tenant{ownerTenantID: {ID: ownerTenantID}}}
	docs := &recordingDocumentService{stubKnowledgeService: stubKnowledgeService{docs: map[string]*types.Knowledge{
		"document": {ID: "document", TenantID: ownerTenantID, KnowledgeBaseID: kb.ID, Title: "Existing title"},
	}}}
	srv.knowledgeService = docs
	ep := &types.MCPEndpoint{
		ID: "endpoint", TenantID: 1, KnowledgeBaseIDs: types.StringArray{kb.ID}, Tools: types.StringArray{write.tool},
	}
	if ownerTenantID == 0 {
		// An unrestricted malformed tenant context still resolves the target,
		// so the write guard must reject before ordinary write authorization.
		ep.TenantID, ep.KnowledgeBaseIDs = 0, nil
	}
	req := mcp.CallToolRequest{}
	req.Params.Name, req.Params.Arguments = write.tool, write.args
	return srv, docs, mcpCallContext(ep.TenantID, ep), req
}

func TestMCPDocumentWritesRejectManagedKnowledgeBases(t *testing.T) {
	for _, kind := range []managed.Kind{managed.KindWiki, managed.KindRaw} {
		for _, state := range []managed.State{managed.StatePending, managed.StateActive} {
			for _, write := range documentWriteCases() {
				for _, permission := range []types.OrgMemberRole{types.OrgRoleEditor, types.OrgRoleViewer} {
					t.Run(string(kind)+"/"+string(state)+"/"+write.name+"/"+string(permission), func(t *testing.T) {
						classifier := &recordingManagedClassifier{role: managed.Role{Kind: kind, State: state}}
						srv, docs, ctx, req := newDocumentWriteFixture(2, classifier, write)
						// Managed denial must also precede the write permission check
						// when a viewer share can only resolve the target for reading.
						srv.kbShareService = &stubKBShareService{shared: map[string]types.OrgMemberRole{
							"owner-kb": permission,
						}}
						result, err := write.handler(srv, ctx, req)
						require.NoError(t, err)
						require.True(t, result.IsError)
						require.Contains(t, result.Content[0].(mcp.TextContent).Text, managed.ErrorCodeReleaseManaged)
						require.Empty(t, docs.mutations, "managed denial must not mutate document content or indexes")
						require.Equal(t, 1, classifier.calls)
						require.Equal(t, uint64(2), classifier.tenantID, "classify the shared KB's owner tenant")
						require.Equal(t, "owner-kb", classifier.kbID, "classify the resolved ID, not the name selector")
					})
				}
			}
		}
	}
}

func TestMCPDocumentWritesFailClosed(t *testing.T) {
	for _, failure := range []string{"classification_error", "missing_classifier", "missing_tenant"} {
		for _, write := range documentWriteCases() {
			t.Run(failure+"/"+write.name, func(t *testing.T) {
				classifier := &recordingManagedClassifier{role: managed.Role{
					Kind: managed.KindNone, State: managed.StateUnmanaged,
				}}
				var dependency managed.Classifier = classifier
				ownerTenantID := uint64(2)
				switch failure {
				case "classification_error":
					classifier.err = errors.New("classification unavailable")
				case "missing_classifier":
					dependency = nil
				case "missing_tenant":
					ownerTenantID = 0
				}
				srv, docs, ctx, req := newDocumentWriteFixture(ownerTenantID, dependency, write)
				result, err := write.handler(srv, ctx, req)
				require.NoError(t, err)
				require.True(t, result.IsError)
				require.Contains(t, result.Content[0].(mcp.TextContent).Text,
					managed.ErrorCodeClassificationUnavailable)
				require.Empty(t, docs.mutations, "an unavailable classification must not allow writes")
			})
		}
	}
}

func TestMCPDocumentWritesPreserveUnmanagedBehavior(t *testing.T) {
	for _, write := range documentWriteCases() {
		t.Run(write.name, func(t *testing.T) {
			classifier := &recordingManagedClassifier{role: managed.Role{
				Kind: managed.KindNone, State: managed.StateUnmanaged,
			}}
			srv, docs, ctx, req := newDocumentWriteFixture(2, classifier, write)
			result, err := write.handler(srv, ctx, req)
			require.NoError(t, err)
			require.False(t, result.IsError)
			require.Len(t, docs.mutations, 1)
			mutation := docs.mutations[0]
			require.Equal(t, write.name, mutation.operation)
			require.Equal(t, uint64(2), mutation.tenantID, "retain the owner-scoped write context")
			require.Equal(t, uint64(2), classifier.tenantID)
			require.Equal(t, "owner-kb", classifier.kbID)
			var body map[string]any
			require.NoError(t, json.Unmarshal([]byte(result.Content[0].(mcp.TextContent).Text), &body))
			switch write.name {
			case "add_text":
				require.Equal(t, "owner-kb", body["knowledge_base_id"])
				require.Equal(t, "owner-kb", mutation.kbID)
				require.Equal(t, "New document", mutation.payload.Title)
			case "add_url":
				require.Equal(t, "owner-kb", body["knowledge_base_id"])
				require.Equal(t, "owner-kb", mutation.kbID)
				require.Equal(t, "https://example.com/source", mutation.url)
			case "update":
				require.Equal(t, "document", mutation.docID)
				require.Equal(t, "Existing title", mutation.payload.Title,
					"an omitted title preserves the current title")
			case "delete":
				require.Equal(t, "document", mutation.docID)
				require.Equal(t, true, body["deleted"])
				require.Equal(t, "document", body["knowledge_id"])
			}
			if mutation.payload != nil {
				require.Equal(t, "Updated body", mutation.payload.Content)
				require.Equal(t, types.ManualKnowledgeStatusDraft, mutation.payload.Status)
				require.Equal(t, askChannel, mutation.payload.Channel)
			}
		})
	}
}

func TestMCPServerReceivesManagedClassifier(t *testing.T) {
	classifier := &recordingManagedClassifier{}
	srv := NewServer(nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil)
	require.Same(t, srv, srv.WithManagedClassifier(classifier))
	require.Same(t, classifier, srv.managedClassifier)
}
