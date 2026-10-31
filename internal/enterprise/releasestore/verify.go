package releasestore

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

// PageReader reads the verified pages of one captured source revision (*source.Service).
type PageReader interface {
	Pages(ctx context.Context, scope source.Scope, knowledgeID string, attempt int64) (*source.PageSet, error)
}

// EvidenceVerifier checks PDF_TEXT_SPAN evidence against the captured page text of the exact
// source revision it cites (S4c-2b-2 Spec §3.2), and Office evidence against the one captured block
// it names (S11d Spec §2.2). Captured artifacts are written once per attempt, so verifying at
// submission is enough; activation does not repeat it.
type EvidenceVerifier struct {
	spaces Spaces
	pages  PageReader
}

// NewEvidenceVerifier builds the verifier for the configured Spaces.
func NewEvidenceVerifier(spaces Spaces, pages PageReader) *EvidenceVerifier {
	return &EvidenceVerifier{spaces: spaces, pages: pages}
}

// VerifyEvidence reads each cited (knowledge, attempt) once per call and stops at the first
// failing check. Details carry the JSON pointer and a reason category, never source text.
func (v *EvidenceVerifier) VerifyEvidence(ctx context.Context, checks []release.EvidenceCheck) error {
	scope, ok := release.ScopeFromContext(ctx)
	if !ok {
		return errNoScope
	}
	if len(checks) == 0 {
		return nil
	}
	if _, err := v.spaces.Scope(scope.Principal.TenantID, scope.SpaceID); err != nil || v.pages == nil {
		return refuse(release.ErrorEvidenceUnverifiable, checks[0].Path, "the Space has no captured sources")
	}
	read := source.Scope{TenantID: scope.Principal.TenantID, SpaceID: scope.SpaceID}
	cache := map[string]*source.PageSet{}
	for _, c := range checks {
		if err := v.verify(ctx, read, cache, c); err != nil {
			return err
		}
	}
	return nil
}

func (v *EvidenceVerifier) verify(
	ctx context.Context, scope source.Scope, cache map[string]*source.PageSet, c release.EvidenceCheck,
) error {
	ev := c.Evidence
	ref, ok := release.ParseSourceRef(ev.SourceRef)
	if !ok {
		return refuse(release.ErrorEvidenceUnsupported, c.Path, "source reference format")
	}
	cited := ref.FileSHA256
	if strings.ToLower(ev.FileSHA256) != cited {
		return refuse(release.ErrorEvidenceMismatch, c.Path, "file fingerprint")
	}
	office := source.OfficeKind(ev.Locator.Kind)
	if (ev.Locator.Kind != "PDF_TEXT_SPAN" && !office) || (ev.Match != "" && ev.Match != "EXACT") {
		return refuse(release.ErrorEvidenceUnsupported, c.Path, "locator kind or match")
	}
	if office && !officeFields(ev.Locator, c.LocatorKeys) {
		return refuse(release.ErrorEvidenceUnsupported, c.Path, "Office locator fields")
	}
	key := ref.KnowledgeID + ":" + strconv.FormatInt(ref.ParseAttempt, 10)
	set, cached := cache[key]
	if !cached {
		var err error
		set, err = v.pages.Pages(ctx, scope, ref.KnowledgeID, ref.ParseAttempt)
		if err != nil {
			return sourceFailure(c.Path, err)
		}
		cache[key] = set
	}
	if set == nil || strings.ToLower(set.DocumentSHA256) != cited {
		return refuse(release.ErrorEvidenceMismatch, c.Path, "captured revision fingerprint")
	}
	if office {
		return verifyBlock(c.Path, set, ev)
	}
	if set.LocatorKind() != ev.Locator.Kind {
		return refuse(release.ErrorEvidenceMismatch, c.Path, "captured format")
	}
	loc := ev.Locator
	if loc.Page == nil || loc.Start == nil || loc.End == nil || *loc.Page < 1 || *loc.Page > len(set.Pages) {
		return refuse(release.ErrorEvidenceMismatch, c.Path, "page")
	}
	text := []rune(set.Pages[*loc.Page-1].Text)
	if *loc.Start < 0 || *loc.Start >= *loc.End || *loc.End > len(text) {
		return refuse(release.ErrorEvidenceMismatch, c.Path, "code-point range")
	}
	return sameQuote(c.Path, ev, string(text[*loc.Start:*loc.End]))
}

// officeLocatorKeys are the keys each Office locator carries with a value, sorted (S11d Spec §2.1):
// its block's fields, the page and the page-text offsets. Shapes, cells and boxes are not captured.
var officeLocatorKeys = map[string][]string{
	"PPTX_SHAPE":      {"end", "kind", "page", "slide", "start"},
	"DOCX_BLOCK":      {"block_index", "end", "kind", "page", "start"},
	"XLSX_CELL_RANGE": {"cell_range", "end", "kind", "page", "sheet", "start"},
}

// officeFields reports whether an Office locator has exactly the keys of its kind; keys the
// submission did not list fail closed.
func officeFields(loc release.Locator, keys []string) bool {
	return slices.Equal(keys, officeLocatorKeys[loc.Kind]) && loc.Page != nil && loc.Start != nil && loc.End != nil
}

// verifyBlock checks Office evidence on the captured pages it cites: one block holds the range and
// carries the cited locator, and the quote is the verbatim page slice (S11d Spec §2.2 steps 7–11).
func verifyBlock(path string, set *source.PageSet, ev release.Evidence) error {
	loc := ev.Locator
	view, err := set.Locate(ooxml.Locator{
		Kind: loc.Kind, Slide: loc.Slide, BlockIndex: loc.BlockIndex, Sheet: loc.Sheet, CellRange: loc.CellRange,
	}, *loc.Page, *loc.Start, *loc.End)
	if err != nil {
		reason := "block"
		var failure *source.Error
		if errors.As(err, &failure) {
			reason = failure.Detail
		}
		return refuse(release.ErrorEvidenceMismatch, path, reason)
	}
	return sameQuote(path, ev, view.Quote)
}

// sameQuote requires the quote to be the captured slice verbatim and a given digest to be its own.
func sameQuote(path string, ev release.Evidence, captured string) error {
	if captured != ev.Quote {
		return refuse(release.ErrorEvidenceMismatch, path, "quote")
	}
	if ev.QuoteSHA256 != "" && strings.ToLower(ev.QuoteSHA256) != release.QuoteDigest(ev.Quote) {
		return refuse(release.ErrorEvidenceMismatch, path, "quote digest")
	}
	return nil
}

// sourceFailure separates sources that cannot serve as evidence from storage outages.
func sourceFailure(path string, err error) error {
	var failure *source.Error
	if errors.As(err, &failure) {
		switch failure.Code {
		case source.ErrorNotCaptured, source.ErrorSourceNotFound, source.ErrorIntegrity:
			return refuse(release.ErrorEvidenceUnverifiable, path, "source revision cannot serve as evidence")
		}
	}
	return fmt.Errorf("read captured source pages: %w", err)
}

func refuse(code, path, reason string) error {
	return &release.Error{Code: code, Detail: path + ": " + reason}
}
