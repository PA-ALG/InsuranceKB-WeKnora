package source

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
)

// Service verifies and reads the pages of captured source revisions.
type Service struct{ store ArtifactStore }

// NewService constructs a read-only page service backed by store.
func NewService(store ArtifactStore) *Service { return &Service{store: store} }

// Pages verifies every page before returning any text. Offsets are Unicode code
// points; no whitespace or line-ending normalization is applied.
func (s *Service) Pages(ctx context.Context, scope Scope, knowledgeID string, attempt int64) (*PageSet, error) {
	v, err := s.load(ctx, scope, knowledgeID, attempt)
	if err != nil {
		return nil, err
	}
	return v.set, nil
}

// nativePage is the geometry part of one captured page; text is verified separately.
type nativePage struct {
	Number      int         `json:"page_number"`
	Start       *int        `json:"global_codepoint_start"`
	End         *int        `json:"global_codepoint_end"`
	SHA256      string      `json:"page_text_sha256"`
	Width       string      `json:"width_points"`
	Height      string      `json:"height_points"`
	Boxes       []charBox   `json:"bboxes"`
	Unavailable []codeRange `json:"unavailable_ranges"`
}

type charBox struct {
	BBox  []int `json:"bbox"`
	Start int   `json:"global_codepoint_start"`
	End   int   `json:"global_codepoint_end"`
}

type codeRange struct {
	Start int `json:"global_codepoint_start"`
	End   int `json:"global_codepoint_end"`
}

// verified is one loaded artifact whose every page passed integrity checks.
type verified struct {
	set    *PageSet
	native []nativePage
	office bool // an Office capture: pages and blocks come from its structure, no PDF geometry
}

func (s *Service) load(ctx context.Context, scope Scope, knowledgeID string, attempt int64) (*verified, error) {
	if scope.TenantID == 0 || strings.TrimSpace(scope.SpaceID) == "" ||
		strings.TrimSpace(knowledgeID) == "" || attempt <= 0 {
		return nil, &Error{Code: ErrorInvalidRequest, Detail: "scope, knowledge and a positive attempt are required"}
	}
	if s == nil || s.store == nil || ctx.Err() != nil {
		return nil, unavailable()
	}
	a, err := s.store.Load(ctx, scope, knowledgeID, attempt)
	if err != nil {
		var failure *Error
		switch {
		case errors.Is(err, ErrNotFound):
			return nil, &Error{Code: ErrorSourceNotFound, Detail: "source revision was not found"}
		case errors.Is(err, ErrNotCaptured):
			failure := &Error{Code: ErrorNotCaptured, Detail: "parse artifact was not captured"}
			var reason *NotCaptured
			if errors.As(err, &reason) {
				failure.Reason, failure.Page = reason.Reason, reason.Page
			}
			return nil, failure
		case errors.As(err, &failure) && failure.Code == ErrorInvalidRequest:
			return nil, &Error{Code: ErrorInvalidRequest, Detail: "source request authorization is invalid"}
		case errors.As(err, &failure) && failure.Code == ErrorIntegrity:
			return nil, integrity()
		default:
			return nil, unavailable()
		}
	}
	if ctx.Err() != nil || a == nil {
		return nil, unavailable()
	}
	if a.KnowledgeID != knowledgeID || a.ParseAttempt != attempt ||
		strings.TrimSpace(a.FileName) == "" || strings.ContainsAny(a.FileName, "/\\\x00") ||
		!validSHA256(a.FileSHA256) || !validSHA256(a.ParserIdentitySHA256) ||
		!utf8.ValidString(a.Markdown) || !utf8.Valid(a.NativeJSON) {
		return nil, integrity()
	}
	var native struct {
		Contract string       `json:"contract"`
		Pages    []nativePage `json:"pages"`
	}
	if json.Unmarshal(a.NativeJSON, &native) != nil {
		return nil, integrity()
	}
	if native.Contract == ooxml.Contract {
		return officePages(a)
	}
	if len(native.Pages) == 0 {
		return nil, integrity()
	}
	runes := []rune(a.Markdown)
	pages := make([]Page, 0, len(native.Pages))
	previousEnd := 0
	for i, p := range native.Pages {
		if p.Number != i+1 || p.Start == nil || p.End == nil ||
			*p.Start < previousEnd || *p.End < *p.Start || *p.End > len(runes) {
			return nil, integrity()
		}
		text := string(runes[*p.Start:*p.End])
		if digest([]byte(text)) != p.SHA256 {
			return nil, integrity()
		}
		pages = append(pages, Page{Number: p.Number, Text: text, TextSHA256: p.SHA256})
		previousEnd = *p.End
	}
	return &verified{
		set: &PageSet{
			KnowledgeID: a.KnowledgeID, ParseAttempt: a.ParseAttempt, Document: a.FileName,
			DocumentSHA256: a.FileSHA256, ParserIdentitySHA256: a.ParserIdentitySHA256,
			NativeSHA256: digest(a.NativeJSON), Pages: pages, RevisedAt: a.RevisedAt,
		},
		native: native.Pages,
	}, nil
}

// officePages reads an Office capture: the structure is decoded and fully verified, must belong to
// the captured file and parser identity, and its pages are returned verbatim with their blocks.
func officePages(a *Artifact) (*verified, error) {
	structure, err := ooxml.Decode(a.NativeJSON)
	if err != nil || structure.SourceSHA256 != a.FileSHA256 ||
		structure.ParserIdentitySHA256 != a.ParserIdentitySHA256 {
		return nil, integrity()
	}
	pages := make([]Page, len(structure.Pages))
	for i, p := range structure.Pages {
		pages[i] = Page{Number: p.Number, Text: p.Text, TextSHA256: p.TextSHA256}
		if len(p.Blocks) > 0 {
			pages[i].Blocks = p.Blocks
		}
	}
	return &verified{
		set: &PageSet{
			KnowledgeID: a.KnowledgeID, ParseAttempt: a.ParseAttempt, Document: a.FileName,
			DocumentSHA256: a.FileSHA256, ParserIdentitySHA256: a.ParserIdentitySHA256,
			NativeSHA256: digest(a.NativeJSON), Pages: pages, RevisedAt: a.RevisedAt,
		},
		office: true,
	}, nil
}

func digest(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func validSHA256(value string) bool {
	if len(value) != 2*sha256.Size || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func integrity() *Error {
	return &Error{Code: ErrorIntegrity, Detail: "parse artifact failed integrity verification"}
}

func unavailable() *Error {
	return &Error{Code: ErrorUnavailable, Detail: "source artifact is unavailable"}
}
