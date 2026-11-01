package release

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"time"
)

// OriginIdentityRefresh marks a bundle that only refreshes product version identity
// (PV-4 Spec §2, PV-0 appendix A §2). The platform does not trust the marker: it checks
// the whole target Release against the active one before activation.
const OriginIdentityRefresh = "identity_refresh"

const (
	kindEntity          = "entity"
	kindClaim           = "claim"
	kindRelation        = "relation"
	predicateSupersedes = "supersedes"
	dateLayout          = "2006-01-02"
)

var (
	refreshKinds     = map[string]bool{kindEntity: true, kindClaim: true, kindRelation: true}
	entityRefreshed  = map[string]bool{"lifecycle": true, "product_family": true}
	identifierFields = map[string]bool{"product_code": true, "version_key": true, "filing_no": true}
	lifecycleFields  = map[string]bool{
		"sale_start": true, "sale_end": true, "source_status": true, "basis_commit": true, "basis_date": true,
	}
	sourceStatuses = map[string]bool{"on_sale": true, "discontinued": true}
	commitPattern  = regexp.MustCompile(`^[0-9a-f]{40}$`)
)

// WithVersionedEntityTypes names the entity types whose members are filed product versions.
// Only their identity may change in an identity refresh; without any, such bundles are refused.
// Configuration, not code: the platform never names a domain type itself (PV-4 Spec §2.1).
func WithVersionedEntityTypes(types ...string) Option {
	return func(s *Service) {
		s.versioned = map[string]bool{}
		for _, t := range types {
			if t = strings.TrimSpace(t); t != "" {
				s.versioned[t] = true
			}
		}
	}
}

// checkRefreshShape is the receive-time part: a refresh names its exact base, carries no
// review plan and only entity, claim and relation members (PV-4 Spec §2.2).
func (s *Service) checkRefreshShape(b Bundle) error {
	switch {
	case b.Origin != OriginIdentityRefresh:
		return nil
	case len(s.versioned) == 0:
		return invalid("identity refresh: versioned entity types are not configured")
	case strings.TrimSpace(b.BaseReleaseID) == "" || b.BaseEpoch == nil:
		return invalid("identity refresh needs base_release_id and base_epoch")
	case len(b.ReviewPlan) > 0:
		return invalid("identity refresh carries no review plan")
	}
	for i, m := range b.Members {
		if !refreshKinds[m.Kind] {
			return invalid(fmt.Sprintf("identity refresh member kind is not allowed at /members/%d", i))
		}
	}
	return nil
}

// checkIdentityRefresh compares the target Release with the active one (PV-4 Spec §2.3):
// only supersedes relations may appear or disappear, and kept members may change only
// their version identity fields. Every violation rejects the whole bundle.
func (s *Service) checkIdentityRefresh(active, target []Member) error {
	if len(s.versioned) == 0 {
		return invalid("identity refresh: versioned entity types are not configured")
	}
	before, after := bySlug(active), bySlug(target)
	versioned := s.versionedEntities(target)
	changes := 0
	for _, m := range target {
		old, kept := before[m.LogicalSlug]
		if !kept {
			if err := checkAddedRelation(m, versioned); err != nil {
				return err
			}
			changes++
			continue
		}
		if err := checkEnvelope(old, m); err != nil {
			return err
		}
		if old.MemberDigest == m.MemberDigest {
			continue
		}
		if err := s.checkChangedPayload(old, m, versioned); err != nil {
			return err
		}
		changes++
	}
	for _, m := range active {
		if _, kept := after[m.LogicalSlug]; kept {
			continue
		}
		if !isSupersedes(m) {
			return invalid("identity refresh may only remove supersedes relations: " + m.LogicalSlug)
		}
		changes++
	}
	if changes == 0 {
		return invalid("identity refresh changes nothing")
	}
	return nil
}

func bySlug(members []Member) map[string]Member {
	out := make(map[string]Member, len(members))
	for _, m := range members {
		out[m.LogicalSlug] = m
	}
	return out
}

// versionedEntities maps the entity IDs of the target's versioned entities.
func (s *Service) versionedEntities(target []Member) map[string]bool {
	out := map[string]bool{}
	for _, m := range target {
		if m.Kind != kindEntity {
			continue
		}
		payload, ok := decodeObject(m.Payload)
		if !ok {
			continue
		}
		id, _ := payload["entity_id"].(string)
		kind, _ := payload["entity_type"].(string)
		if id != "" && s.versioned[kind] {
			out[id] = true
		}
	}
	return out
}

func checkEnvelope(old, m Member) error {
	if old.Kind != m.Kind || old.AccessScope != m.AccessScope || !sameStrings(old.EvidenceRefs, m.EvidenceRefs) {
		return invalid("identity refresh may not change a member's kind, scope or evidence refs: " + m.LogicalSlug)
	}
	return nil
}

func (s *Service) checkChangedPayload(old, m Member, versioned map[string]bool) error {
	before, okBefore := decodeObject(old.Payload)
	after, okAfter := decodeObject(m.Payload)
	if !okBefore || !okAfter {
		return invalid("identity refresh payload is not an object: " + m.LogicalSlug)
	}
	switch m.Kind {
	case kindEntity:
		return s.checkEntityChange(m.LogicalSlug, before, after)
	case kindClaim:
		return checkClaimChange(m.LogicalSlug, before, after, versioned)
	default:
		return invalid("identity refresh may not change this member: " + m.LogicalSlug)
	}
}

