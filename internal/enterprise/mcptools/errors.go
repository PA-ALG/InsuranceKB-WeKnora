package mcptools

import (
	"context"
	"errors"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/mark3labs/mcp-go/mcp"
)

// Only known codes and fixed messages cross the MCP boundary. Dependency errors
// can contain connection strings, source paths, or private storage diagnostics.
func errorResult(err error) *mcp.CallToolResult {
	code := release.ErrorServiceUnavailable
	var rel *release.Error
	var src *source.Error
	switch {
	case errors.Is(err, context.Canceled):
		return mcp.NewToolResultError("REQUEST_CANCELLED: request cancelled")
	case errors.Is(err, context.DeadlineExceeded):
		return mcp.NewToolResultError("REQUEST_TIMEOUT: request deadline exceeded")
	case errors.As(err, &rel):
		code = rel.Code
	case errors.As(err, &src):
		code = src.Code
	}
	messages := map[string]string{
		release.ErrorInvalidRequest:       "invalid tool arguments",
		release.ErrorReleaseAccessDenied:  "published knowledge access denied",
		release.ErrorReleaseNotFound:      "published release not found",
		release.ErrorReleaseConflict:      "published release is inconsistent",
		release.ErrorMemberNotFound:       "published member not found",
		release.ErrorEvidenceNotFound:     "citation not found",
		release.ErrorEvidenceUnsupported:  "citation format is unsupported",
		release.ErrorEvidenceMismatch:     "citation does not match the captured source",
		release.ErrorEvidenceUnverifiable: "citation cannot be verified",
		release.ErrorServiceUnavailable:   "published knowledge is unavailable",
		source.ErrorSourceNotFound:        "citation source not found",
		source.ErrorUnavailable:           "citation source is unavailable",
		source.ErrorNotCaptured:           "citation source was not captured",
		source.ErrorIntegrity:             "citation source failed integrity verification",
		source.ErrorSpanOutOfRange:        "citation is outside the captured source",
		"ENTITY_NOT_FOUND":                "entity not found in the published release",
		"CONCEPT_NOT_FOUND":               "concept not found in the published release",
	}
	message, ok := messages[code]
	if !ok {
		code, message = release.ErrorServiceUnavailable, messages[release.ErrorServiceUnavailable]
	}
	return mcp.NewToolResultError(code + ": " + message)
}
