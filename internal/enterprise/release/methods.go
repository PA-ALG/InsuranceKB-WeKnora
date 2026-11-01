package release

import (
	"encoding/json"
	"strings"
)

// ClassMethod is the presentation profile knowledge class of method knowledge (SK-3 Spec §1): its
// entity types are published data; the platform dispatches on this contract value only.
const ClassMethod = "method"

type profileTypes struct {
	Types []string `json:"entity_types"`
	Class string   `json:"knowledge_class"`
}

// MethodEntityTypes are the entity types a presentation profile with knowledge class "method"
// serves among the given members.
func MethodEntityTypes(members ...[]Member) map[string]bool {
	out := map[string]bool{}
	for _, set := range members {
		for _, m := range set {
			var profile profileTypes
			if m.Kind != "presentation_profile" || json.Unmarshal(m.Payload, &profile) != nil {
				continue
			}
			if profile.Class == ClassMethod {
				for _, kind := range profile.Types {
					out[kind] = true
				}
			}
		}
	}
	return out
}

// EntityTypes maps each entity member's ID to its entity type.
func EntityTypes(members []Member) map[string]string {
	out := map[string]string{}
	for _, m := range members {
		var entity struct {
			ID   string `json:"entity_id"`
			Type string `json:"entity_type"`
		}
		if m.Kind == kindEntity && json.Unmarshal(m.Payload, &entity) == nil && entity.ID != "" {
			out[entity.ID] = entity.Type
		}
	}
	return out
}

type methodClaim struct {
	Subject    string `json:"subject_ref"`
	State      string `json:"state"`
	Origin     string `json:"origin"`
	Value      any    `json:"value"`
	ExpertLock bool   `json:"expert_lock"`
	Evidence   []struct {
		Locator struct {
			Kind string `json:"kind"`
		} `json:"locator"`
	} `json:"evidence"`
}

// checkMethodClaims holds the candidate's method claims to their rule (SK-3 Spec §4.1): method
// knowledge rests on source passages only (no expert evidence or lock), and a present claim is
// SOURCE_SUPPORTED with a non-blank text and at least one evidence object, or a non-empty list of
// non-blank texts with one evidence object at each item's position. Without a source a method
// claim can only be unknown (SK-0 §2.1). Method types come from the Active and the target release,
// so dropping the profile in the same candidate does not lift the rule.
func checkMethodClaims(active, target []Member, b Bundle) error {
	methods := MethodEntityTypes(active, target)
	if len(methods) == 0 {
		return nil
	}
	types := EntityTypes(target)
	for _, m := range b.Members {
		if m.Kind != kindClaim {
			continue
		}
		var claim methodClaim
		if err := json.Unmarshal(m.Payload, &claim); err != nil {
			return invalid("method claim is not an object: " + m.LogicalSlug)
		}
		if !methods[types[claim.Subject]] {
			continue
		}
		if claim.ExpertLock {
			return invalid("method knowledge carries no expert lock: " + m.LogicalSlug)
		}
		for _, evidence := range claim.Evidence {
			if evidence.Locator.Kind == "EXPERT_REVISION" {
				return invalid("method knowledge rests on source passages only: " + m.LogicalSlug)
			}
		}
		if claim.State == "unknown" {
			continue
		}
		if err := sourcedValue(claim); err != "" {
			return invalid(err + ": " + m.LogicalSlug)
		}
	}
	return nil
}

// sourcedValue is why a stated method claim is not sourced item by item, or "".
func sourcedValue(claim methodClaim) string {
	if claim.Origin != "SOURCE_SUPPORTED" {
		return "method knowledge is SOURCE_SUPPORTED or unknown"
	}
	if text, ok := claim.Value.(string); ok {
		if strings.TrimSpace(text) == "" || len(claim.Evidence) == 0 {
			return "a method text needs its source passages"
		}
		return ""
	}
	items, ok := claim.Value.([]any)
	if !ok || len(items) == 0 {
		return "a method value is a text or a non-empty list"
	}
	if len(items) != len(claim.Evidence) {
		return "method list items and evidence differ"
	}
	for _, item := range items {
		if text, ok := item.(string); !ok || strings.TrimSpace(text) == "" {
			return "method list items must be non-blank text"
		}
	}
	return ""
}