func (s *Service) checkEntityChange(slug string, before, after map[string]any) error {
	if kind, _ := before["entity_type"].(string); !s.versioned[kind] {
		return invalid("identity refresh may not change an unversioned entity: " + slug)
	}
	if !sameJSON(stripEntity(before), stripEntity(after)) {
		return invalid("identity refresh changed an entity field outside version identity: " + slug)
	}
	if value, ok := after["lifecycle"]; ok && !validLifecycle(value) {
		return invalid("identity refresh lifecycle is invalid: " + slug)
	}
	if value, ok := after["product_family"]; ok && !validFamily(value) {
		return invalid("identity refresh product_family is invalid: " + slug)
	}
	identifiers, _ := after["identifiers"].(map[string]any)
	for _, value := range identifiers {
		if _, ok := value.(string); !ok {
			return invalid("identity refresh identifiers must be strings: " + slug)
		}
	}
	return nil
}

func checkClaimChange(slug string, before, after map[string]any, versioned map[string]bool) error {
	subject, _ := before["subject_ref"].(string)
	if !versioned[subject] {
		return invalid("identity refresh may not change a claim of an unversioned subject: " + slug)
	}
	stripped := func(payload map[string]any) map[string]any {
		out := copyObject(payload)
		delete(out, "product_version_ref")
		return out
	}
	if !sameJSON(stripped(before), stripped(after)) {
		return invalid("identity refresh changed a claim field outside product_version_ref: " + slug)
	}
	if ref, ok := after["product_version_ref"]; ok && ref != nil && ref != subject {
		return invalid("product_version_ref must equal the claim's subject: " + slug)
	}
	return nil
}

func checkAddedRelation(m Member, versioned map[string]bool) error {
	payload, ok := decodeObject(m.Payload)
	if m.Kind != kindRelation || !ok || payload["predicate"] != predicateSupersedes {
		return invalid("identity refresh may only add supersedes relations: " + m.LogicalSlug)
	}
	from, _ := payload["from"].(string)
	to, _ := payload["to"].(string)
	id := predicateSupersedes + "/" + from + "/" + to
	switch {
	case from == "" || to == "" || from == to || strings.Contains(from+to, "/"):
		return invalid("supersedes needs two different entity ids: " + m.LogicalSlug)
	case payload["relation_id"] != id || m.LogicalSlug != "relation/"+id:
		return invalid("supersedes relation id is not derived from its ends: " + m.LogicalSlug)
	case !versioned[from] || !versioned[to]:
		return invalid("supersedes ends must be versioned entities of the release: " + m.LogicalSlug)
	}
	return nil
}

func isSupersedes(m Member) bool {
	payload, ok := decodeObject(m.Payload)
	return m.Kind == kindRelation && ok && payload["predicate"] == predicateSupersedes
}

func stripEntity(payload map[string]any) map[string]any {
	out := copyObject(payload)
	for key := range entityRefreshed {
		delete(out, key)
	}
	if identifiers, ok := out["identifiers"].(map[string]any); ok {
		kept := copyObject(identifiers)
		for key := range identifierFields {
			delete(kept, key)
		}
		out["identifiers"] = kept
	}
	return out
}

func validLifecycle(value any) bool {
	lifecycle, ok := value.(map[string]any)
	if !ok {
		return false
	}
	text := map[string]string{}
	for key, field := range lifecycle {
		if !lifecycleFields[key] {
			return false
		}
		if field == nil {
			continue
		}
		s, ok := field.(string)
		if !ok {
			return false
		}
		text[key] = s
	}
	for _, key := range []string{"sale_start", "sale_end", "basis_date"} {
		if s, ok := text[key]; ok && !validDate(s) {
			return false
		}
	}
	if status, ok := text["source_status"]; ok && !sourceStatuses[status] {
		return false
	}
	if commit, ok := text["basis_commit"]; ok && !commitPattern.MatchString(commit) {
		return false
	}
	start, hasStart := text["sale_start"]
	end, hasEnd := text["sale_end"]
	return !hasStart || !hasEnd || start < end
}

func validDate(text string) bool {
	parsed, err := time.Parse(dateLayout, text)
	return err == nil && parsed.Format(dateLayout) == text
}

func validFamily(value any) bool {
	family, ok := value.(map[string]any)
	if !ok || len(family) != 2 {
		return false
	}
	for _, key := range []string{"key", "display_name"} {
		s, ok := family[key].(string)
		if !ok || strings.TrimSpace(s) == "" {
			return false
		}
	}
	return true
}

func decodeObject(raw json.RawMessage) (map[string]any, bool) {
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil || out == nil {
		return nil, false
	}
	return out, true
}

func copyObject(in map[string]any) map[string]any {
	out := make(map[string]any, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}

// sameJSON compares two decoded payloads by their canonical JSON (sorted keys).
func sameJSON(a, b map[string]any) bool {
	left, errA := json.Marshal(a)
	right, errB := json.Marshal(b)
	return errA == nil && errB == nil && bytes.Equal(left, right)
}

func sameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
