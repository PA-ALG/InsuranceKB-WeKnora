// SK-3 acceptance: experts cannot edit method knowledge (Spec docs/design/slices/SK-3-销售方法阅读与问答.md
// §4.2; SK-0 §3.4). Protected file: written by Claude.
//
// A claim whose subject the Active release's method profile serves is refused with
// EXPERT_EDIT_METHOD_KNOWLEDGE before anything is recorded or published; a product claim of the same
// release stays editable. Reuses the S9a fixture. RED until SK-3 implements it.
package expert_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func kindMember(t *testing.T, kind, slug string, payload map[string]any) map[string]any {
	t.Helper()
	return map[string]any{
		"kind": kind, "logical_slug": slug, "payload": payload, "member_digest": digestOf(t, payload),
		"access_scope": "space",
	}
}

// withMethod publishes, on the fixture's first release, a method profile, a method entity M and
// its claim M/method_summary.
func withMethod(t *testing.T, f fixture) release.Release {
	t.Helper()
	summary := claimMember(t, "M/method_summary", "先问需求")
	summary["payload"].(map[string]any)["subject_ref"] = "M"
	summary["member_digest"] = digestOf(t, summary["payload"])
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
		"base_release_id": f.first.ID, "base_epoch": f.first.Epoch,
		"members": []any{
			kindMember(t, "presentation_profile", "presentation/sales_method", map[string]any{
				"profile_id": "sales_method", "entity_types": []any{"sales_method"}, "knowledge_class": "method",
				"sections": []any{map[string]any{
					"section_key": "method", "display_name": "销售方法",
					"fields": []any{map[string]any{"field_key": "method_summary", "short_title": "方法摘要"}},
				}},
			}),
			kindMember(t, "entity", "entity/M", map[string]any{
				"entity_id": "M", "entity_type": "sales_method", "names": []any{"需求分析三步法"},
				"classification_labels": []any{"medical"},
			}),
			summary,
		},
	})
	require.NoError(t, err)
	ctx := context.Background()
	c, err := f.releases.Receive(ctx, harness, spaceID, raw)
	require.NoError(t, err)
	d, err := f.releases.Decide(ctx, harness, spaceID, c.ID, approve)
	require.NoError(t, err)
	second, err := f.releases.Activate(ctx, harness, spaceID, c.ID, d.ID)
	require.NoError(t, err)
	return second
}

func TestAnExpertEditOfAMethodClaimIsRefusedAndWritesNothing(t *testing.T) {
	f := setup(t)
	second := withMethod(t, f)
	_, err := f.editor.Edit(context.Background(), admin, "admin", spaceID, expert.EditInput{
		BaseReleaseID: second.ID, MemberSlug: "M/method_summary",
		BaseMemberDigest: memberOf(second, "M/method_summary").MemberDigest,
		State:            "present", Value: "先讲产品", Reason: "改写",
	})
	require.Equal(t, expert.ErrorMethodKnowledge, codeOf(t, err))
	require.Equal(t, "EXPERT_EDIT_METHOD_KNOWLEDGE", expert.ErrorMethodKnowledge)
	require.Empty(t, f.revisions.rows, "no revision record")
	require.Equal(t, 2, f.platform.activations, "no release")

	result, err := f.editor.Edit(context.Background(), admin, "admin", spaceID, expert.EditInput{
		BaseReleaseID: second.ID, MemberSlug: "P/waiting",
		BaseMemberDigest: memberOf(second, "P/waiting").MemberDigest,
		State:            "present", Value: "180日", Reason: "备案条款",
	})
	require.NoError(t, err, "a product claim of the same release stays editable")
	require.Equal(t, uint64(3), result.Release.Epoch)
}
