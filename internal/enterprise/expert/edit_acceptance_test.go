// S9a acceptance: an expert edit stores an immutable revision record and publishes a new release
// in which the claim carries the expert value, an EXPERT_REVISION citation and expert_lock; stale
// or invalid edits write nothing; forged expert references are refused
// (Spec docs/design/slices/S9a-专家编辑平台.md §4). Protected file: written by Claude.
// RED until S9a: package expert does not exist.
package expert_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const spaceID = "space-1"

var (
	admin   = release.Principal{TenantID: 7, Subject: "admin-1"}
	harness = release.Principal{TenantID: 7, Subject: "svc-harness"}
	approve = release.DecisionInput{Outcome: "approve", Mode: "human", Reason: "seed"}
	fixedAt = time.Date(2026, 10, 22, 9, 0, 0, 0, time.UTC)
	fileSHA = strings.Repeat("ab", 32)
)

// ---- in-memory platform: one Head, CAS on activation -------------------------------------

type platform struct {
	candidates  map[string]release.Candidate
	bundles     map[string]release.Bundle
	byDigest    map[string]string
	decisions   map[string]release.Decision
	releases    map[string]release.Release
	nonces      map[string]string
	head        release.Head
	activations int
}

func newPlatform() *platform {
	return &platform{
		candidates: map[string]release.Candidate{}, bundles: map[string]release.Bundle{},
		byDigest: map[string]string{}, decisions: map[string]release.Decision{},
		releases: map[string]release.Release{}, nonces: map[string]string{},
	}
}

func (p *platform) CreateCandidate(_ context.Context, c release.Candidate, b release.Bundle) (release.Candidate, error) {
	if id, ok := p.byDigest[c.BundleDigest]; ok {
		return p.candidates[id], nil
	}
	c.ID, c.Status = fmt.Sprintf("candidate-%d", len(p.candidates)+1), "created"
	p.candidates[c.ID], p.bundles[c.ID], p.byDigest[c.BundleDigest] = c, b, c.ID
	return c, nil
}

func (p *platform) CandidateByID(_ context.Context, _ uint64, _, id string) (release.Candidate, error) {
	c, ok := p.candidates[id]
	if !ok {
		return release.Candidate{}, &release.Error{Code: release.ErrorCandidateNotFound}
	}
	return c, nil
}

func (p *platform) BundleOf(_ context.Context, _ uint64, _, id string) (release.Bundle, error) {
	return p.bundles[id], nil
}

func (p *platform) Head(context.Context, uint64, string) (release.Head, error) { return p.head, nil }

func (p *platform) MembersOf(_ context.Context, _ uint64, _, id string) (map[string]string, error) {
	out := map[string]string{}
	for _, m := range p.releases[id].Members {
		out[m.LogicalSlug] = m.MemberDigest
	}
	return out, nil
}

func (p *platform) SaveDecision(_ context.Context, d release.Decision) (release.Decision, error) {
	d.ID = fmt.Sprintf("decision-%d", len(p.decisions)+1)
	p.decisions[d.ID] = d
	return d, nil
}

func (p *platform) DecisionByID(_ context.Context, _ uint64, _, id string) (release.Decision, error) {
	d, ok := p.decisions[id]
	if !ok {
		return release.Decision{}, &release.Error{Code: release.ErrorDecisionNotFound}
	}
	return d, nil
}

func (p *platform) ReleaseByID(_ context.Context, _ uint64, _, id string) (release.Release, error) {
	if id == "" {
		id = p.head.ReleaseID
	}
	r, ok := p.releases[id]
	if !ok {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return r, nil
}

func (p *platform) Activate(_ context.Context, w release.ActivationWrite) (release.Release, error) {
	if id, ok := p.nonces[w.Nonce]; ok {
		return p.releases[id], nil
	}
	if w.Expected != p.head {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseConflict}
	}
	p.activations++
	r := release.Release{
		ID: fmt.Sprintf("release-%d", p.activations), Epoch: p.head.Epoch + 1,
		BaseReleaseID: w.Expected.ReleaseID, CandidateID: w.CandidateID,
		DecisionDigest: w.DecisionDigest, Members: w.Members,
	}
	p.releases[r.ID], p.nonces[w.Nonce] = r, r.ID
	p.head = release.Head{ReleaseID: r.ID, Epoch: r.Epoch}
	return r, nil
}

// ---- revision store and evidence collaborators -------------------------------------------

