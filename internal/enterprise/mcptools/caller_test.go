package mcptools_test

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type lookupKB struct {
	kbs   map[string]*types.KnowledgeBase
	calls []string
}

func (k *lookupKB) GetKnowledgeBaseByIDOnly(_ context.Context, id string) (*types.KnowledgeBase, error) {
	k.calls = append(k.calls, id)
	return k.kbs[id], nil
}

type sharesLookup struct {
	allowed bool
	err     error
}

func (s sharesLookup) CheckTenantKBPermission(
	context.Context, string, uint64, types.TenantRole,
) (types.OrgMemberRole, bool, error) {
	return types.OrgRoleViewer, s.allowed, s.err
}

func authenticatedEndpoint() (context.Context, *types.MCPEndpoint) {
	ep := &types.MCPEndpoint{
		ID: "endpoint", TenantID: tenant, Enabled: true,
		KnowledgeBaseIDs: types.StringArray{"raw", "wiki", "shared"},
		Tools:            types.StringArray{"search_knowledge"},
	}
	ctx := context.WithValue(context.Background(), types.MCPEndpointContextKey, ep)
	ctx = context.WithValue(ctx, types.TenantIDContextKey, tenant)
	ctx = context.WithValue(ctx, types.UserIDContextKey, "mcp-endpoint")
	ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
	ctx = types.WithCaller(ctx, types.Caller{TenantID: tenant, UserID: "mcp-endpoint", Role: types.TenantRoleViewer})
	ctx = types.WithPrincipal(ctx, types.MCPEndpointPrincipal(tenant, ep.ID))
	return types.WithTenantAPIKeyScope(ctx, types.MCPEndpointScope(ep)), ep
}

func TestProductionCallerRequiresConsistentAuthenticatedIdentity(t *testing.T) {
	ctx, _ := authenticatedEndpoint()
	kbs := &lookupKB{}
	resolve := mcptools.EndpointCaller(kbs, nil, nil)
	_, ok := resolve(ctx)
	require.True(t, ok)
	for _, mutation := range []func(context.Context) context.Context{
		func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.TenantIDContextKey, uint64(99))
		},
		func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.PrincipalContextKey, types.MCPEndpointPrincipal(tenant, "other"))
		},
		func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.CallerContextKey, types.Caller{TenantID: 99})
		},
		func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.CallerContextKey, nil)
		},
		func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.UserIDContextKey, "another-user")
		},
		func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.TenantAPIKeyScopeContextKey, types.TenantAPIKeyScope{FullAccess: true})
		},
		func(ctx context.Context) context.Context {
			return context.WithValue(ctx, types.TenantAPIKeyScopeContextKey, nil)
		},
		func(ctx context.Context) context.Context {
			disabled := &types.MCPEndpoint{ID: "endpoint", TenantID: tenant}
			return context.WithValue(ctx, types.MCPEndpointContextKey, disabled)
		},
	} {
		_, ok := resolve(mutation(ctx))
		require.False(t, ok)
	}
	require.Empty(t, kbs.calls, "identity validation must precede KB lookup")
}

func TestProductionCallerRequiresEndpointScopeAndViewerAccessWithoutChangingTenant(t *testing.T) {
	ctx, _ := authenticatedEndpoint()
	kbs := &lookupKB{kbs: map[string]*types.KnowledgeBase{
		"raw": {ID: "raw", TenantID: tenant}, "wiki": {ID: "wiki", TenantID: tenant},
		"outside": {ID: "outside", TenantID: tenant}, "shared": {ID: "shared", TenantID: 88},
	}}
	caller, ok := mcptools.EndpointCaller(kbs, nil, nil)(ctx)
	require.True(t, ok)
	require.True(t, caller.Readable("raw"))
	require.True(t, caller.Readable("wiki"))
	require.False(t, caller.Readable("outside"))
	require.False(t, caller.Readable("shared"))
	require.NotContains(t, kbs.calls, "outside")
	for _, shares := range []sharesLookup{{}, {allowed: true}, {allowed: true, err: errors.New("lookup failed")}} {
		caller, ok = mcptools.EndpointCaller(kbs, shares, nil)(ctx)
		require.True(t, ok)
		require.Equal(t, shares.allowed && shares.err == nil, caller.Readable("shared"))
		actual, _ := types.TenantIDFromContext(ctx)
		require.Equal(t, tenant, actual)
	}
}

type agentShares struct{ allowed bool }

func (a agentShares) GetSharedAgentForTenant(
	context.Context, uint64, types.TenantRole, string, ...uint64,
) (*types.CustomAgent, error) {
	return nil, errors.New("explicit agent is not used")
}

func (a agentShares) TenantCanAccessKBViaSomeSharedAgent(
	context.Context, uint64, types.TenantRole, *types.KnowledgeBase,
) (bool, error) {
	return a.allowed, nil
}

func TestProductionCallerUsesBrowserSharedAgentViewerGrant(t *testing.T) {
	ctx, _ := authenticatedEndpoint()
	kbs := &lookupKB{kbs: map[string]*types.KnowledgeBase{"shared": {ID: "shared", TenantID: 88}}}
	caller, ok := mcptools.EndpointCaller(kbs, nil, agentShares{allowed: true})(ctx)
	require.True(t, ok)
	require.True(t, caller.Readable("shared"))
}
