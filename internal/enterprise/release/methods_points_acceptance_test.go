// SK-3 acceptance r3 (#523 R1, R2): every publishing path holds method claims to their rule (Spec
// docs/design/slices/SK-3-销售方法阅读与问答.md §4.1). Protected file: written by Claude.
//
// The production store is also a QueueStore and a PointStore, so a candidate is published either
// as a whole (Decide → Activate) or point by point (ReviewCandidate → ReviewPoints). Both refuse,
// before any decision or Head is written, a method claim that is present without resting item by
// item on source passages: list items and evidence differ, an expert lock or expert evidence, a
// model-written value without evidence, an empty list, an origin other than SOURCE_SUPPORTED. The
// candidate's detail and the claim's point name the refusal. A valid method list, an unknown
// method claim, a model-written claim of a product and a product claim publish as before.
package release_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func methodPointService(t *testing.T, p *pointPlatform) *release.Service {
	t.Helper()
	allowed := map[string]bool{refOne: true, refTwo: true, expertRef: true}
	return release.NewService(p, fakeEvidence{allowed: allowed}, realSchemas(t),
		release.WithPublisher(p), release.WithEvidenceVerifier(&recordingVerifier{}))
}

func modelClaim(t *testing.T, subject, field string, value any) map[string]any {
	t.Helper()
	return listMember(t, subject, field, value, map[string]any{"origin": "MODEL_GENERATED"})
}

// methodCandidate is a candidate with the method profile, a new method entity and one claim.
func methodCandidate(t *testing.T, claim map[string]any) []byte {
	t.Helper()
	return vbundle(t, "compile", nil, nil, methodProfileMember(t), methodEntityMember(t, "sm-1"), claim)
}

var refusedMethodClaims = map[string]func(*testing.T) map[string]any{
	"a list with fewer evidence than items": func(t *testing.T) map[string]any {
		return listMember(t, "sm-1", "method_steps", []any{"问家庭", "讲保障"}, nil,
			evidenceObject(refOne, 3, 0, 3, "问家庭"))
	},
	"an expert lock": func(t *testing.T) map[string]any {
		return listMember(t, "sm-1", "method_summary", "先问需求", map[string]any{"expert_lock": true},
			evidenceObject(refOne, 2, 0, 4, "先问需求"))
	},
	"expert revision evidence": func(t *testing.T) map[string]any {
		return listMember(t, "sm-1", "method_summary", "改后", nil, expertEvidence())
	},
	"model-written text without evidence": func(t *testing.T) map[string]any {
		return modelClaim(t, "sm-1", "method_summary", "模型补写的方法摘要")
	},
	"a model-written empty list": func(t *testing.T) map[string]any {
		return modelClaim(t, "sm-1", "method_steps", []any{})
	},
	"a mixed origin with evidence": func(t *testing.T) map[string]any {
		return listMember(t, "sm-1", "method_summary", "先问需求", map[string]any{"origin": "MIXED"},
			evidenceObject(refOne, 2, 0, 4, "先问需求"))
	},
}

func TestAMethodClaimWithoutItsSourcesIsRefusedAsAWhole(t *testing.T) {
	for name, claim := range refusedMethodClaims {
		t.Run(name, func(t *testing.T) {
			ctx := context.Background()
			p := newPointPlatform()
			s := methodPointService(t, p)
			member := claim(t)
			slug := member["logical_slug"].(string)
			c, err := s.Receive(ctx, principal(), spaceID, methodCandidate(t, member))
			require.NoError(t, err, "the method rule is checked where the target release is known")

			detail, err := s.ReviewCandidate(ctx, principal(), spaceID, c.ID)
			require.NoError(t, err)
			require.Equal(t, release.ErrorCandidateInvalid, detail.Blocker, "the detail names the refusal")

			// The browser's whole review refuses before it writes a decision.
			_, err = s.Review(ctx, principal(), spaceID, c.ID, "approve", "looks fine")
			requireInvalid(t, err, slug)
			require.Empty(t, p.decisions, "no decision is written")

			// The machine path records its decision; activation refuses before any Head is written.
			d, err := s.Decide(ctx, principal(), spaceID, c.ID, approve)
			require.NoError(t, err)
			_, err = s.Activate(ctx, principal(), spaceID, c.ID, d.ID)
			requireInvalid(t, err, slug)
			require.Empty(t, p.head.ReleaseID, "no Head is written")
		})
	}
}

