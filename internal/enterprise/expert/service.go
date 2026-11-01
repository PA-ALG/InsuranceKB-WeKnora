package expert

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// CompilerIdentity names expert edits in candidate bundles.
const CompilerIdentity = "weknora/expert-edit@1"

// Service validates, records and publishes expert edits.
type Service struct {
	releases *release.Service
	store    Store
	now      func() time.Time
	newID    func() string
}

// Option configures a Service.
type Option func(*Service)

// WithClock fixes the record time source (tests).
func WithClock(now func() time.Time) Option { return func(s *Service) { s.now = now } }

// WithIDs fixes the record identifier source (tests).
func WithIDs(newID func() string) Option { return func(s *Service) { s.newID = newID } }

// NewService builds the edit service on top of the release service that publishes candidates.
func NewService(releases *release.Service, store Store, options ...Option) *Service {
	s := &Service{releases: releases, store: store, now: time.Now, newID: randomID}
	for _, option := range options {
		option(s)
	}
	return s
}

func randomID() string {
	raw := make([]byte, 16)
	_, _ = rand.Read(raw)
	return "rev_" + hex.EncodeToString(raw)
}

var states = map[string]bool{"present": true, "absent_explicitly": true, "unknown": true}

// Edit records one expert edit and publishes it as a new release at once ("保存即上线").
// Nothing is written when the edit is invalid or no longer applies to the Active release.
func (s *Service) Edit(ctx context.Context, p release.Principal, role, spaceID string, in EditInput) (Result, error) {
	if s == nil || s.releases == nil || s.store == nil {
		return Result{}, failure(release.ErrorServiceUnavailable, "expert edits are not configured")
	}
	after, reason, err := validateInput(in)
	if err != nil {
		return Result{}, err
	}
	active, err := s.releases.Release(ctx, p, spaceID, "")
	if err != nil {
		return Result{}, err
	}
	if active.ID == "" || active.ID != in.BaseReleaseID {
		return Result{}, failure(ErrorStale, "the active release has moved on")
	}
	base, err := claimMember(active, in.MemberSlug)
	if err != nil {
		return Result{}, err
	}
	if base.MemberDigest != in.BaseMemberDigest {
		return Result{}, failure(ErrorStale, "the claim changed since it was read")
	}
	var payload map[string]any
	if err := json.Unmarshal(base.Payload, &payload); err != nil {
		return Result{}, failure(ErrorInvalid, "the claim payload is not an object")
	}
	subject, _ := payload["subject_ref"].(string)
	if release.MethodEntityTypes(active.Members)[release.EntityTypes(active.Members)[subject]] {
		return Result{}, failure(ErrorMethodKnowledge, "method knowledge is corrected through its source material")
	}
	before := Value{State: stringField(payload, "state"), Value: payload["value"]}
	if before.State == after.State && fmt.Sprint(before.Value) == fmt.Sprint(after.Value) {
		return Result{}, failure(ErrorInvalid, "the edit changes nothing")
	}
	// PostgreSQL keeps microseconds; the digested time must survive the round trip unchanged.
	record := Revision{
		ID: s.newID(), TenantID: p.TenantID, SpaceID: spaceID, BaseReleaseID: active.ID,
		MemberSlug: base.LogicalSlug, BaseMemberDigest: base.MemberDigest, Actor: p.Subject,
		Role: role, RecordedAt: s.now().UTC().Truncate(time.Microsecond), Before: before, After: after,
		Reason: reason,
	}
	record.RecordSHA256 = recordDigest(record)
	if err := s.store.CreateRevision(ctx, record); err != nil {
		return Result{}, fmt.Errorf("store expert revision: %w", err)
	}
	raw, err := editBundle(active, base, payload, record)
	if err != nil {
		return Result{}, err
	}
	candidate, err := s.releases.Receive(ctx, p, spaceID, raw)
	if err != nil {
		return Result{}, err
	}
	decision, err := s.releases.Decide(ctx, p, spaceID, candidate.ID, release.DecisionInput{
		Outcome: "approve", Mode: "human", Reason: reason,
	})
	if err != nil {
		return Result{}, err
	}
	published, err := s.releases.Activate(ctx, p, spaceID, candidate.ID, decision.ID)
	if err != nil {
		return Result{}, err
	}
	return Result{Release: published, Revision: record}, nil
}

