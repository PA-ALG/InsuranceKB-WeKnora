// SK-3 acceptance: activation holds method claims to their item convention (Spec
// docs/design/slices/SK-3-销售方法阅读与问答.md §1, §4.1). Protected file: written by Claude.
//
// A method type is one a presentation profile with knowledge_class "method" serves, in the target
// release or the current Active one. A claim of the candidate whose subject is such an entity must
// give every list item as a non-blank string with exactly one evidence object at its position, and
// rest on source passages only (no EXPERT_REVISION evidence, no expert_lock). Anything else refuses
// the whole candidate; products and releases without a method profile are unaffected. Reuses the
// in-memory platform and helpers of this package. RED until SK-3 implements it.
package release_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

var expertRef = "expert:v1:rev-1:" + fileSHA

func methodPlatform(t *testing.T) (*platform, *release.Service) {
	t.Helper()
	p := newPlatform()
	allowed := map[string]bool{refOne: true, refTwo: true, expertRef: true}
	return p, release.NewService(p, fakeEvidence{allowed: allowed}, realSchemas(t),
		release.WithPublisher(p), release.WithEvidenceVerifier(&recordingVerifier{}))
}

func methodProfileMember(t *testing.T) map[string]any {
	t.Helper()
	return vm(t, "presentation_profile", "presentation/sales_method", map[string]any{
		"profile_id": "sales_method", "entity_types": []any{"sales_method"}, "knowledge_class": "method",
		"sections": []any{map[string]any{
			"section_key": "method", "display_name": "销售方法",
			"fields": []any{map[string]any{"field_key": "method_steps", "short_title": "步骤"}},
		}},
	})
}

func methodEntityMember(t *testing.T, id string) map[string]any {
	t.Helper()
	return vm(t, "entity", "entity/"+id, entityPayload(id, "sales_method", nil))
}

// listMember is a present claim of subject/field with the given value and evidence.
func listMember(
	t *testing.T, subject, field string, value any, extra map[string]any, evidence ...map[string]any,
) map[string]any {
	t.Helper()
	items := make([]any, 0, len(evidence))
	refs := map[string]bool{}
	for _, e := range evidence {
		items = append(items, e)
		refs[e["source_ref"].(string)] = true
	}
	payload := claimPayload(subject, field, nil, map[string]any{
		"state": "present", "value": value, "evidence": items, "unknown_reason": nil,
	})
	for k, v := range extra {
		payload[k] = v
	}
	sorted := []string{}
	for _, ref := range []string{expertRef, refOne, refTwo} {
		if refs[ref] {
			sorted = append(sorted, ref)
		}
	}
	return vm(t, "claim", subject+"/"+field, payload, sorted...)
}

func expertEvidence() map[string]any {
	return map[string]any{
		"source_ref": expertRef, "file_sha256": fileSHA, "quote": "改后", "access_scope": "space",
		"locator": map[string]any{"kind": "EXPERT_REVISION", "revision_record_id": "rev-1"},
	}
}

// activation receives, approves and activates one bundle, returning the activation's error.
func activation(t *testing.T, s *release.Service, raw []byte) (release.Release, error) {
	t.Helper()
	ctx := context.Background()
	c, err := s.Receive(ctx, principal(), spaceID, raw)
	require.NoError(t, err, "the item convention is checked at activation, against the target release")
	d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
	require.NoError(t, err)
	return s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
}

func requireInvalid(t *testing.T, err error, slug string) {
	t.Helper()
	var failure *release.Error
	require.True(t, errors.As(err, &failure), "want *release.Error, got %v", err)
	require.Equal(t, release.ErrorCandidateInvalid, failure.Code)
	require.Contains(t, failure.Detail, slug)
}

func TestAnAlignedMethodListActivates(t *testing.T) {
	p, s := methodPlatform(t)
	r, err := activation(t, s, vbundle(t, "compile", nil, nil,
		methodProfileMember(t), methodEntityMember(t, "sm-1"),
		listMember(t, "sm-1", "method_steps", []any{"问家庭", "讲保障"}, nil,
			evidenceObject(refOne, 3, 0, 3, "问家庭"), evidenceObject(refTwo, 4, 0, 3, "讲保障"))))
	require.NoError(t, err)
	require.Equal(t, uint64(1), r.Epoch)
	require.Equal(t, r.ID, p.head.ReleaseID)
}

