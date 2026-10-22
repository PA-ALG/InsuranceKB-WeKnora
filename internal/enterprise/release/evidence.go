package release

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// Evidence failures of a submission or a citation (S4c-2b-2 Spec §3.1, §3.4).
const (
	ErrorEvidenceMismatch     = "EVIDENCE_MISMATCH"
	ErrorEvidenceUnsupported  = "EVIDENCE_UNSUPPORTED"
	ErrorEvidenceUnverifiable = "EVIDENCE_UNVERIFIABLE"
	ErrorMemberNotFound       = "MEMBER_NOT_FOUND"
	ErrorEvidenceNotFound     = "EVIDENCE_NOT_FOUND"
)

// Evidence mirrors contracts/evidence.schema.json; Locator keeps only the fields this slice verifies.
type Evidence struct {
	SourceRef   string  `json:"source_ref"`
	FileSHA256  string  `json:"file_sha256"`
	Locator     Locator `json:"locator"`
	Quote       string  `json:"quote"`
	QuoteSHA256 string  `json:"quote_sha256,omitempty"`
	Match       string  `json:"match,omitempty"`
	AccessScope string  `json:"access_scope"`
}

// Locator holds the PDF_TEXT_SPAN coordinates: one-based page, page-local code points [start, end),
// or for an EXPERT_REVISION citation the revision record it names (S9a).
type Locator struct {
	Kind             string `json:"kind"`
	Page             *int   `json:"page,omitempty"`
	Start            *int   `json:"start,omitempty"`
	End              *int   `json:"end,omitempty"`
	RevisionRecordID string `json:"revision_record_id,omitempty"`
}

// EvidenceCheck is one evidence object with its JSON pointer inside the bundle.
type EvidenceCheck struct {
	Path     string // e.g. /members/0/payload/evidence/1
	Evidence Evidence
}

// EvidenceVerifier checks evidence against the captured sources of the request scope
// (ScopeFromContext). It returns nil or a *Error with ErrorEvidenceMismatch,
// ErrorEvidenceUnsupported or ErrorEvidenceUnverifiable whose Detail starts with the
// failing Path; any other error is a storage failure and rejects the bundle.
type EvidenceVerifier interface {
	VerifyEvidence(ctx context.Context, checks []EvidenceCheck) error
}

// WithEvidenceVerifier enables submission-time verification of payload evidence.
func WithEvidenceVerifier(v EvidenceVerifier) Option { return func(s *Service) { s.verifier = v } }

// EvidenceAt is one evidence object of a published member, with the member's origin so
// readers can label model-generated content.
type EvidenceAt struct {
	ReleaseID string   `json:"release_id"`
	Slug      string   `json:"member"`
	Index     int      `json:"evidence_index"`
	Origin    string   `json:"origin"`
	Evidence  Evidence `json:"evidence"`
}

// citedOrigins must rest on evidence unless the field is unknown. MODEL_GENERATED content
// may be published without a source; its origin travels with the member so it stays labelled.
var citedOrigins = map[string]bool{
	"SOURCE_SUPPORTED": true, "MIXED": true, "EXPERT_REVISION": true, "STRUCTURED_IMPORT": true,
}

// memberPayload is the generic part of a payload this slice reads: origin, state and evidence.
type memberPayload struct {
	origin, state string
	hasEvidence   bool
	evidence      []any // exact JSON values, numbers as json.Number
}

func readPayload(raw json.RawMessage) (memberPayload, error) {
	doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		return memberPayload{}, err
	}
	object, ok := doc.(map[string]any)
	if !ok {
		return memberPayload{}, nil
	}
	out := memberPayload{}
	out.origin, _ = object["origin"].(string)
	out.state, _ = object["state"].(string)
	value, present := object["evidence"]
	if !present {
		return out, nil
	}
	out.hasEvidence = true
	items, ok := value.([]any)
	if !ok {
		return memberPayload{}, errNotAnArray
	}
	out.evidence = items
	return out, nil
}

var errNotAnArray = fmt.Errorf("evidence must be an array")

func decodeEvidence(item any) (Evidence, error) {
	raw, err := json.Marshal(item)
	if err != nil {
		return Evidence{}, err
	}
	var ev Evidence
	return ev, json.Unmarshal(raw, &ev)
}

