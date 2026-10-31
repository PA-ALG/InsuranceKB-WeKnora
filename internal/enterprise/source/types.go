// Package source reads captured parse artifacts without invoking a parser.
package source

import (
	"context"
	"errors"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
)

const (
	// ErrorInvalidRequest identifies an invalid scope, knowledge ID, or attempt.
	ErrorInvalidRequest = "INVALID_REQUEST"
	// ErrorSourceNotFound identifies an absent or inaccessible source revision.
	ErrorSourceNotFound = "SOURCE_NOT_FOUND"
	// ErrorNotCaptured identifies a revision without a saved parse artifact.
	ErrorNotCaptured = "PARSE_ARTIFACT_NOT_CAPTURED"
	// ErrorIntegrity identifies an invalid or inconsistent parse artifact.
	ErrorIntegrity = "PARSE_ARTIFACT_INTEGRITY"
	// ErrorUnavailable identifies a storage or service availability failure.
	ErrorUnavailable = "SOURCE_UNAVAILABLE"
)

var (
	// ErrNotFound means the source revision is absent or outside the scope.
	ErrNotFound = errors.New("source not found")
	// ErrNotCaptured means the source revision has no saved parse artifact.
	ErrNotCaptured = errors.New("parse artifact not captured")
)

// Typed reasons a revision was not captured (S11f). Only the code and, for a scanned PDF, the first
// scanned page number are ever exposed; parser messages stay private.
const (
	// NotCapturedScannedPage means a PDF page has no usable text layer, so the whole file was not captured.
	NotCapturedScannedPage = "SCANNED_PAGE"
	// NotCapturedOfficeUnreadable means an Office file's structure could not be read or sealed.
	NotCapturedOfficeUnreadable = "OFFICE_STRUCTURE_UNREADABLE"
	// NotCapturedUnsupportedFormat means the file type is outside what is captured (PDF and OOXML).
	NotCapturedUnsupportedFormat = "UNSUPPORTED_FORMAT"
	// NotCapturedNotRecorded means a capturable type without a capture or a note for this attempt.
	NotCapturedNotRecorded = "CAPTURE_NOT_RECORDED"
)

// NotCaptured qualifies ErrNotCaptured with its typed reason; errors.Is(err, ErrNotCaptured) holds.
type NotCaptured struct {
	Reason string
	Page   int // the first scanned page, only with NotCapturedScannedPage
}

func (e *NotCaptured) Error() string { return ErrNotCaptured.Error() + ": " + e.Reason }

// Is makes a typed reason match ErrNotCaptured.
func (e *NotCaptured) Is(target error) bool { return target == ErrNotCaptured }

// Scope is supplied by the authenticated platform boundary.
type Scope struct {
	TenantID uint64
	SpaceID  string
}

// CaptureScope identifies configured enterprise RAW knowledge bases.
type CaptureScope interface {
	RawKB(tenantID uint64, knowledgeBaseID string) bool
}

// Artifact retains the exact captured text and sanitized native JSON bytes.
type Artifact struct {
	KnowledgeID          string
	ParseAttempt         int64
	FileName             string
	FileSHA256           string
	ParserIdentitySHA256 string
	Markdown             string
	NativeJSON           []byte
}

// ArtifactStore must enforce Scope before reading the requested immutable
// attempt. Missing capture must never trigger parsing or use another attempt.
type ArtifactStore interface {
	Load(ctx context.Context, scope Scope, knowledgeID string, attempt int64) (*Artifact, error)
}

// ArtifactStoreFunc adapts the platform's read-only capture seam.
type ArtifactStoreFunc func(context.Context, Scope, string, int64) (*Artifact, error)

// Load calls the adapted reader with the authenticated request scope.
func (f ArtifactStoreFunc) Load(ctx context.Context, scope Scope, id string, attempt int64) (*Artifact, error) {
	return f(ctx, scope, id, attempt)
}

// Page is the verbatim text and recorded digest of one physical page. Office pages also carry their
// located blocks (S11b); PDF pages never do, so their JSON is unchanged.
type Page struct {
	Number     int           `json:"page_number"`
	Text       string        `json:"text"`
	TextSHA256 string        `json:"page_text_sha256"`
	Blocks     []ooxml.Block `json:"blocks,omitempty"`
}

// PageSet identifies a source revision and its verified physical pages.
type PageSet struct {
	KnowledgeID          string `json:"knowledge_id"`
	ParseAttempt         int64  `json:"parse_attempt"`
	Document             string `json:"document"`
	DocumentSHA256       string `json:"document_sha256"`
	ParserIdentitySHA256 string `json:"parser_identity_sha256"`
	NativeSHA256         string `json:"native_sha256"`
	Pages                []Page `json:"pages"`
}

// Error is safe to expose at the HTTP boundary; backend diagnostics stay private. Reason and Page
// qualify ErrorNotCaptured only (S11f).
type Error struct {
	Code, Detail string
	Reason       string
	Page         int
}

func (e *Error) Error() string { return e.Code + ": " + e.Detail }
