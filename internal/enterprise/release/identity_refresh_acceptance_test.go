// PV-4a acceptance: the platform checks an identity_refresh bundle against the full target
// Release (PV-4 Spec §2, appendix A §2). Protected file: written by Claude.
//
// Only version identity may change: on versioned entities the identifiers product_code,
// version_key and filing_no, lifecycle and product_family; on their claims product_version_ref,
// which must equal the subject; supersedes relations may be added or removed. Anything else
// rejects the whole bundle. The base must be the current Head (no lenient rebase), and a bundle
// that changes nothing is refused. Versioned entity types are platform configuration.
package release_test

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const evidenceRef = "source:v1:k-1:1:abc"

func realSchemas(t *testing.T) map[string][]byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "contracts", "candidate_bundle.schema.json"))
	require.NoError(t, err)
	return map[string][]byte{"candidate_bundle": raw}
}

func refreshService(t *testing.T, p *platform, versioned ...string) *release.Service {
	t.Helper()
	options := []release.Option{release.WithPublisher(p)}
	if len(versioned) > 0 {
		options = append(options, release.WithVersionedEntityTypes(versioned...))
	}
	return release.NewService(p, fakeEvidence{allowed: map[string]bool{evidenceRef: true}}, realSchemas(t), options...)
}

func vm(t *testing.T, kind, slug string, payload map[string]any, refs ...string) map[string]any {
	t.Helper()
	entry := map[string]any{
		"kind": kind, "logical_slug": slug, "payload": payload,
		"member_digest": digest(t, payload), "access_scope": "space",
	}
	if len(refs) > 0 {
		entry["evidence_refs"] = refs
	}
	return entry
}

func vbundle(t *testing.T, origin string, base *release.Release, removals []string, members ...map[string]any) []byte {
	t.Helper()
	if members == nil {
		members = []map[string]any{}
	}
	doc := map[string]any{
		"contract_version": "1", "origin": origin, "compiler_identity": "harness/test", "members": members,
	}
	if base != nil {
		doc["base_release_id"], doc["base_epoch"] = base.ID, base.Epoch
	}
	if len(removals) > 0 {
		doc["removals"] = removals
	}
	raw, err := json.Marshal(doc)
	require.NoError(t, err)
	return raw
}

func entityPayload(id, entityType string, extra map[string]any) map[string]any {
	payload := map[string]any{
		"entity_id": id, "entity_type": entityType, "names": []any{"name " + id}, "aliases": []any{},
		"identifiers": map[string]any{"product_code": id}, "classification_labels": []any{"demo"},
		"owner_module": "harness",
	}
	for k, v := range extra {
		payload[k] = v
	}
	return payload
}

func claimPayload(subject, field string, ref any, extra map[string]any) map[string]any {
	key := subject + "/" + field
	payload := map[string]any{
		"claim_id": key, "logical_key": key, "subject_ref": subject, "product_version_ref": ref,
		"predicate": field, "state": "unknown", "value": nil, "origin": "SOURCE_SUPPORTED",
		"evidence": []any{}, "unknown_reason": "NOT_IN_MATERIAL",
	}
	for k, v := range extra {
		payload[k] = v
	}
	return payload
}

func supersedes(newer, older string) (string, map[string]any) {
	id := "supersedes/" + newer + "/" + older
	return "relation/" + id, map[string]any{
		"relation_id": id, "predicate": "supersedes", "from": newer, "to": older,
		"applicability": map[string]any{}, "evidence": []any{}, "provenance": map[string]any{},
	}
}

var (
	lifecycle = map[string]any{
		"sale_start": "2024-04-23", "sale_end": "2024-09-01", "source_status": "discontinued",
		"basis_commit": strings.Repeat("a", 40), "basis_date": "2026-11-01",
	}
	family   = map[string]any{"key": "fam", "display_name": "family"}
	filedIDs = map[string]any{"product_code": "2635", "version_key": "2635-1", "filing_no": "F-1"}
)

// activeBase publishes the base release A through an ordinary compile bundle.
func activeBase(t *testing.T, s *release.Service) release.Release {
	t.Helper()
	return publish(t, s, vbundle(t, "compile", nil, nil,
		vm(t, "entity", "entity/P1", entityPayload("P1", "product", nil)),
		vm(t, "entity", "entity/P2", entityPayload("P2", "product", nil)),
		vm(t, "entity", "entity/M1", entityPayload("M1", "method", nil)),
		vm(t, "claim", "P1/f1", claimPayload("P1", "f1", nil, nil)),
		vm(t, "claim", "P2/f1", claimPayload("P2", "f1", nil, nil)),
		vm(t, "claim", "M1/s1", claimPayload("M1", "s1", nil, nil)),
		vm(t, "claim", "X/f1", claimPayload("X", "f1", nil, nil)),
		vm(t, "presentation_profile", "presentation/p", map[string]any{"profile_id": "p"}),
	))
}