// checkEvidence applies the S4c-2b-2 rules to every member and verifies all evidence in one call.
func (s *Service) checkEvidence(ctx context.Context, b Bundle) error {
	var checks []EvidenceCheck
	for i, m := range b.Members {
		payload, err := readPayload(m.Payload)
		if err != nil {
			return invalid(fmt.Sprintf("evidence must be an array at /members/%d/payload/evidence", i))
		}
		if payload.hasEvidence && s.evidenceSchema == nil {
			return &Error{Code: ErrorEvidenceUnverifiable, Detail: "evidence contract is not configured"}
		}
		sources := make(map[string]bool, len(payload.evidence))
		for j, item := range payload.evidence {
			path := fmt.Sprintf("/members/%d/payload/evidence/%d", i, j)
			if err := s.evidenceSchema.Validate(item); err != nil {
				return invalid("evidence does not match the contract at " + path)
			}
			ev, err := decodeEvidence(item)
			if err != nil {
				return invalid("evidence does not match the contract at " + path)
			}
			sources[ev.SourceRef] = true
			checks = append(checks, EvidenceCheck{Path: path, Evidence: ev})
		}
		if payload.hasEvidence && !sameRefs(sources, m.EvidenceRefs) {
			return invalid(fmt.Sprintf("evidence sources differ from /members/%d/evidence_refs", i))
		}
		if citedOrigins[payload.origin] && payload.state != "unknown" && len(payload.evidence) == 0 {
			return invalid(fmt.Sprintf("a %s member needs evidence at /members/%d/payload", payload.origin, i))
		}
	}
	if len(checks) == 0 {
		return nil
	}
	if s.verifier == nil {
		return &Error{Code: ErrorEvidenceUnverifiable, Detail: "evidence verification is not configured"}
	}
	return s.verifier.VerifyEvidence(ctx, checks)
}

func sameRefs(sources map[string]bool, refs []string) bool {
	listed := make(map[string]bool, len(refs))
	for _, ref := range refs {
		listed[ref] = true
	}
	if len(listed) != len(sources) {
		return false
	}
	for ref := range sources {
		if !listed[ref] {
			return false
		}
	}
	return true
}

// Evidence returns one evidence object of a member of an explicitly named release.
func (s *Service) Evidence(
	ctx context.Context, p Principal, spaceID, releaseID, slug string, index int,
) (EvidenceAt, error) {
	if err := s.canPublish(p, spaceID); err != nil {
		return EvidenceAt{}, err
	}
	if id := strings.TrimSpace(releaseID); id == "" || id == "active" {
		return EvidenceAt{}, &Error{Code: ErrorReleaseNotFound, Detail: "an explicit release id is required"}
	}
	r, err := s.publisher.ReleaseByID(ctx, p.TenantID, spaceID, releaseID)
	if err != nil {
		return EvidenceAt{}, err
	}
	for _, m := range r.Members {
		if m.LogicalSlug != slug {
			continue
		}
		payload, err := readPayload(m.Payload)
		if err != nil || index < 0 || index >= len(payload.evidence) {
			return EvidenceAt{}, &Error{Code: ErrorEvidenceNotFound, Detail: "the member has no such evidence"}
		}
		ev, err := decodeEvidence(payload.evidence[index])
		if err != nil {
			return EvidenceAt{}, &Error{Code: ErrorEvidenceNotFound, Detail: "the member has no such evidence"}
		}
		return EvidenceAt{ReleaseID: r.ID, Slug: slug, Index: index, Origin: payload.origin, Evidence: ev}, nil
	}
	return EvidenceAt{}, &Error{Code: ErrorMemberNotFound, Detail: "the release has no such member"}
}

// SourceRef is the platform evidence reference frozen by S4c-2a Spec §3.2:
// source:v1:<knowledge_id>:<parse_attempt>:<file_sha256>.
type SourceRef struct {
	KnowledgeID  string
	ParseAttempt int64
	FileSHA256   string
}

var sourceRefPattern = regexp.MustCompile(
	`^source:v1:([A-Za-z0-9][A-Za-z0-9_-]{0,63}):([1-9][0-9]{0,18}):([0-9a-f]{64})$`,
)

// ParseSourceRef accepts exactly the frozen format; anything else is not a platform source.
func ParseSourceRef(ref string) (SourceRef, bool) {
	parts := sourceRefPattern.FindStringSubmatch(ref)
	if parts == nil {
		return SourceRef{}, false
	}
	attempt, err := strconv.ParseInt(parts[2], 10, 64)
	if err != nil {
		return SourceRef{}, false
	}
	return SourceRef{KnowledgeID: parts[1], ParseAttempt: attempt, FileSHA256: parts[3]}, true
}