type memoryRevisions struct{ rows map[string]expert.Revision }

func (m *memoryRevisions) CreateRevision(_ context.Context, r expert.Revision) error {
	if _, ok := m.rows[r.ID]; ok {
		return fmt.Errorf("revision %s exists", r.ID)
	}
	m.rows[r.ID] = r
	return nil
}

func (m *memoryRevisions) RevisionByID(_ context.Context, tenant uint64, space, id string) (expert.Revision, error) {
	r, ok := m.rows[id]
	if !ok || r.TenantID != tenant || r.SpaceID != space {
		return expert.Revision{}, &release.Error{Code: release.ErrorEvidenceNotFound}
	}
	return r, nil
}

// sourceRefs accepts the seeded PDF source; anything else is unknown to it.
type sourceRefs struct{}

func (sourceRefs) Resolve(_ context.Context, ref string) (bool, error) {
	return strings.HasPrefix(ref, "source:v1:"), nil
}

type pdfVerifier struct{}

func (pdfVerifier) VerifyEvidence(_ context.Context, checks []release.EvidenceCheck) error {
	for _, c := range checks {
		if c.Evidence.Locator.Kind != "PDF_TEXT_SPAN" {
			return &release.Error{Code: release.ErrorEvidenceUnsupported, Detail: c.Path}
		}
	}
	return nil
}

func contractSchemas(t *testing.T) map[string][]byte {
	t.Helper()
	out := map[string][]byte{}
	for _, name := range []string{"candidate_bundle", "evidence", "locator"} {
		raw, err := os.ReadFile("../../../contracts/" + name + ".schema.json")
		require.NoError(t, err)
		out[name] = raw
	}
	return out
}

// ---- fixture ------------------------------------------------------------------------------

func digestOf(t *testing.T, payload any) string {
	t.Helper()
	raw, err := json.Marshal(payload)
	require.NoError(t, err)
	var decoded any
	require.NoError(t, json.Unmarshal(raw, &decoded))
	canonical, err := json.Marshal(decoded)
	require.NoError(t, err)
	sum := sha256.Sum256(canonical)
	return hex.EncodeToString(sum[:])
}

func claimMember(t *testing.T, slug, value string) map[string]any {
	t.Helper()
	ref := "source:v1:k-1:1:" + fileSHA
	payload := map[string]any{
		"claim_id": slug, "logical_key": slug, "subject_ref": "P", "predicate": strings.Split(slug, "/")[1],
		"state": "present", "value": value, "origin": "SOURCE_SUPPORTED", "expert_lock": false,
		"evidence": []any{map[string]any{
			"source_ref": ref, "file_sha256": fileSHA, "quote": value, "access_scope": "space",
			"locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1, "start": 0, "end": len([]rune(value))},
		}},
		"maintenance": map[string]any{"revision_no": 0, "changed_by": "compile", "first_release_id": "release-0"},
	}
	return map[string]any{
		"kind": "claim", "logical_slug": slug, "payload": payload, "member_digest": digestOf(t, payload),
		"evidence_refs": []string{ref}, "access_scope": "space",
	}
}

type fixture struct {
	platform  *platform
	revisions *memoryRevisions
	releases  *release.Service
	editor    *expert.Service
	first     release.Release
}

func setup(t *testing.T) fixture {
	t.Helper()
	p, revisions := newPlatform(), &memoryRevisions{rows: map[string]expert.Revision{}}
	releases := release.NewService(p, expert.NewResolver(revisions, sourceRefs{}), contractSchemas(t),
		release.WithPublisher(p), release.WithEvidenceVerifier(expert.NewVerifier(revisions, pdfVerifier{})))
	ids := 0
	editor := expert.NewService(releases, revisions,
		expert.WithClock(func() time.Time { return fixedAt }),
		expert.WithIDs(func() string { ids++; return fmt.Sprintf("rev-%d", ids) }))
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
		"members": []any{claimMember(t, "P/waiting", "90日"), claimMember(t, "P/grace", "60日")},
	})
	require.NoError(t, err)
	ctx := context.Background()
	c, err := releases.Receive(ctx, harness, spaceID, raw)
	require.NoError(t, err)
	d, err := releases.Decide(ctx, harness, spaceID, c.ID, approve)
	require.NoError(t, err)
	first, err := releases.Activate(ctx, harness, spaceID, c.ID, d.ID)
	require.NoError(t, err)
	return fixture{platform: p, revisions: revisions, releases: releases, editor: editor, first: first}
}