func TestAMethodClaimWithoutItsSourcesIsRefusedPointByPoint(t *testing.T) {
	for name, claim := range refusedMethodClaims {
		t.Run(name, func(t *testing.T) {
			ctx := context.Background()
			p := newPointPlatform()
			s := methodPointService(t, p)
			member := claim(t)
			slug := member["logical_slug"].(string)
			c, err := s.Receive(ctx, principal(), spaceID, methodCandidate(t, member))
			require.NoError(t, err)

			detail, err := s.ReviewCandidate(ctx, principal(), spaceID, c.ID)
			require.NoError(t, err)
			blockers := map[string]string{}
			for _, point := range detail.Points {
				blockers[point.Slug] = point.Blocker
			}
			require.Equal(t, release.ErrorCandidateInvalid, blockers[slug], "the claim's point names the refusal")

			_, err = s.ReviewPoints(ctx, principal(), spaceID, c.ID, []string{slug}, "approve", "looks fine")
			requireInvalid(t, err, slug)
			require.Empty(t, p.points, "no point decision is written")
			require.Empty(t, p.head.ReleaseID, "no Head is written")
		})
	}
}

func TestValidMethodsAndOtherClaimsPublishOnBothPaths(t *testing.T) {
	accepted := map[string][]map[string]any{
		"an aligned method list": {
			methodProfileMember(t), methodEntityMember(t, "sm-1"),
			listMember(t, "sm-1", "method_steps", []any{"问家庭", "讲保障"}, nil,
				evidenceObject(refOne, 3, 0, 3, "问家庭"), evidenceObject(refTwo, 4, 0, 3, "讲保障")),
		},
		"an unknown method claim": {
			methodProfileMember(t), methodEntityMember(t, "sm-1"),
			vm(t, "claim", "sm-1/key_phrases", claimPayload("sm-1", "key_phrases", nil, nil)),
		},
		"a model-written product claim": {
			methodProfileMember(t), vm(t, "entity", "entity/P1", entityPayload("P1", "product", nil)),
			modelClaim(t, "P1", "summary", "模型补充的概念说明"),
		},
		"a product claim": {
			methodProfileMember(t), vm(t, "entity", "entity/P1", entityPayload("P1", "product", nil)),
			listMember(t, "P1", "waiting_period", "90日", nil, evidenceObject(refOne, 1, 0, 3, "90日")),
		},
	}
	for name, members := range accepted {
		t.Run(name+" as a whole", func(t *testing.T) {
			p := newPointPlatform()
			_, err := activation(t, methodPointService(t, p), vbundle(t, "compile", nil, nil, members...))
			require.NoError(t, err)
			require.NotEmpty(t, p.head.ReleaseID)
		})
		t.Run(name+" point by point", func(t *testing.T) {
			ctx := context.Background()
			p := newPointPlatform()
			s := methodPointService(t, p)
			c, err := s.Receive(ctx, principal(), spaceID, vbundle(t, "compile", nil, nil, members...))
			require.NoError(t, err)
			detail, err := s.ReviewCandidate(ctx, principal(), spaceID, c.ID)
			require.NoError(t, err)
			require.Empty(t, detail.Blocker)
			slug := members[len(members)-1]["logical_slug"].(string)
			_, err = s.ReviewPoints(ctx, principal(), spaceID, c.ID, []string{slug}, "approve", "looks fine")
			require.NoError(t, err)
			require.NotEmpty(t, p.head.ReleaseID)
		})
	}
}
