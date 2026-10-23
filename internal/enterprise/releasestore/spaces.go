// Package releasestore persists generic candidates and decisions and publishes
// releases through the existing wiki_release_* Head authority (S4c-2a Spec §3.2).
package releasestore

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// Space binds one enterprise Space to the knowledge bases its releases cover.
type Space struct {
	TenantID uint64 `json:"tenant_id"`
	SpaceID  string `json:"space_id"`
	RawKBID  string `json:"raw_kb_id"`
	WikiKBID string `json:"wiki_kb_id"`
}

// Spaces is the configured set of enterprise Spaces. It is deployment
// configuration until managed Spaces get a persistent binding (S4c-2c).
type Spaces struct {
	byKey map[string]types.WikiReleaseScope
}

// ParseSpaces decodes the ENTERPRISE_SPACES JSON list. Every Space must be complete and
// unique, and no knowledge base may serve two roles.
func ParseSpaces(raw string) (Spaces, error) {
	spaces := Spaces{byKey: map[string]types.WikiReleaseScope{}}
	if strings.TrimSpace(raw) == "" {
		return spaces, nil
	}
	var entries []Space
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&entries); err != nil {
		return Spaces{}, fmt.Errorf("ENTERPRISE_SPACES is not a JSON list of spaces: %w", err)
	}
	knowledgeBases := map[string]bool{}
	for i, e := range entries {
		if e.TenantID == 0 || strings.TrimSpace(e.SpaceID) == "" || strings.TrimSpace(e.RawKBID) == "" ||
			strings.TrimSpace(e.WikiKBID) == "" || e.RawKBID == e.WikiKBID {
			return Spaces{}, fmt.Errorf("ENTERPRISE_SPACES[%d] is incomplete", i)
		}
		key := spaceKey(e.TenantID, e.SpaceID)
		if _, dup := spaces.byKey[key]; dup || knowledgeBases[e.RawKBID] || knowledgeBases[e.WikiKBID] {
			return Spaces{}, fmt.Errorf("ENTERPRISE_SPACES[%d] repeats a Space or knowledge base role", i)
		}
		knowledgeBases[e.RawKBID], knowledgeBases[e.WikiKBID] = true, true
		spaces.byKey[key] = types.WikiReleaseScope{
			TenantID: e.TenantID, SpaceID: e.SpaceID, RawKBID: e.RawKBID, WikiKBID: e.WikiKBID,
		}
	}
	return spaces, nil
}

// SpaceOf identifies configured enterprise KBs inside their owning tenant only.
func (s Spaces) SpaceOf(tenantID uint64, kbID string) (string, chatsource.Role, bool) {
	if tenantID == 0 || kbID == "" {
		return "", "", false
	}
	for _, scope := range s.byKey {
		if scope.TenantID != tenantID {
			continue
		}
		if scope.RawKBID == kbID {
			return scope.SpaceID, chatsource.RoleRaw, true
		}
		if scope.WikiKBID == kbID {
			return scope.SpaceID, chatsource.RoleWiki, true
		}
	}
	return "", "", false
}

// RawKB reports whether the tenant owns a configured enterprise RAW knowledge base.
func (s Spaces) RawKB(tenantID uint64, knowledgeBaseID string) bool {
	if tenantID == 0 || knowledgeBaseID == "" {
		return false
	}
	for _, scope := range s.byKey {
		if scope.TenantID == tenantID && scope.RawKBID == knowledgeBaseID {
			return true
		}
	}
	return false
}

// Scope resolves the four-part release scope of a configured Space.
func (s Spaces) Scope(tenantID uint64, spaceID string) (types.WikiReleaseScope, error) {
	scope, ok := s.byKey[spaceKey(tenantID, spaceID)]
	if !ok {
		return types.WikiReleaseScope{}, &release.Error{
			Code: release.ErrorReleaseAccessDenied, Detail: "the Space is not an enterprise Space",
		}
	}
	return scope, nil
}

// SpaceIDs lists the configured Spaces of one tenant in stable order.
func (s Spaces) SpaceIDs(tenantID uint64) []string {
	ids := make([]string, 0)
	for _, scope := range s.byKey {
		if scope.TenantID == tenantID {
			ids = append(ids, scope.SpaceID)
		}
	}
	sort.Strings(ids)
	return ids
}

// KnowledgeBases resolves both configured KBs without crossing tenant boundaries.
func (s Spaces) KnowledgeBases(tenantID uint64, spaceID string) (string, string, bool) {
	scope, err := s.Scope(tenantID, spaceID)
	if err != nil {
		return "", "", false
	}
	return scope.RawKBID, scope.WikiKBID, true
}

func spaceKey(tenantID uint64, spaceID string) string {
	return fmt.Sprintf("%d\x00%s", tenantID, spaceID)
}
