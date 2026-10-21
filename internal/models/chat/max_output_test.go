package chat

// S6a-5 acceptance: a chat built by NewChat reports the model's known output limit through every
// wrapper, so callers can size a completion budget (Spec docs/design/slices/S6a-5-思考调用输出预算.md
// §4). Protected file: written by Claude. RED until S6a-5: MaxOutputTokens does not exist yet.

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

func remoteChatForLimit(t *testing.T, provider, model string, extra map[string]string) Chat {
	t.Helper()
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	server := httptest.NewServer(http.NotFoundHandler())
	t.Cleanup(server.Close)
	c, err := NewChat(&ChatConfig{
		Source:      types.ModelSourceRemote,
		Provider:    provider,
		ModelName:   model,
		ModelID:     "model-under-test",
		BaseURL:     server.URL + "/v1",
		APIKey:      "test-key",
		ExtraConfig: extra,
	}, nil)
	if err != nil {
		t.Fatalf("NewChat: %v", err)
	}
	return c
}

// The live row keeps the legacy thinking_control=none; the limit comes from the catalog regardless.
func TestACatalogedRemoteChatReportsItsOutputLimitThroughTheWrappers(t *testing.T) {
	c := remoteChatForLimit(t, "deepseek", "deepseek-v4-flash", map[string]string{"thinking_control": "none"})
	if got := MaxOutputTokens(c); got < 65536 {
		t.Fatalf("deepseek-v4-flash must report its catalog output limit (384K) through NewChat's wrappers, got %d",
			got)
	}
}

func TestAnUncatalogedRemoteChatReportsNoOutputLimit(t *testing.T) {
	c := remoteChatForLimit(t, "generic", "acme-local-model", nil)
	if got := MaxOutputTokens(c); got != 0 {
		t.Fatalf("an uncataloged model has no known output limit, got %d", got)
	}
}
