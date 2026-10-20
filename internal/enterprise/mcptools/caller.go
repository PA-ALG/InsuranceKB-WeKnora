package mcptools

import (
	"context"
	"slices"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/access"
	"github.com/Tencent/WeKnora/internal/types"
)

// KnowledgeBases loads authoritative KB ownership before applying Viewer ACLs.
type KnowledgeBases interface {
	GetKnowledgeBaseByIDOnly(context.Context, string) (*types.KnowledgeBase, error)
}

// EndpointCaller accepts only the consistent identity installed by MCP endpoint
// authentication. It never changes the execution tenant or creates a user grant.
func EndpointCaller(
	kbs KnowledgeBases, shares access.KBShareLookup, agents access.AgentShareLookup,
) func(context.Context) (Caller, bool) {
	return func(ctx context.Context) (Caller, bool) {
		ep, caller, ok := endpointIdentity(ctx)
		if !ok || kbs == nil {
			return Caller{}, false
		}
		return Caller{TenantID: caller.TenantID, Readable: func(id string) bool {
			if ctx.Err() != nil || id == "" || !ep.AllowsKnowledgeBase(id) {
				return false
			}
			kb, err := kbs.GetKnowledgeBaseByIDOnly(ctx, id)
			if err != nil || kb == nil || kb.ID != id {
				return false
			}
			_, err = access.ResolveKB(ctx, access.KBRequest{Caller: caller}, kb, types.OrgRoleViewer, shares, agents)
			return err == nil && ctx.Err() == nil
		}}, true
	}
}

func endpointIdentity(ctx context.Context) (*types.MCPEndpoint, types.Caller, bool) {
	if ctx == nil || ctx.Err() != nil {
		return nil, types.Caller{}, false
	}
	ep, ok := ctx.Value(types.MCPEndpointContextKey).(*types.MCPEndpoint)
	if !ok || ep == nil || !ep.Enabled || strings.TrimSpace(ep.ID) == "" || ep.TenantID == 0 {
		return nil, types.Caller{}, false
	}
	tenant, tenantOK := types.TenantIDFromContext(ctx)
	principal, principalOK := ctx.Value(types.PrincipalContextKey).(types.Principal)
	caller, callerOK := ctx.Value(types.CallerContextKey).(types.Caller)
	userID, _ := types.UserIDFromContext(ctx)
	scope, scopeOK := types.TenantAPIKeyScopeFromContext(ctx)
	expected := types.MCPEndpointScope(ep).Normalize()
	if !tenantOK || tenant != ep.TenantID || !principalOK ||
		principal != types.MCPEndpointPrincipal(tenant, ep.ID) || !callerOK || caller.TenantID != tenant ||
		caller.UserID != "mcp-"+ep.ID || userID != caller.UserID || caller.Role != types.TenantRoleViewer ||
		types.TenantRoleFromContext(ctx) != caller.Role || !scopeOK || scope.KeyID != expected.KeyID ||
		scope.Name != expected.Name || scope.ScopeType != expected.ScopeType ||
		scope.FullAccess != expected.FullAccess ||
		!slices.Equal(scope.KnowledgeBaseIDs, expected.KnowledgeBaseIDs) ||
		!slices.Equal(scope.Capabilities, expected.Capabilities) ||
		!scope.HasCapability(types.APIKeyCapabilityRetrieve) {
		return nil, types.Caller{}, false
	}
	return ep, caller, true
}
