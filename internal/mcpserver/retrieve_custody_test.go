package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/stretchr/testify/require"
)

type custodyChunks struct {
	interfaces.ChunkRepository
	reads int
}

func (c *custodyChunks) ListPagedChunksByKnowledgeID(
	context.Context, uint64, string, *types.Pagination, []types.ChunkType,
	[]string, string, string, string, string, *bool,
) ([]*types.Chunk, int64, error) {
	c.reads++
	return nil, 0, nil
}

type custodyChunkService struct {
	interfaces.ChunkService
	repo *custodyChunks
}

func (c *custodyChunkService) GetRepository() interfaces.ChunkRepository { return c.repo }

func TestReadDocumentCustody(t *testing.T) {
	for _, tc := range []struct {
		name    string
		role    managed.Role
		failure error
		code    string
	}{
		{"raw pending", managed.Role{Kind: managed.KindRaw, State: managed.StatePending},
			nil, managed.ErrorCodeReleaseManaged},
		{"wiki active", managed.Role{Kind: managed.KindWiki, State: managed.StateActive},
			nil, managed.ErrorCodeReleaseManaged},
		{"unavailable", managed.Role{}, errors.New("private failure"), managed.ErrorCodeClassificationUnavailable},
		{"plain", managed.Role{Kind: managed.KindNone, State: managed.StateUnmanaged}, nil, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			classifier := &recordingManagedClassifier{role: tc.role, err: tc.failure}
			srv, _, ctx, req := newDocumentWriteFixture(9, classifier, documentWriteCase{
				tool: types.MCPEndpointToolReadDocument, args: map[string]any{"knowledge_id": "document"},
			})
			chunks := &custodyChunks{}
			srv.chunkService = &custodyChunkService{repo: chunks}
			result, err := srv.handleReadDocument(ctx, req)
			require.NoError(t, err)
			require.Equal(t, uint64(9), classifier.tenantID)
			if tc.code != "" {
				require.True(t, result.IsError)
				require.Contains(t, result.Content[0].(mcp.TextContent).Text, tc.code)
				require.Zero(t, chunks.reads)
			} else {
				require.False(t, result.IsError, result)
				require.Positive(t, chunks.reads)
				require.Contains(t, result.Content[0].(mcp.TextContent).Text, "Existing title")
			}
		})
	}
}

func TestListKnowledgeBasesIncludesCustody(t *testing.T) {
	srv, ep := managedReadFixture(activeManaged())
	result, err := srv.handleListKnowledgeBases(mcpCallContext(1, ep), mcp.CallToolRequest{})
	require.NoError(t, err)
	require.False(t, result.IsError)
	var body struct {
		KnowledgeBases []struct {
			ID      string `json:"id"`
			Managed bool   `json:"release_managed"`
		} `json:"knowledge_bases"`
	}
	require.NoError(t, json.Unmarshal([]byte(result.Content[0].(mcp.TextContent).Text), &body))
	got := map[string]bool{}
	for _, kb := range body.KnowledgeBases {
		got[kb.ID] = kb.Managed
	}
	require.Equal(t, map[string]bool{"kb-managed": true, "kb-plain": false}, got)
	srv.WithManagedClassifier(nil)
	result, err = srv.handleListKnowledgeBases(mcpCallContext(1, ep), mcp.CallToolRequest{})
	require.NoError(t, err)
	require.True(t, result.IsError)
	require.Contains(t, result.Content[0].(mcp.TextContent).Text, managed.ErrorCodeClassificationUnavailable)
}
