package source

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"unicode/utf8"
)

// Service verifies and reads the pages of captured source revisions.
type Service struct{ store ArtifactStore }

// NewService constructs a read-only page service backed by store.
func NewService(store ArtifactStore) *Service { return &Service{store: store} }

// Pages verifies every page before returning any text. Offsets are Unicode code
// points; no whitespace or line-ending normalization is applied.
func (s *Service) Pages(ctx context.Context, scope Scope, knowledgeID string, attempt int64) (*PageSet, error) {
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
			return nil, &Error{Code: ErrorNotCaptured, Detail: "parse artifact was not captured"}
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
		Pages []struct {
			Number int    `json:"page_number"`
			Start  *int   `json:"global_codepoint_start"`
			End    *int   `json:"global_codepoint_end"`
			SHA256 string `json:"page_text_sha256"`
		} `json:"pages"`
	}
	if json.Unmarshal(a.NativeJSON, &native) != nil || len(native.Pages) == 0 {
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
	return &PageSet{
		KnowledgeID: a.KnowledgeID, ParseAttempt: a.ParseAttempt, Document: a.FileName,
		DocumentSHA256: a.FileSHA256, ParserIdentitySHA256: a.ParserIdentitySHA256,
		NativeSHA256: digest(a.NativeJSON), Pages: pages,
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
