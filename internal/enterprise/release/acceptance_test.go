// S3b acceptance: the platform receives bundles through the shared contract
// (blueprint 1001 §6.2, §5.3). Protected file: written by Claude.
//
// Everything here uses the package's exported surface only, with in-memory
// fakes and an inline schema: no database, no network, no file system. The
// package does not exist yet, so this file is RED until S3b implements it.
package release_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const spaceID = "space-1"

// schema is deliberately minimal: it pins the shape the service must accept,
// not the full §5 contract (S3a owns that).
const schema = `{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["contract_version", "origin", "members", "compiler_identity"],
  "properties": {
    "contract_version": {"const": "1"},
    "base_release_id": {"type": "string"},
    "origin": {"type": "string"},
    "compiler_identity": {"type": "string"},
    "removals": {"type": "array", "items": {"type": "string"}},
    "members": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["kind", "logical_slug", "payload", "member_digest"],
        "properties": {
          "kind": {"type": "string"},
          "logical_slug": {"type": "string"},
          "payload": {"type": "object"},
          "member_digest": {"type": "string"},
          "evidence_refs": {"type": "array", "items": {"type": "string"}}
        }
      }
    }
  }
}`

func canonical(t *testing.T, value any) []byte {
	t.Helper()
	raw, err := json.Marshal(value)
	require.NoError(t, err)
	return raw
}

func digest(t *testing.T, value any) string {
	t.Helper()
	sum := sha256.Sum256(canonical(t, value))
	return hex.EncodeToString(sum[:])
}

// member builds a contract-shaped member whose digest matches its payload.
func member(t *testing.T, slug string, payload map[string]any, refs ...string) map[string]any {
	t.Helper()
	entry := map[string]any{
		"kind":          "claim",
		"logical_slug":  slug,
		"payload":       payload,
		"member_digest": digest(t, payload),
	}
	if len(refs) > 0 {
		entry["evidence_refs"] = refs
	}
	return entry
}

func bundle(t *testing.T, members ...map[string]any) []byte {
	t.Helper()
	raw, err := json.Marshal(map[string]any{
		"contract_version":  "1",
		"base_release_id":   "release-base",
		"origin":            "compile",
		"compiler_identity": "harness/test",
		"members":           members,
	})
	require.NoError(t, err)
	return raw
}

func schemas() map[string][]byte {
	return map[string][]byte{"candidate_bundle": []byte(schema)}
}

// ---- fakes --------------------------------------------------------------------------------

type fakeStore struct {
	candidates map[string]release.Candidate
	bundles    map[string]release.Bundle
	byDigest   map[string]string
	// members is the active Head's logical_slug -> member_digest map, which
	// Preview compares the candidate against.
	members map[string]string
	head    release.Head
	created int
}

func newStore() *fakeStore {
	return &fakeStore{
		candidates: map[string]release.Candidate{},
		bundles:    map[string]release.Bundle{},
		byDigest:   map[string]string{},
	}
}

func (s *fakeStore) CreateCandidate(_ context.Context, c release.Candidate, b release.Bundle) (release.Candidate, error) {
	if id, ok := s.byDigest[c.BundleDigest]; ok {
		existing := s.candidates[id]
		existing.Status = "existing"
		return existing, nil
	}
	s.created++
	c.ID = fmt.Sprintf("candidate-%d", s.created)
	c.Status = "created"
	s.candidates[c.ID] = c
	s.bundles[c.ID] = b
	s.byDigest[c.BundleDigest] = c.ID
	return c, nil
}

// CandidateByID deliberately ignores the tenant: the service, not the store,
// must refuse a candidate that belongs to somebody else.
func (s *fakeStore) CandidateByID(_ context.Context, _ uint64, _, id string) (release.Candidate, error) {
	c, ok := s.candidates[id]
	if !ok {
		return release.Candidate{}, &release.Error{Code: release.ErrorCandidateNotFound, Detail: id}
	}
	return c, nil
}

