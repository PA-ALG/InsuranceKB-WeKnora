package enterprise_test

// SK-3 acceptance (Spec docs/design/slices/SK-3-销售方法阅读与问答.md §4.2): the browser expert-edit
// route answers an edit of method knowledge with 409 and EXPERT_EDIT_METHOD_KNOWLEDGE, writing
// nothing. Protected file: written by Claude. Reuses the S9a expert world. RED until SK-3.

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

func methodMember(t *testing.T, kind, slug string, payload map[string]any, refs ...string) map[string]any {
	t.Helper()
	canonical, err := json.Marshal(payload)
	require.NoError(t, err)
	entry := map[string]any{
		"kind": kind, "logical_slug": slug, "payload": payload, "member_digest": digestOf(canonical),
		"access_scope": "space",
	}
	if len(refs) > 0 {
		entry["evidence_refs"] = refs
	}
	return entry
}

func TestAnExpertEditOfMethodKnowledgeIsAConflict(t *testing.T) {
	w := newExpertWorld(t)
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
		"base_release_id": w.first.ID, "base_epoch": w.first.Epoch,
		"members": []any{
			methodMember(t, "presentation_profile", "presentation/sales_method", map[string]any{
				"profile_id": "sales_method", "entity_types": []any{"sales_method"}, "knowledge_class": "method",
				"sections": []any{map[string]any{"section_key": "method", "display_name": "销售方法",
					"fields": []any{map[string]any{"field_key": "method_summary", "short_title": "方法摘要"}}}},
			}),
			methodMember(t, "entity", "entity/M", map[string]any{
				"entity_id": "M", "entity_type": "sales_method", "names": []any{"需求分析三步法"},
			}),
			methodMember(t, "claim", "M/method_summary", map[string]any{
				"claim_id": "M/method_summary", "logical_key": "M/method_summary", "subject_ref": "M",
				"predicate": "method_summary", "state": "present", "value": "90日", "origin": "SOURCE_SUPPORTED",
				"evidence": []any{map[string]any{
					"source_ref": expertSourceRef, "file_sha256": strings.Repeat("ab", 32),
					"quote": "90日", "access_scope": "space",
					"locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1, "start": 0, "end": 3},
				}},
			}, expertSourceRef),
		},
	})
	require.NoError(t, err)
	ctx, harness := context.Background(), release.Principal{TenantID: 7, Subject: "svc-harness"}
	c, err := w.releases.Receive(ctx, harness, "demo", raw)
	require.NoError(t, err)
	d, err := w.releases.Decide(ctx, harness, "demo", c.ID, release.DecisionInput{Outcome: "approve", Mode: "human"})
	require.NoError(t, err)
	w.first, err = w.releases.Activate(ctx, harness, "demo", c.ID, d.ID)
	require.NoError(t, err)
	var digest string
	for _, m := range w.first.Members {
		if m.LogicalSlug == "M/method_summary" {
			digest = m.MemberDigest
		}
	}

	resp := post(w.router(browser, types.TenantRoleAdmin, w.experts), expertEditsPath,
		w.body(t, map[string]any{"member_slug": "M/method_summary", "base_member_digest": digest}))
	require.Equal(t, http.StatusConflict, resp.Code, resp.Body.String())
	require.Equal(t, expert.ErrorMethodKnowledge, code(t, resp.Body.Bytes()))
	w.requireNothingWritten(t)
}