func setup(t *testing.T) (*platform, *release.Service, release.Release) {
	t.Helper()
	p := newPlatform()
	s := refreshService(t, p, "product")
	return p, s, activeBase(t, s)
}

// attempt receives, approves and activates, returning the first error.
func attempt(s *release.Service, raw []byte) (release.Release, error) {
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, raw)
	if err != nil {
		return release.Release{}, err
	}
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	if err != nil {
		return release.Release{}, err
	}
	return s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
}

func TestAnIdentityRefreshPublishesOnlyVersionIdentity(t *testing.T) {
	_, s, a := setup(t)
	p1 := entityPayload("P1", "product", map[string]any{
		"identifiers": filedIDs, "lifecycle": lifecycle, "product_family": family,
	})
	relSlug, rel := supersedes("P2", "P1")
	r := publish(t, s, vbundle(t, "identity_refresh", &a, nil,
		vm(t, "entity", "entity/P1", p1),
		vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil)),
		vm(t, "claim", "P2/f1", claimPayload("P2", "f1", "P2", nil)),
		vm(t, "relation", relSlug, rel),
	))
	require.Equal(t, a.Epoch+1, r.Epoch)
	require.Equal(t, digest(t, p1), memberBySlug(r, "entity/P1").MemberDigest)
	require.Equal(t, digest(t, rel), memberBySlug(r, relSlug).MemberDigest)
	require.Equal(t, memberBySlug(a, "M1/s1").MemberDigest, memberBySlug(r, "M1/s1").MemberDigest)

	// Removing a stale supersedes relation alone is a change, not a no-op.
	gone := publish(t, s, vbundle(t, "identity_refresh", &r, []string{relSlug}))
	require.NotContains(t, slugs(gone), relSlug)
}

func TestAnIdentityRefreshRejectsEveryOtherChange(t *testing.T) {
	relSlug, rel := supersedes("P2", "P1")
	bad := func(mutate func(map[string]any)) map[string]any {
		payload := map[string]any{}
		for k, v := range rel {
			payload[k] = v
		}
		mutate(payload)
		return payload
	}
	cases := map[string]func(t *testing.T, a *release.Release) []byte{
		"added claim": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "claim", "P1/f9", claimPayload("P1", "f9", "P1", nil)))
		},
		"removed claim": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, []string{"P1/f1"})
		},
		"removed other member": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, []string{"presentation/p"})
		},
		"claim field outside the allowed set": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil,
				vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", map[string]any{"unit": "day"})))
		},
		"evidence refs": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil,
				vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil), evidenceRef))
		},
		"access scope": func(t *testing.T, a *release.Release) []byte {
			m := vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil))
			m["access_scope"] = "other"
			return vbundle(t, "identity_refresh", a, nil, m)
		},
		"kind": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "claim", "entity/P1",
				entityPayload("P1", "product", map[string]any{"lifecycle": lifecycle})))
		},
		"ref is not the subject": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P2", nil)))
		},
		"ref to an unversioned entity": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "claim", "M1/s1", claimPayload("M1", "s1", "M1", nil)))
		},
		"ref to no entity": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "claim", "X/f1", claimPayload("X", "f1", "X", nil)))
		},
		"unversioned entity gets a lifecycle": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "entity", "entity/M1",
				entityPayload("M1", "method", map[string]any{"lifecycle": lifecycle})))
		},
		"other identifier": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "entity", "entity/P1", entityPayload("P1", "product",
				map[string]any{"identifiers": map[string]any{"product_code": "P1", "extra": "1"}})))
		},
		"entity name": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "entity", "entity/P1",
				entityPayload("P1", "product", map[string]any{"names": []any{"renamed"}})))
		},
		"sale period reversed": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "entity", "entity/P1", entityPayload("P1", "product",
				map[string]any{"lifecycle": map[string]any{"sale_start": "2024-09-01", "sale_end": "2024-04-23"}})))
		},
		"impossible date": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "entity", "entity/P1", entityPayload("P1", "product",
				map[string]any{"lifecycle": map[string]any{"sale_start": "2024-02-30"}})))
		},
		"unknown status": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "entity", "entity/P1", entityPayload("P1", "product",
				map[string]any{"lifecycle": map[string]any{"source_status": "paused"}})))
		},
		"lifecycle extra field": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "entity", "entity/P1", entityPayload("P1", "product",
				map[string]any{"lifecycle": map[string]any{"sale_state": "on_sale"}})))
		},
		"empty family": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil, vm(t, "entity", "entity/P1", entityPayload("P1", "product",
				map[string]any{"product_family": map[string]any{"key": "", "display_name": "x"}})))
		},
		"other relation": func(t *testing.T, a *release.Release) []byte {
			payload := bad(func(p map[string]any) { p["predicate"] = "relates_to"; p["relation_id"] = "relates_to/P1" })
			return vbundle(t, "identity_refresh", a, nil, vm(t, "relation", "relation/relates_to/P1", payload))
		},
		"relation id not derived": func(t *testing.T, a *release.Release) []byte {
			payload := bad(func(p map[string]any) { p["relation_id"] = "supersedes/P2/P9" })
			return vbundle(t, "identity_refresh", a, nil, vm(t, "relation", relSlug, payload))
		},
		"relation end unversioned": func(t *testing.T, a *release.Release) []byte {
			slug, payload := supersedes("M1", "P1")
			return vbundle(t, "identity_refresh", a, nil, vm(t, "relation", slug, payload))
		},
		"relation to itself": func(t *testing.T, a *release.Release) []byte {
			slug, payload := supersedes("P1", "P1")
			return vbundle(t, "identity_refresh", a, nil, vm(t, "relation", slug, payload))
		},
		"no change": func(t *testing.T, a *release.Release) []byte {
			return vbundle(t, "identity_refresh", a, nil,
				vm(t, "entity", "entity/P1", entityPayload("P1", "product", nil)))
		},
		"no base": func(t *testing.T, _ *release.Release) []byte {
			return vbundle(t, "identity_refresh", nil, nil,
				vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil)))
		},
		"review plan": func(t *testing.T, a *release.Release) []byte {
			raw := vbundle(t, "identity_refresh", a, nil, vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil)))
			var doc map[string]any
			require.NoError(t, json.Unmarshal(raw, &doc))
			doc["review_plan"] = []any{map[string]any{"mode": "human"}}
			out, err := json.Marshal(doc)
			require.NoError(t, err)
			return out
		},
	}
	for name, build := range cases {
		t.Run(name, func(t *testing.T) {
			p, s, a := setup(t)
			_, err := attempt(s, build(t, &a))
			require.Error(t, err)
			require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
			require.Equal(t, a.ID, p.head.ReleaseID, "nothing activated")
		})
	}
}