func (s *fakeStore) BundleOf(_ context.Context, _ uint64, _, id string) (release.Bundle, error) {
	b, ok := s.bundles[id]
	if !ok {
		return release.Bundle{}, &release.Error{Code: release.ErrorCandidateNotFound, Detail: id}
	}
	return b, nil
}

func (s *fakeStore) Head(_ context.Context, tenantID uint64, _ string) (release.Head, error) {
	if s.head.ReleaseID == "" || tenantID == 0 {
		return release.Head{}, nil
	}
	return s.head, nil
}

func (s *fakeStore) MembersOf(_ context.Context, _ uint64, _, releaseID string) (map[string]string, error) {
	if releaseID == s.head.ReleaseID {
		return s.members, nil
	}
	return map[string]string{}, nil
}

func newService(store *fakeStore, valid ...string) *release.Service {
	allowed := map[string]bool{}
	for _, ref := range valid {
		allowed[ref] = true
	}
	return release.NewService(store, fakeEvidence{allowed: allowed}, schemas())
}

type fakeEvidence struct{ allowed map[string]bool }

func (f fakeEvidence) Resolve(_ context.Context, ref string) (bool, error) {
	if strings.HasPrefix(ref, "boom:") {
		return false, errors.New("resolver unavailable")
	}
	return f.allowed[ref], nil
}

func principal() release.Principal { return release.Principal{TenantID: 7, Subject: "svc-harness"} }

func codeOf(t *testing.T, err error) string {
	t.Helper()
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	return failure.Code
}

// ---- receive ------------------------------------------------------------------------------

func TestReceiveAcceptsAValidBundleWithAStableDigest(t *testing.T) {
	store := newStore()
	service := newService(store, "ev-1")
	raw := bundle(t, member(t, "596-1:waiting_period", map[string]any{"value": "90日"}, "ev-1"))

	first, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.NoError(t, err)
	require.Equal(t, "1", first.ContractVersion)
	require.Equal(t, "release-base", first.BaseReleaseID)
	require.Equal(t, uint64(7), first.TenantID)

	second, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.NoError(t, err)
	require.Equal(t, first.BundleDigest, second.BundleDigest, "the same bytes must produce the same digest")
	require.Equal(t, 1, store.created, "a repeated digest must not create a second candidate")
	require.Equal(t, first.ID, second.ID)
}

