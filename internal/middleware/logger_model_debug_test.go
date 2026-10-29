package middleware

import (
	"strings"
	"testing"
)

// R3-3: model-debug responses carry prompts and raw model output, so the
// access log omits them; ordinary responses keep field sanitization.
func TestR3_3ModelDebugResponseIsNeverWrittenToAccessLog(t *testing.T) {
	const body = "{\"success\":true,\"data\":{\"ok\":true,\"elapsed_ms\":12" +
		",\"request\":{\"input\":\"private prompt\"},\"raw_response\":{\"content\":\"private" +
		" model output\",\"reasoning_content\":\"private reasoning\"},\"error\":\"private" +
		" provider error\"}}"

	got := sanitizeResponseBodyForLog(
		"/api/v1/models/model-1/debug?trace=1",
		body,
	)

	if got != "[model debug response omitted]" {
		t.Fatalf("unexpected model-debug log body: %q", got)
	}
	for _, secret := range []string{
		"private prompt",
		"private model output",
		"private reasoning",
		"private provider error",
	} {
		if strings.Contains(got, secret) {
			t.Fatalf("model-debug access log leaked %q", secret)
		}
	}
}

func TestR3_3OrdinaryResponseKeepsExistingFieldSanitization(t *testing.T) {
	const body = `{"api_key":"secret","content":"ordinary response"}`

	got := sanitizeResponseBodyForLog("/api/v1/knowledge", body)

	const want = `{"api_key":"***","content":"ordinary response"}`
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}