func memberOf(r release.Release, slug string) release.Member {
	for _, m := range r.Members {
		if m.LogicalSlug == slug {
			return m
		}
	}
	return release.Member{}
}

func payloadOf(t *testing.T, m release.Member) map[string]any {
	t.Helper()
	var out map[string]any
	require.NoError(t, json.Unmarshal(m.Payload, &out))
	return out
}

func edit(f fixture, in expert.EditInput) (expert.Result, error) {
	if in.BaseReleaseID == "" {
		in.BaseReleaseID = f.first.ID
	}
	if in.BaseMemberDigest == "" {
		in.BaseMemberDigest = memberOf(f.first, in.MemberSlug).MemberDigest
	}
	return f.editor.Edit(context.Background(), admin, "admin", spaceID, in)
}

func codeOf(t *testing.T, err error) string {
	t.Helper()
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	return failure.Code
}

// ---- acceptance ---------------------------------------------------------------------------

func TestAnExpertEditPublishesTheValueWithAnExpertCitationAndLock(t *testing.T) {
	f := setup(t)
	result, err := edit(f, expert.EditInput{
		MemberSlug: "P/waiting", State: "present", Value: "180日", Reason: "2026版条款将等待期改为180日",
	})
	require.NoError(t, err)
	require.Equal(t, f.first.ID, result.Release.BaseReleaseID)
	require.Equal(t, memberOf(f.first, "P/grace").MemberDigest, memberOf(result.Release, "P/grace").MemberDigest,
		"other members carry over unchanged")

	edited := memberOf(result.Release, "P/waiting")
	payload := payloadOf(t, edited)
	require.Equal(t, "present", payload["state"])
	require.Equal(t, "180日", payload["value"])
	require.Equal(t, "EXPERT_REVISION", payload["origin"])
	require.Equal(t, true, payload["expert_lock"])
	maintenance := payload["maintenance"].(map[string]any)
	require.EqualValues(t, 1, maintenance["revision_no"])
	require.Equal(t, "expert", maintenance["changed_by"])
	require.Equal(t, "release-0", maintenance["first_release_id"])
	review := payload["review"].(map[string]any)
	require.Equal(t, "human", review["mode"])
	require.Equal(t, "admin-1", review["reviewer"])

	evidence := payload["evidence"].([]any)
	require.Len(t, evidence, 1)
	ev := evidence[0].(map[string]any)
	locator := ev["locator"].(map[string]any)
	require.Equal(t, "EXPERT_REVISION", locator["kind"])
	require.Equal(t, result.Revision.ID, locator["revision_record_id"])
	require.Equal(t, result.Revision.RecordSHA256, ev["file_sha256"])
	require.Equal(t, "180日", ev["quote"])
	require.Equal(t, []string{"expert:v1:" + result.Revision.ID + ":" + result.Revision.RecordSHA256},
		edited.EvidenceRefs)

	stored, err := f.revisions.RevisionByID(context.Background(), 7, spaceID, result.Revision.ID)
	require.NoError(t, err)
	require.Equal(t, expert.Value{State: "present", Value: "90日"}, stored.Before)
	require.Equal(t, expert.Value{State: "present", Value: "180日"}, stored.After)
	require.Equal(t, "admin-1", stored.Actor)
	require.Equal(t, "2026版条款将等待期改为180日", stored.Reason)
	require.Equal(t, "P/waiting", stored.MemberSlug)
	require.True(t, fixedAt.Equal(stored.RecordedAt))
}

func TestAnExplicitAbsenceCitesTheReason(t *testing.T) {
	f := setup(t)
	result, err := edit(f, expert.EditInput{
		MemberSlug: "P/grace", State: "absent_explicitly", Reason: "本产品为趸交，不设宽限期",
	})
	require.NoError(t, err)
	payload := payloadOf(t, memberOf(result.Release, "P/grace"))
	require.Equal(t, "absent_explicitly", payload["state"])
	require.Nil(t, payload["value"])
	ev := payload["evidence"].([]any)[0].(map[string]any)
	require.Equal(t, "本产品为趸交，不设宽限期", ev["quote"])
}

