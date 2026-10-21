package chat

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/api"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type capacityChat struct {
	*fakeChat
	capacity int
}

func (c *capacityChat) MaxOutputTokens() int { return c.capacity }

func TestOutputCapacitySurvivesEachDecoratorAndComposition(t *testing.T) {
	for _, tc := range []struct {
		name string
		chat Chat
		want int
	}{
		{"nil", nil, 0},
		{"unsupported", &fakeChat{}, 0},
		{"unknown", &capacityChat{fakeChat: &fakeChat{}}, 0},
		{"known", &capacityChat{fakeChat: &fakeChat{}, capacity: 65536}, 65536},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for name, decorated := range map[string]Chat{
				"bare":        tc.chat,
				"debug":       &debugChat{inner: tc.chat},
				"langfuse":    &langfuseChat{inner: tc.chat},
				"concurrency": &concurrencyChat{inner: tc.chat},
				"all":         &concurrencyChat{inner: &langfuseChat{inner: &debugChat{inner: tc.chat}}},
			} {
				t.Run(name, func(t *testing.T) { require.Equal(t, tc.want, MaxOutputTokens(decorated)) })
			}
		})
	}
}

func TestOutputCapacityUsesResolvedOverrideForEveryRemoteProtocol(t *testing.T) {
	t.Setenv("SSRF_WHITELIST", "127.0.0.1")
	server := httptest.NewServer(http.NotFoundHandler())
	defer server.Close()
	for _, protocol := range []api.API{
		api.APIOpenAICompletions, api.APIOpenAIResponses, api.APIAnthropicMessages, api.APIGoogleGenerativeAI,
	} {
		t.Run(string(protocol), func(t *testing.T) {
			config := &ChatConfig{
				Source: types.ModelSourceRemote, Provider: "generic", ModelName: "uncataloged-model",
				ModelID: "capacity-test", APIKey: "test-key", BaseURL: server.URL,
				Spec: &types.ModelSpecOverride{API: string(protocol), MaxOutputTokens: 72000},
			}
			model, err := NewChat(config, nil)
			require.NoError(t, err)
			require.Equal(t, 72000, MaxOutputTokens(model))
			require.Equal(t, config.ModelName, model.GetModelName())
			require.Equal(t, config.ModelID, model.GetModelID())
			remote, err := NewRemoteChat(config)
			require.NoError(t, err)
			builder, ok := remote.(interface {
				BuildRequestBody([]api.Message, *api.Options, bool) (map[string]any, error)
			})
			require.True(t, ok, "remote metadata must preserve the existing request inspection interface")
			for _, stream := range []bool{false, true} {
				body, err := builder.BuildRequestBody([]api.Message{{Role: "user", Content: "test"}},
					&api.Options{MaxTokens: 65536}, stream)
				require.NoError(t, err)
				require.NotEmpty(t, body)
			}
		})
	}
}