func TestAnIdentityRefreshCannotChangeAPublishedRelation(t *testing.T) {
	_, s, a := setup(t)
	relSlug, rel := supersedes("P2", "P1")
	r := publish(t, s, vbundle(t, "identity_refresh", &a, nil, vm(t, "relation", relSlug, rel)))
	changed := map[string]any{}
	for k, v := range rel {
		changed[k] = v
	}
	changed["applicability"] = map[string]any{"channel": "x"}
	_, err := attempt(s, vbundle(t, "identity_refresh", &r, nil, vm(t, "relation", relSlug, changed)))
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

func TestAnIdentityRefreshNeedsTheCurrentHead(t *testing.T) {
	_, s, a := setup(t)
	raw := vbundle(t, "identity_refresh", &a, nil, vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil)))
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, raw)
	require.NoError(t, err)
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	// An unrelated compile moves the Head; a compile delta would rebase leniently, this may not.
	moved := publish(t, s, vbundle(t, "compile", &a, nil, vm(t, "claim", "Q1/f1", claimPayload("Q1", "f1", nil, nil))))
	require.NotEqual(t, a.ID, moved.ID)
	_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
	require.Equal(t, release.ErrorNeedsRebase, codeOf(t, err))
}

func TestAnIdentityRefreshNeedsConfiguredVersionedTypes(t *testing.T) {
	p := newPlatform()
	s := refreshService(t, p)
	a := activeBase(t, s)
	_, err := attempt(s, vbundle(t, "identity_refresh", &a, nil,
		vm(t, "claim", "P1/f1", claimPayload("P1", "f1", "P1", nil))))
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
	require.Equal(t, a.ID, p.head.ReleaseID)
}

func TestCompileBundlesAreUnaffectedByTheRefreshRules(t *testing.T) {
	_, s, a := setup(t)
	r := publish(t, s, vbundle(t, "compile", &a, []string{"presentation/p"},
		vm(t, "claim", "P1/f1", claimPayload("P1", "f1", nil, map[string]any{"unit": "day"})),
		vm(t, "claim", "P1/f9", claimPayload("P1", "f9", nil, nil))))
	require.Contains(t, slugs(r), "P1/f9")
	require.NotContains(t, slugs(r), "presentation/p")
}