func TestMethodListsMustCiteEachItemAtItsPosition(t *testing.T) {
	for name, claim := range map[string]func(*testing.T) map[string]any{
		"fewer evidence than items": func(t *testing.T) map[string]any {
			return listMember(t, "sm-1", "method_steps", []any{"问家庭", "讲保障"}, nil,
				evidenceObject(refOne, 3, 0, 3, "问家庭"))
		},
		"more evidence than items": func(t *testing.T) map[string]any {
			return listMember(t, "sm-1", "method_steps", []any{"问家庭"}, nil,
				evidenceObject(refOne, 3, 0, 3, "问家庭"), evidenceObject(refTwo, 4, 0, 3, "讲保障"))
		},
		"an item that is not a string": func(t *testing.T) map[string]any {
			return listMember(t, "sm-1", "method_steps", []any{"问家庭", 2}, nil,
				evidenceObject(refOne, 3, 0, 3, "问家庭"), evidenceObject(refTwo, 4, 0, 3, "讲保障"))
		},
		"a blank item": func(t *testing.T) map[string]any {
			return listMember(t, "sm-1", "method_steps", []any{"问家庭", "  "}, nil,
				evidenceObject(refOne, 3, 0, 3, "问家庭"), evidenceObject(refTwo, 4, 0, 3, "讲保障"))
		},
		"expert revision evidence": func(t *testing.T) map[string]any {
			return listMember(t, "sm-1", "method_summary", "改后", nil, expertEvidence())
		},
		"an expert lock": func(t *testing.T) map[string]any {
			return listMember(t, "sm-1", "method_summary", "先问需求", map[string]any{"expert_lock": true},
				evidenceObject(refOne, 2, 0, 4, "先问需求"))
		},
	} {
		t.Run(name, func(t *testing.T) {
			p, s := methodPlatform(t)
			member := claim(t)
			_, err := activation(t, s, vbundle(t, "compile", nil, nil,
				methodProfileMember(t), methodEntityMember(t, "sm-1"), member))
			requireInvalid(t, err, member["logical_slug"].(string))
			require.Empty(t, p.head.ReleaseID, "nothing is activated")
		})
	}
}

func TestAMethodProfileInTheActiveReleaseStillHoldsLaterClaims(t *testing.T) {
	_, s := methodPlatform(t)
	base, err := activation(t, s, vbundle(t, "compile", nil, nil,
		methodProfileMember(t), methodEntityMember(t, "sm-1")))
	require.NoError(t, err)
	_, err = activation(t, s, vbundle(t, "compile", &base, nil,
		listMember(t, "sm-1", "method_steps", []any{"问家庭", "讲保障"}, nil, evidenceObject(refOne, 3, 0, 3, "问家庭"))))
	requireInvalid(t, err, "sm-1/method_steps")

	// A candidate that drops the method profile is still held to the Active one's rule.
	_, err = activation(t, s, vbundle(t, "compile", &base, []string{"presentation/sales_method"},
		listMember(t, "sm-1", "method_steps", []any{"问家庭", "讲保障"}, nil, evidenceObject(refOne, 3, 0, 3, "问家庭"))))
	requireInvalid(t, err, "sm-1/method_steps")
}

func TestClaimsOutsideMethodTypesAreNotHeldToTheItemConvention(t *testing.T) {
	_, s := methodPlatform(t)
	_, err := activation(t, s, vbundle(t, "compile", nil, nil,
		methodProfileMember(t),
		vm(t, "entity", "entity/P1", entityPayload("P1", "product", nil)),
		listMember(t, "P1", "exclusions", []any{"一", "二"}, nil, evidenceObject(refOne, 3, 0, 1, "一"))))
	require.NoError(t, err, "a product's list keeps its own evidence")

	_, s = methodPlatform(t)
	_, err = activation(t, s, vbundle(t, "compile", nil, nil,
		methodEntityMember(t, "sm-1"),
		listMember(t, "sm-1", "method_steps", []any{"问家庭", "讲保障"}, nil, evidenceObject(refOne, 3, 0, 3, "问家庭"))))
	require.NoError(t, err, "without a method profile the type is not method knowledge")
}
