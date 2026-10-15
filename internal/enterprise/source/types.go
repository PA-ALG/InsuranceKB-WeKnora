// Package source reads captured parse artifacts without invoking a parser.
package source

import (
	"context"
	"errors"
)

const (
	ErrorInvalidRequest = "INVALID_REQUEST"
	ErrorSourceNotFound = "SOURCE_NOT_FOUND"
	ErrorNotCaptured    = "PARSE_ARTIFACT_NOT_CAPTURED"
	ErrorIntegrity      = "PARSE_ARTIFACT_INTEGRITY"
	ErrorUnavailable    = "SOURCE_UNAVAILABLE"
)

var (
	ErrNotFound    = errors.New("source not found")
	ErrNotCaptured = errors.New("parse artifact not captured")
)

// Scope is supplied by the authenticated platform boundary.
type Scope struct {
	TenantID uint64
	SpaceID  string
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

func (f ArtifactStoreFunc) Load(ctx context.Context, scope Scope, id string, attempt int64) (*Artifact, error) {
	return f(ctx, scope, id, attempt)
}

type Page struct {
	Number     int    `json:"page_number"`
	Text       string `json:"text"`
	TextSHA256 string `json:"page_text_sha256"`
}

type PageSet struct {
	KnowledgeID          string `json:"knowledge_id"`
	ParseAttempt         int64  `json:"parse_attempt"`
	Document             string `json:"document"`
	DocumentSHA256       string `json:"document_sha256"`
	ParserIdentitySHA256 string `json:"parser_identity_sha256"`
	NativeSHA256         string `json:"native_sha256"`
	Pages                []Page `json:"pages"`
}

// Error is safe to expose at the HTTP boundary; backend diagnostics stay private.
type Error struct{ Code, Detail string }

func (e *Error) Error() string { return e.Code + ": " + e.Detail }
