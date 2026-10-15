// Package releasestore persists generic candidates and decisions and publishes
// releases through the existing wiki_release_* Head authority (S4c-2a Spec §3.2).
package releasestore

import (
	"encoding/json"
	"fmt"
	"strings"

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

// ParseSpaces decodes the ENTERPRISE_SPACES JSON list. Every Space must be
// complete and unique, and must not reuse the Space or wiki KB of any scope in
// reserved (the G3 path keeps its own Head; S4c-2a user decision 2026-10-15).
func ParseSpaces(raw string, reserved ...types.WikiReleaseScope) (Spaces, error) {
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
	wikiKBs := map[string]bool{}
	for i, e := range entries {
		if e.TenantID == 0 || strings.TrimSpace(e.SpaceID) == "" || strings.TrimSpace(e.RawKBID) == "" ||
			strings.TrimSpace(e.WikiKBID) == "" || e.RawKBID == e.WikiKBID {
			return Spaces{}, fmt.Errorf("ENTERPRISE_SPACES[%d] is incomplete", i)
		}
		key := spaceKey(e.TenantID, e.SpaceID)
		if _, dup := spaces.byKey[key]; dup || wikiKBs[e.WikiKBID] {
			return Spaces{}, fmt.Errorf("ENTERPRISE_SPACES[%d] repeats a Space or wiki KB", i)
		}
		for _, r := range reserved {
			if r.TenantID == e.TenantID && (r.SpaceID == e.SpaceID || r.WikiKBID == e.WikiKBID) {
				return Spaces{}, fmt.Errorf("ENTERPRISE_SPACES[%d] reuses a reserved Space or wiki KB", i)
			}
		}
		wikiKBs[e.WikiKBID] = true
		spaces.byKey[key] = types.WikiReleaseScope{
			TenantID: e.TenantID, SpaceID: e.SpaceID, RawKBID: e.RawKBID, WikiKBID: e.WikiKBID,
		}
	}
	return spaces, nil
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

func spaceKey(tenantID uint64, spaceID string) string {
	return fmt.Sprintf("%d\x00%s", tenantID, spaceID)
}