func TestReceiveRejectsASchemaViolation(t *testing.T) {
	service := newService(newStore())
	raw := bundle(t, map[string]any{"kind": "claim", "logical_slug": "x", "member_digest": "d"}) // no payload

	_, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.Error(t, err)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

func TestReceiveRejectsAMemberDigestThatDoesNotMatchItsPayload(t *testing.T) {
	service := newService(newStore())
	entry := member(t, "596-1:waiting_period", map[string]any{"value": "90日"})
	entry["member_digest"] = digest(t, map[string]any{"value": "30日"})

	_, err := service.Receive(context.Background(), principal(), spaceID, bundle(t, entry))
	require.Error(t, err)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

func TestReceiveRejectsDuplicateLogicalSlugs(t *testing.T) {
	service := newService(newStore())
	payload := map[string]any{"value": "90日"}
	raw := bundle(t, member(t, "596-1:waiting_period", payload), member(t, "596-1:waiting_period", payload))

	_, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.Error(t, err)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

func TestReceiveRejectsAnUnresolvableEvidenceRef(t *testing.T) {
	service := newService(newStore(), "ev-1")
	missing := bundle(t, member(t, "596-1:waiting_period", map[string]any{"value": "90日"}, "ev-missing"))
	_, err := service.Receive(context.Background(), principal(), spaceID, missing)
	require.Error(t, err)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))

	failing := bundle(t, member(t, "596-1:waiting_period", map[string]any{"value": "90日"}, "boom:resolver"))
	_, err = service.Receive(context.Background(), principal(), spaceID, failing)
	require.Error(t, err, "a resolver failure must fail closed, not drop the member")
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

func TestReceiveRejectsAnUnsupportedContractVersion(t *testing.T) {
	service := newService(newStore())
	var doc map[string]any
	require.NoError(t, json.Unmarshal(bundle(t, member(t, "s", map[string]any{"value": "v"})), &doc))
	doc["contract_version"] = "2"
	raw, err := json.Marshal(doc)
	require.NoError(t, err)

	_, err = service.Receive(context.Background(), principal(), spaceID, raw)
	require.Error(t, err)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

func TestReceiveRejectsAnUnknownTopLevelField(t *testing.T) {
	service := newService(newStore())
	var doc map[string]any
	require.NoError(t, json.Unmarshal(bundle(t, member(t, "s", map[string]any{"value": "v"})), &doc))
	doc["surprise"] = true
	raw, err := json.Marshal(doc)
	require.NoError(t, err)

	_, err = service.Receive(context.Background(), principal(), spaceID, raw)
	require.Error(t, err)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

// ---- preview ------------------------------------------------------------------------------

func TestPreviewAgainstAnEmptyHeadReportsEveryMemberAsAdded(t *testing.T) {
	store := newStore()
	service := newService(store)
	raw := bundle(t,
		member(t, "596-1:waiting_period", map[string]any{"value": "90日"}),
		member(t, "596-1:coverage_period", map[string]any{"value": "一年"}),
	)
	candidate, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.NoError(t, err)

	preview, err := service.Preview(context.Background(), principal(), spaceID, candidate.ID)
	require.NoError(t, err)
	require.False(t, preview.NeedsRebase, "nothing has been activated yet")
	require.Equal(t, []string{"596-1:coverage_period", "596-1:waiting_period"}, preview.Delta.Added)
	require.Empty(t, preview.Delta.Changed)
	require.Empty(t, preview.Delta.Removed)
	require.Empty(t, preview.Delta.Unchanged)
}

func TestPreviewReportsChangedRemovedAndUnchangedAgainstHead(t *testing.T) {
	store := newStore()
	store.head = release.Head{ReleaseID: "release-live", Epoch: 3}
	store.members = map[string]string{
		"596-1:waiting_period": digest(t, map[string]any{"value": "90日"}),
	}
	service := newService(store)
	raw := bundle(t,
		member(t, "596-1:waiting_period", map[string]any{"value": "90日"}), // unchanged
		member(t, "596-1:coverage_period", map[string]any{"value": "一年"}), // added
	)

	candidate, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.NoError(t, err)
	preview, err := service.Preview(context.Background(), principal(), spaceID, candidate.ID)
	require.NoError(t, err)
	require.True(t, preview.NeedsRebase, "Head moved past the candidate's base")
	require.Equal(t, "release-live", preview.HeadReleaseID)
	require.Equal(t, []string{"596-1:coverage_period"}, preview.Delta.Added)
	require.Equal(t, []string{"596-1:waiting_period"}, preview.Delta.Unchanged)
}

func TestPreviewReportsAnUnknownCandidate(t *testing.T) {
	service := newService(newStore())
	_, err := service.Preview(context.Background(), principal(), spaceID, "candidate-does-not-exist")
	require.Error(t, err)
	require.Equal(t, release.ErrorCandidateNotFound, codeOf(t, err))
}

func TestPreviewDeniesAnotherTenant(t *testing.T) {
	store := newStore()
	service := newService(store)
	candidate, err := service.Receive(context.Background(), principal(), spaceID,
		bundle(t, member(t, "596-1:waiting_period", map[string]any{"value": "90日"})))
	require.NoError(t, err)

	other := release.Principal{TenantID: 8, Subject: "svc-other"}
	_, err = service.Preview(context.Background(), other, spaceID, candidate.ID)
	require.Error(t, err)
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
}
