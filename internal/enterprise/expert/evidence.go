package expert

import (
	"context"
	"errors"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// NewResolver resolves expert references from the revision store and delegates every other
// reference to next. A missing or mismatching record resolves to false.
func NewResolver(store Store, next release.EvidenceResolver) release.EvidenceResolver {
	return resolver{store: store, next: next}
}

type resolver struct {
	store Store
	next  release.EvidenceResolver
}

func (r resolver) Resolve(ctx context.Context, ref string) (bool, error) {
	id, sha, ok := ParseSourceRef(ref)
	if !ok {
		if strings.HasPrefix(ref, refPrefix) || r.next == nil {
			return false, nil
		}
		return r.next.Resolve(ctx, ref)
	}
	record, err := lookup(ctx, r.store, id)
	if err != nil || record == nil {
		return false, err
	}
	return record.RecordSHA256 == sha, nil
}

// NewVerifier checks EXPERT_REVISION evidence against its revision record and delegates every
// other check to next.
func NewVerifier(store Store, next release.EvidenceVerifier) release.EvidenceVerifier {
	return verifier{store: store, next: next}
}

type verifier struct {
	store Store
	next  release.EvidenceVerifier
}

func (v verifier) VerifyEvidence(ctx context.Context, checks []release.EvidenceCheck) error {
	var others []release.EvidenceCheck
	for _, c := range checks {
		if c.Evidence.Locator.Kind != LocatorKind {
			others = append(others, c)
			continue
		}
		if err := v.verify(ctx, c); err != nil {
			return err
		}
	}
	if len(others) == 0 {
		return nil
	}
	if v.next == nil {
		return failure(release.ErrorEvidenceUnverifiable, others[0].Path+": evidence verification is not configured")
	}
	return v.next.VerifyEvidence(ctx, others)
}

func (v verifier) verify(ctx context.Context, c release.EvidenceCheck) error {
	id, err := citedRecordID(c.Path, c.Evidence)
	if err != nil {
		return err
	}
	record, err := lookup(ctx, v.store, id)
	if err != nil {
		return err
	}
	return matchRecord(c.Path, c.Evidence, record)
}

// citedRecordID reads the record an EXPERT_REVISION evidence object names; the reference and
// the locator must name the same record.
func citedRecordID(path string, ev release.Evidence) (string, error) {
	id, _, ok := ParseSourceRef(ev.SourceRef)
	if !ok || ev.Locator.Kind != LocatorKind || ev.Locator.RevisionRecordID != id {
		return "", failure(release.ErrorEvidenceMismatch, path+": expert revision reference")
	}
	if ev.Match != "" && ev.Match != "EXACT" {
		return "", failure(release.ErrorEvidenceUnsupported, path+": match")
	}
	return id, nil
}

// matchRecord checks that the evidence quotes exactly the record it names, by its digest.
func matchRecord(path string, ev release.Evidence, record *Revision) error {
	_, sha, _ := ParseSourceRef(ev.SourceRef)
	switch {
	case record == nil:
		return failure(release.ErrorEvidenceNotFound, path+": expert revision record")
	case record.RecordSHA256 != sha || strings.ToLower(ev.FileSHA256) != sha:
		return failure(release.ErrorEvidenceMismatch, path+": record fingerprint")
	case record.After.State == "unknown" || ev.Quote != citedQuote(*record):
		return failure(release.ErrorEvidenceMismatch, path+": quote")
	case ev.QuoteSHA256 != "" && strings.ToLower(ev.QuoteSHA256) != release.QuoteDigest(ev.Quote):
		return failure(release.ErrorEvidenceMismatch, path+": quote digest")
	}
	return nil
}

// lookup reads a record in the request's scope; a record outside it, or missing, is nil.
func lookup(ctx context.Context, store Store, id string) (*Revision, error) {
	scope, ok := release.ScopeFromContext(ctx)
	if !ok || store == nil {
		return nil, failure(release.ErrorEvidenceUnverifiable, "expert revisions are not available")
	}
	record, err := store.RevisionByID(ctx, scope.Principal.TenantID, scope.SpaceID, id)
	var missing *release.Error
	if errors.As(err, &missing) && missing.Code == release.ErrorEvidenceNotFound {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &record, nil
}
