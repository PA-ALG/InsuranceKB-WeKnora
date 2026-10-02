package mcpserver

// S1b acceptance (blueprint 1001 §7.5). Protected file: written by Claude,
// implementers must not edit it. Every MCP read tool resolves its knowledge
// bases through selectKnowledgeBases, so the release-managed policy lives
// there: an explicitly requested managed KB is rejected with the shared error
// code, an unspecified scope silently drops managed KBs, and classification
// failures fail closed.

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type kbRoleClassifier struct {
	roles map[string]managed.Role
	err   error
}

func (c *kbRoleClassifier) Classify(_ context.Context, _ uint64, kbID string) (managed.Role, error) {
	if c.err != nil {
		return managed.Role{}, c.err
	}
	if role, ok := c.roles[kbID]; ok {
		return role, nil
	}
	return managed.Role{Kind: managed.KindNone, State: managed.StateUnmanaged}, nil
}

func managedReadFixture(classifier managed.Classifier) (*Server, *types.MCPEndpoint) {
	srv := newScopeTestServer(
		&types.KnowledgeBase{ID: "kb-managed", TenantID: 1, Name: "Managed"},
		&types.KnowledgeBase{ID: "kb-plain", TenantID: 1, Name: "Plain"},
	)
	srv.WithManagedClassifier(classifier)
	ep := &types.MCPEndpoint{ID: "ep", TenantID: 1, KnowledgeBaseIDs: types.StringArray{"kb-managed", "kb-plain"}}
	return srv, ep
}

func activeManaged() *kbRoleClassifier {
	return &kbRoleClassifier{roles: map[string]managed.Role{
		"kb-managed": {Kind: managed.KindRaw, State: managed.StateActive},
	}}
}

func TestMCPReadRejectsExplicitManagedKB(t *testing.T) {
	srv, ep := managedReadFixture(activeManaged())
	_, err := srv.selectKnowledgeBases(mcpCallContext(1, ep), ep, []string{"kb-managed"})
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(), managed.ErrorCodeReleaseManaged), err.Error())
}

func TestMCPReadDropsManagedKBFromDefaultScope(t *testing.T) {
	srv, ep := managedReadFixture(activeManaged())
	kbs, err := srv.selectKnowledgeBases(mcpCallContext(1, ep), ep, nil)
	require.NoError(t, err)
	require.Len(t, kbs, 1)
	require.Equal(t, "kb-plain", kbs[0].ID)
}

func TestMCPReadExplicitPlainKBStillWorks(t *testing.T) {
	srv, ep := managedReadFixture(activeManaged())
	kbs, err := srv.selectKnowledgeBases(mcpCallContext(1, ep), ep, []string{"kb-plain"})
	require.NoError(t, err)
	require.Len(t, kbs, 1)
	require.Equal(t, "kb-plain", kbs[0].ID)
}

func TestMCPReadPendingManagedKBIsAlsoExcluded(t *testing.T) {
	classifier := &kbRoleClassifier{roles: map[string]managed.Role{
		"kb-managed": {Kind: managed.KindWiki, State: managed.StatePending},
	}}
	srv, ep := managedReadFixture(classifier)
	kbs, err := srv.selectKnowledgeBases(mcpCallContext(1, ep), ep, nil)
	require.NoError(t, err)
	require.Len(t, kbs, 1)
	require.Equal(t, "kb-plain", kbs[0].ID)
}

func TestMCPReadFailsClosedWhenClassificationFails(t *testing.T) {
	srv, ep := managedReadFixture(&kbRoleClassifier{err: errors.New("database unavailable")})
	_, err := srv.selectKnowledgeBases(mcpCallContext(1, ep), ep, nil)
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(), managed.ErrorCodeClassificationUnavailable), err.Error())
}

func TestMCPReadWithoutClassifierFailsClosed(t *testing.T) {
	srv := newScopeTestServer(&types.KnowledgeBase{ID: "kb-plain", TenantID: 1, Name: "Plain"})
	ep := &types.MCPEndpoint{ID: "ep", TenantID: 1, KnowledgeBaseIDs: types.StringArray{"kb-plain"}}
	_, err := srv.selectKnowledgeBases(mcpCallContext(1, ep), ep, nil)
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(), managed.ErrorCodeClassificationUnavailable), err.Error())
}

func TestMCPReadAllManagedLeavesNoKnowledgeBase(t *testing.T) {
	classifier := &kbRoleClassifier{roles: map[string]managed.Role{
		"kb-managed": {Kind: managed.KindRaw, State: managed.StateActive},
		"kb-plain":   {Kind: managed.KindWiki, State: managed.StateActive},
	}}
	srv, ep := managedReadFixture(classifier)
	_, err := srv.selectKnowledgeBases(mcpCallContext(1, ep), ep, nil)
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(), managed.ErrorCodeReleaseManaged), err.Error())
}
