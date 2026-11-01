// Package knowledge projects published, Space-visible members for read-only queries.
package knowledge

import (
	"context"
	"reflect"
	"strings"
	"time"
	"unicode"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"golang.org/x/text/unicode/norm"
)

// Reader must return only members visible to this tenant and Space at the named release.
type Reader interface {
	ReleaseByID(ctx context.Context, tenantID uint64, spaceID, releaseID string) (release.Release, error)
}

// Evidence retains one Claim citation and its original position.
type Evidence struct {
	Index     int
	Quote     string
	Page      int
	SourceRef string
}

// Field is a published Claim with its entity, display title and provenance. EntityVersion is the
// entity's version label, empty for an entity without a lifecycle.
type Field struct {
	ReleaseID, Slug, EntityID, EntityName, EntityVersion, FieldKey, FieldTitle, State, Value, Origin, Review string
	Evidence                                                                                                 []Evidence
	// Method marks method knowledge (SK-3): Note is its profile's reading note with the entity's
	// notice sentence, and Items[i] is the list item Evidence[i] supports, when they line up.
	Method bool
	Note   string
	Items  []string
}

// Entity is the published identity, aliases and classification of an entry, with its version
// data: Status is evaluated for the read; Predecessors and Successors are visible entity IDs.
type Entity struct {
	EntityID, Name           string
	Kind, Notice             string // the entity type and SK-2's identifiers.notice flag
	Method                   bool   // a method-knowledge profile serves the type (SK-3 §1)
	Names, Labels            []string
	Lifecycle                *Lifecycle
	Family                   *Family
	Status                   SaleStatus
	Predecessors, Successors []string
}

// Statement is a concept explanation with exact Claim references.
type Statement struct {
	Text string
	Refs []string
}

// Concept is a model-written reading aid whose fact references remain visible and current.
type Concept struct {
	ReleaseID, Key, Title, Definition, Explanation string
	Statements                                     []Statement
	OmittedStatements                              int
}

// Service has no release cache: each query remains within its explicit read scope. now is the
// clock sale status is evaluated by (time.Now when nil).
type Service struct {
	reader Reader
	now    func() time.Time
}

// NewService constructs a stateless query service over the supplied release reader.
func NewService(reader Reader) *Service { return &Service{reader: reader} }

func (s *Service) read(ctx context.Context, tenantID uint64, spaceID, releaseID string) (*releaseIndex, error) {
	if err := validateRead(ctx, tenantID, spaceID, releaseID); err != nil {
		return nil, err
	}
	if s == nil || missingReader(s.reader) {
		return nil, &release.Error{Code: release.ErrorServiceUnavailable, Detail: "knowledge reader is unavailable"}
	}
	r, err := s.reader.ReleaseByID(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if r.ID != releaseID {
		return nil, &release.Error{Code: release.ErrorReleaseConflict, Detail: "reader returned another release"}
	}
	index, err := indexRelease(ctx, r)
	if err != nil {
		return nil, err
	}
	index.evaluate(s.today())
	return index, nil
}

func validateRead(ctx context.Context, tenantID uint64, spaceID, releaseID string) error {
	if ctx == nil {
		return &release.Error{Code: release.ErrorInvalidRequest, Detail: "context is required"}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if tenantID == 0 || strings.TrimSpace(spaceID) == "" {
		return &release.Error{Code: release.ErrorReleaseAccessDenied, Detail: "tenant and Space are required"}
	}
	if strings.TrimSpace(releaseID) == "" || normalize(releaseID) == "active" {
		return &release.Error{Code: release.ErrorInvalidRequest, Detail: "an explicit release ID is required"}
	}
	return nil
}

func missingReader(reader Reader) bool {
	if reader == nil {
		return true
	}
	v := reflect.ValueOf(reader)
	switch v.Kind() {
	case reflect.Chan, reflect.Func, reflect.Interface, reflect.Map, reflect.Pointer, reflect.Slice:
		return v.IsNil()
	}
	return false
}

func folded(value string) string {
	return cases.Lower(language.Und).String(norm.NFKC.String(value))
}

func normalize(value string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsSpace(r) || r == '\uFEFF' {
			return -1
		}
		return r
	}, folded(value))
}

func searchFold(value string) string {
	return strings.Join(strings.FieldsFunc(folded(value), browserWhitespace), " ")
}

// S3h-1 uses JavaScript \s and String.trim: NEL is not whitespace there,
// while a BOM is. Keep this boundary identical to the published browser search.
func browserWhitespace(r rune) bool {
	return (r >= '\t' && r <= '\r') || r == ' ' || r == '\u00A0' || r == '\u1680' ||
		(r >= '\u2000' && r <= '\u200A') || r == '\u2028' || r == '\u2029' ||
		r == '\u202F' || r == '\u205F' || r == '\u3000' || r == '\uFEFF'
}

func bigrams(value string) map[string]bool {
	runes := []rune(value)
	out := make(map[string]bool, len(runes))
	for i := 1; i < len(runes); i++ {
		out[string(runes[i-1:i+1])] = true
	}
	return out
}

func sharedBigrams(left, right map[string]bool) int {
	count := 0
	for pair := range left {
		if right[pair] {
			count++
		}
	}
	return count
}

func intersects(left, right []string) bool {
	for _, a := range left {
		for _, b := range right {
			if a == b {
				return true
			}
		}
	}
	return false
}
