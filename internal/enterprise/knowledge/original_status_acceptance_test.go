// PV-5c acceptance (Codex, #535): names and unknown state already work without a code.
// Keep the existing product/identity boundary; the fix belongs at the original/rewrite input.
package knowledge_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

type originalStatusReader struct{}

func (originalStatusReader) ReleaseByID(
	ctx context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	value, err := (statusReader{statusIntents}).ReleaseByID(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return value, err
	}
	for i := range value.Members {
		m := &value.Members[i]
		if m.LogicalSlug != "entity/U" {
			continue
		}
		var payload map[string]any
		if err := json.Unmarshal(m.Payload, &payload); err != nil {
			return release.Release{}, err
		}
		payload["identifiers"] = map[string]string{"arbitrary_registered_key": "R710"}
		m.Payload, err = json.Marshal(payload)
	}
	return value, err
}

func TestOriginalNamedSalesQuestionStillProjectsUnknownWithoutVersionData(t *testing.T) {
	svc := knowledge.NewService(originalStatusReader{})
	lines, fields, err := svc.QuestionReferences(
		context.Background(), tenant, space, pinned, "戊医疗保险能买吗", 12,
	)
	require.NoError(t, err)
	require.Len(t, lines, 1)
	require.Equal(t, "U", lines[0].EntityID)
	require.Equal(t, "戊医疗保险 · 销售状态：未知", lines[0].Text)
	require.NotEmpty(t, fields)
}

func TestOriginalSalesNamingKeepsWholeRegisteredTokenAndIntentBoundaries(t *testing.T) {
	svc := knowledge.NewService(originalStatusReader{})
	questions := []string{
		"R7100能买吗", "R710-0001能买吗", "无产品的推荐", "R710理赔", "R710能买且理赔吗",
	}
	for _, question := range questions {
		lines, err := svc.QuestionStatuses(context.Background(), tenant, space, pinned, question)
		require.NoError(t, err)
		require.Empty(t, lines, "an original input cannot relax existing recognition or intent")
	}
	lines, err := svc.QuestionStatuses(context.Background(), tenant, space, pinned, "产品代码 R710 能买吗")
	require.NoError(t, err)
	require.Len(t, lines, 1)
	require.Equal(t, "U", lines[0].EntityID)
}