func validateInput(in EditInput) (Value, string, error) {
	reason := strings.TrimSpace(in.Reason)
	switch {
	case !states[in.State]:
		return Value{}, "", failure(ErrorInvalid, "state must be present, absent_explicitly or unknown")
	case reason == "":
		return Value{}, "", failure(ErrorInvalid, "a reason is required")
	case utf8.RuneCountInString(reason) > MaxReasonRunes:
		return Value{}, "", failure(ErrorInvalid, "the reason is too long")
	case strings.TrimSpace(in.MemberSlug) == "" || strings.TrimSpace(in.BaseReleaseID) == "":
		return Value{}, "", failure(ErrorInvalid, "the edited claim and its release are required")
	}
	if in.State != "present" {
		return Value{State: in.State}, reason, nil
	}
	value := strings.TrimSpace(in.Value)
	if value == "" {
		return Value{}, "", failure(ErrorInvalid, "a present claim needs a value")
	}
	return Value{State: in.State, Value: value}, reason, nil
}

func claimMember(r release.Release, slug string) (release.Member, error) {
	for _, m := range r.Members {
		if m.LogicalSlug != slug {
			continue
		}
		if m.Kind != "claim" {
			return release.Member{}, failure(ErrorStale, "the member is no longer a claim")
		}
		return m, nil
	}
	return release.Member{}, failure(release.ErrorMemberNotFound, "the active release has no such member")
}

func stringField(payload map[string]any, key string) string {
	text, _ := payload[key].(string)
	return text
}

// editBundle replaces one claim: the expert value, an EXPERT_REVISION citation (none for
// unknown), expert_lock, a human review and the next maintenance revision. Every other payload
// field is kept as it was.
func editBundle(active release.Release, base release.Member, payload map[string]any, r Revision) ([]byte, error) {
	recordedAt := r.RecordedAt.Format(time.RFC3339Nano)
	payload["state"], payload["value"] = r.After.State, r.After.Value
	payload["origin"], payload["expert_lock"] = "EXPERT_REVISION", true
	payload["unknown_reason"] = nil
	if r.After.State == "unknown" {
		payload["unknown_reason"] = "NOT_IN_MATERIAL"
	}
	scope := base.AccessScope
	if scope == "" {
		scope = "space"
	}
	refs := []string{}
	evidence := []any{}
	if r.After.State != "unknown" {
		quote := citedQuote(r)
		evidence = append(evidence, map[string]any{
			"source_ref": SourceRef(r), "file_sha256": r.RecordSHA256, "quote": quote,
			"quote_sha256": release.QuoteDigest(quote), "match": "EXACT", "access_scope": scope,
			"locator": map[string]any{"kind": LocatorKind, "revision_record_id": r.ID},
		})
		refs = append(refs, SourceRef(r))
	}
	payload["evidence"] = evidence
	payload["review"] = map[string]any{"mode": "human", "reviewer": r.Actor, "reviewed_at": recordedAt}
	maintenance, _ := payload["maintenance"].(map[string]any)
	if maintenance == nil {
		maintenance = map[string]any{}
	}
	previous, _ := maintenance["revision_no"].(float64)
	maintenance["revision_no"] = int(previous) + 1
	maintenance["changed_by"], maintenance["changed_at"] = "expert", recordedAt
	maintenance["reason"], maintenance["last_changed_release_id"] = r.Reason, nil
	payload["maintenance"] = maintenance

	digest, err := canonicalDigest(payload)
	if err != nil {
		return nil, err
	}
	return json.Marshal(map[string]any{
		"contract_version": "1", "origin": "expert_edit", "compiler_identity": CompilerIdentity,
		"base_release_id": active.ID, "base_epoch": active.Epoch,
		"members": []any{map[string]any{
			"kind": "claim", "logical_slug": base.LogicalSlug, "payload": payload,
			"member_digest": digest, "evidence_refs": refs, "access_scope": scope,
		}},
		"review_plan": []any{map[string]any{"mode": "human"}},
	})
}

// canonicalDigest matches the release package's member digest: decode into any, then encode.
func canonicalDigest(value any) (string, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return "", errors.New("the edited claim cannot be encoded")
	}
	var decoded any
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return "", errors.New("the edited claim cannot be encoded")
	}
	canonical, _ := json.Marshal(decoded)
	sum := sha256.Sum256(canonical)
	return hex.EncodeToString(sum[:]), nil
}

// Citation opens the revision record an EXPERT_REVISION evidence object of the caller's Space
// cites, after checking the evidence still quotes exactly that record. The caller has already
// read the evidence from an explicit release the principal may see.
func (s *Service) Citation(
	ctx context.Context, p release.Principal, spaceID string, ev release.Evidence,
) (Revision, error) {
	if s == nil || s.store == nil {
		return Revision{}, failure(release.ErrorServiceUnavailable, "expert revisions are not configured")
	}
	id, err := citedRecordID("evidence", ev)
	if err != nil {
		return Revision{}, err
	}
	record, err := s.store.RevisionByID(ctx, p.TenantID, spaceID, id)
	if err != nil {
		return Revision{}, err
	}
	if err := matchRecord("evidence", ev, &record); err != nil {
		return Revision{}, err
	}
	return record, nil
}