func TestAnUnknownEditHasNoCitationButKeepsTheRecord(t *testing.T) {
	f := setup(t)
	result, err := edit(f, expert.EditInput{MemberSlug: "P/grace", State: "unknown", Reason: "原值来源不可靠"})
	require.NoError(t, err)
	payload := payloadOf(t, memberOf(result.Release, "P/grace"))
	require.Equal(t, "unknown", payload["state"])
	require.Equal(t, "NOT_IN_MATERIAL", payload["unknown_reason"])
	require.Empty(t, payload["evidence"])
	require.Empty(t, memberOf(result.Release, "P/grace").EvidenceRefs)
	require.Len(t, f.revisions.rows, 1)
}

func TestAStaleEditWritesNothing(t *testing.T) {
	f := setup(t)
	_, err := edit(f, expert.EditInput{
		MemberSlug: "P/waiting", State: "present", Value: "180日", Reason: "r",
		BaseMemberDigest: strings.Repeat("0", 64),
	})
	require.Equal(t, expert.ErrorStale, codeOf(t, err))

	moved, err := edit(f, expert.EditInput{MemberSlug: "P/grace", State: "present", Value: "30日", Reason: "r"})
	require.NoError(t, err)
	activations, stored := f.platform.activations, len(f.revisions.rows)
	_, err = f.editor.Edit(context.Background(), admin, "admin", spaceID, expert.EditInput{
		BaseReleaseID: f.first.ID, MemberSlug: "P/waiting", State: "present", Value: "180日", Reason: "r",
		BaseMemberDigest: memberOf(moved.Release, "P/waiting").MemberDigest,
	})
	require.Equal(t, expert.ErrorStale, codeOf(t, err), "the Active release moved on")
	require.Equal(t, activations, f.platform.activations)
	require.Len(t, f.revisions.rows, stored)
}

func TestInvalidEditsWriteNothing(t *testing.T) {
	for name, tc := range map[string]struct {
		in   expert.EditInput
		code string
	}{
		"present without a value": {expert.EditInput{MemberSlug: "P/waiting", State: "present", Reason: "r"}, expert.ErrorInvalid},
		"blank reason":            {expert.EditInput{MemberSlug: "P/waiting", State: "present", Value: "1日", Reason: " "}, expert.ErrorInvalid},
		"unknown state":           {expert.EditInput{MemberSlug: "P/waiting", State: "maybe", Value: "1日", Reason: "r"}, expert.ErrorInvalid},
		"no change":               {expert.EditInput{MemberSlug: "P/waiting", State: "present", Value: "90日", Reason: "r"}, expert.ErrorInvalid},
		"missing member":          {expert.EditInput{MemberSlug: "P/none", State: "present", Value: "1日", Reason: "r", BaseMemberDigest: strings.Repeat("1", 64)}, release.ErrorMemberNotFound},
	} {
		t.Run(name, func(t *testing.T) {
			f := setup(t)
			_, err := edit(f, tc.in)
			require.Equal(t, tc.code, codeOf(t, err))
			require.Empty(t, f.revisions.rows)
			require.Equal(t, 1, f.platform.activations)
		})
	}
}

func TestForgedExpertReferencesAreRefused(t *testing.T) {
	f := setup(t)
	result, err := edit(f, expert.EditInput{MemberSlug: "P/waiting", State: "present", Value: "180日", Reason: "r"})
	require.NoError(t, err)
	good := memberOf(result.Release, "P/waiting")
	for name, mutate := range map[string]func(map[string]any) []string{
		"unknown record": func(p map[string]any) []string {
			ev := p["evidence"].([]any)[0].(map[string]any)
			ev["locator"].(map[string]any)["revision_record_id"] = "rev-forged"
			ref := "expert:v1:rev-forged:" + ev["file_sha256"].(string)
			ev["source_ref"] = ref
			return []string{ref}
		},
		"quote differs from the record": func(p map[string]any) []string {
			ev := p["evidence"].([]any)[0].(map[string]any)
			ev["quote"] = "365日"
			return []string{ev["source_ref"].(string)}
		},
	} {
		t.Run(name, func(t *testing.T) {
			payload := payloadOf(t, good)
			refs := mutate(payload)
			raw, err := json.Marshal(map[string]any{
				"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
				"base_release_id": result.Release.ID,
				"members": []any{map[string]any{
					"kind": "claim", "logical_slug": "P/waiting", "payload": payload,
					"member_digest": digestOf(t, payload), "evidence_refs": refs, "access_scope": "space",
				}},
			})
			require.NoError(t, err)
			_, err = f.releases.Receive(context.Background(), harness, spaceID, raw)
			require.Error(t, err, "a forged expert citation must not be accepted")
		})
	}
}
