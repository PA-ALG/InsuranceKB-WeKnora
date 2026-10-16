// S4c-2b-2 acceptance: evidence inside member payloads is verified at submission, members
// that claim a source must carry evidence, and model-generated members may go without but
// keep their origin (Spec docs/design/slices/S4c-2b-2-证据回验与回跳.md §3.1, §3.4).
// Protected file: written by Claude.
//
// Reuses the S4c-2a in-memory platform and the S3b helpers of this package. RED until
// S4c-2b-2 implements it.
package release_test

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

var (
	fileSHA = strings.Repeat("ab", 32)
	refOne  = "source:v1:k-1:1:" + fileSHA
	refTwo  = "source:v1:k-2:3:" + fileSHA
)

type recordingVerifier struct {
	calls [][]release.EvidenceCheck
	fail  error
}

func (v *recordingVerifier) VerifyEvidence(_ context.Context, checks []release.EvidenceCheck) error {
	v.calls = append(v.calls, checks)
	return v.fail
}

func evidenceSchemas(t *testing.T) map[string][]byte {
	t.Helper()
	raw, err := os.ReadFile("../../../contracts/evidence.schema.json")
	require.NoError(t, err)
	out := schemas()
	out["evidence"] = raw
	return out
}

func evidenceObject(ref string, page, start, end int, quote string) map[string]any {
	return map[string]any{
		"source_ref": ref, "file_sha256": ref[len(ref)-64:], "quote": quote, "access_scope": "space",
		"locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": page, "start": start, "end": end},
	}
}

func claim(origin, state string, evidence ...map[string]any) map[string]any {
	payload := map[string]any{"origin": origin, "state": state, "value": "90日"}
	if evidence != nil {
		items := make([]any, 0, len(evidence))
		for _, e := range evidence {
			items = append(items, e)
		}
		payload["evidence"] = items
	}
	return payload
}

func verifying(p *platform, v release.EvidenceVerifier, schemaSet map[string][]byte) *release.Service {
	options := []release.Option{release.WithPublisher(p)}
	if v != nil {
		options = append(options, release.WithEvidenceVerifier(v))
	}
	return release.NewService(p, fakeEvidence{allowed: map[string]bool{refOne: true, refTwo: true}},
		schemaSet, options...)
}

func receive(t *testing.T, s *release.Service, members ...map[string]any) error {
	t.Helper()
	_, err := s.Receive(context.Background(), principal(), spaceID, candidateBundle(t, "", nil, members...))
	return err
}

func TestEveryEvidenceObjectIsVerifiedInOneCallWithItsPointer(t *testing.T) {
	v := &recordingVerifier{}
	s := verifying(newPlatform(), v, evidenceSchemas(t))

	require.NoError(t, receive(t, s,
		member(t, "1828/waiting_period", claim("SOURCE_SUPPORTED", "present",
			evidenceObject(refOne, 5, 120, 168, "等待期为90日"),
			evidenceObject(refTwo, 2, 0, 4, "等待期间")), refOne, refTwo),
		member(t, "1828/grace_period", claim("SOURCE_SUPPORTED", "present",
			evidenceObject(refOne, 7, 10, 20, "宽限期60日")), refOne)))

	require.Len(t, v.calls, 1, "one call lets the verifier read each source once")
	checks := v.calls[0]
	paths := make([]string, 0, len(checks))
	for _, c := range checks {
		paths = append(paths, c.Path)
	}
	require.Equal(t, []string{
		"/members/0/payload/evidence/0", "/members/0/payload/evidence/1", "/members/1/payload/evidence/0",
	}, paths)
	first := checks[0].Evidence
	require.Equal(t, refOne, first.SourceRef)
	require.Equal(t, fileSHA, first.FileSHA256)
	require.Equal(t, "PDF_TEXT_SPAN", first.Locator.Kind)
	require.Equal(t, 5, *first.Locator.Page)
	require.Equal(t, 120, *first.Locator.Start)
	require.Equal(t, 168, *first.Locator.End)
	require.Equal(t, "等待期为90日", first.Quote)
}

func TestVerifierRefusalsRejectTheWholeBundleWithTheirCode(t *testing.T) {
	codes := []string{release.ErrorEvidenceMismatch, release.ErrorEvidenceUnsupported, release.ErrorEvidenceUnverifiable}
	for _, code := range codes {
		p := newPlatform()
		v := &recordingVerifier{fail: &release.Error{Code: code, Detail: "/members/0/payload/evidence/0: quote"}}
		err := receive(t, verifying(p, v, evidenceSchemas(t)),
			member(t, "a", claim("SOURCE_SUPPORTED", "present", evidenceObject(refOne, 1, 0, 2, "等待")), refOne))
		require.Equal(t, code, codeOf(t, err))
		require.Empty(t, p.candidates, "a refused bundle is not stored")
	}

	p := newPlatform()
	v := &recordingVerifier{fail: errors.New("artifact storage unavailable")}
	err := receive(t, verifying(p, v, evidenceSchemas(t)),
		member(t, "a", claim("SOURCE_SUPPORTED", "present", evidenceObject(refOne, 1, 0, 2, "等待")), refOne))
	require.Error(t, err)
	require.Empty(t, p.candidates)
}

func TestMalformedEvidenceIsACandidateErrorBeforeVerification(t *testing.T) {
	missingQuote := evidenceObject(refOne, 1, 0, 2, "等待")
	delete(missingQuote, "quote")
	extraField := evidenceObject(refOne, 1, 0, 2, "等待")
	extraField["note"] = "not in the contract"
	notAnArray := claim("SOURCE_SUPPORTED", "present")
	notAnArray["evidence"] = evidenceObject(refOne, 1, 0, 2, "等待")

	for name, payload := range map[string]map[string]any{
		"evidence is not an array":       notAnArray,
		"evidence misses a quote":        claim("SOURCE_SUPPORTED", "present", missingQuote),
		"evidence has an unknown field":  claim("SOURCE_SUPPORTED", "present", extraField),
		"evidence element is not object": {"origin": "SOURCE_SUPPORTED", "state": "present", "evidence": []any{"x"}},
	} {
		t.Run(name, func(t *testing.T) {
			v := &recordingVerifier{}
			err := receive(t, verifying(newPlatform(), v, evidenceSchemas(t)), member(t, "a", payload, refOne))
			require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
			require.Empty(t, v.calls)
		})
	}
}

func TestEvidenceSourcesMustEqualTheMemberEvidenceRefs(t *testing.T) {
	for name, refs := range map[string][]string{
		"evidence cites an unlisted source": {refTwo},
		"a listed source has no evidence":   {refOne, refTwo},
	} {
		t.Run(name, func(t *testing.T) {
			v := &recordingVerifier{}
			err := receive(t, verifying(newPlatform(), v, evidenceSchemas(t)),
				member(t, "a", claim("SOURCE_SUPPORTED", "present", evidenceObject(refOne, 1, 0, 2, "等待")), refs...))
			require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
			require.Empty(t, v.calls)
		})
	}
}

func TestSourceClaimsNeedEvidenceButModelGeneratedOnesDoNot(t *testing.T) {
	refused := map[string]map[string]any{
		"source-supported without evidence":     claim("SOURCE_SUPPORTED", "present"),
		"source-supported with empty evidence":  claim("SOURCE_SUPPORTED", "present", []map[string]any{}...),
		"absent without the clause it rests on": claim("SOURCE_SUPPORTED", "absent_explicitly"),
		"mixed without evidence":                claim("MIXED", "present"),
		"expert revision without evidence":      claim("EXPERT_REVISION", "present"),
	}
	for name, payload := range refused {
		t.Run(name, func(t *testing.T) {
			v := &recordingVerifier{}
			err := receive(t, verifying(newPlatform(), v, evidenceSchemas(t)), member(t, "a", payload))
			require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
		})
	}

	accepted := map[string]map[string]any{
		"model-generated concept":          claim("MODEL_GENERATED", "present"),
		"unknown field of a sourced claim": claim("SOURCE_SUPPORTED", "unknown", []map[string]any{}...),
		"payload without an origin":        {"value": "一年"},
	}
	for name, payload := range accepted {
		t.Run(name, func(t *testing.T) {
			v := &recordingVerifier{}
			require.NoError(t, receive(t, verifying(newPlatform(), v, evidenceSchemas(t)), member(t, "a", payload)))
			require.Empty(t, v.calls, "nothing to verify")
		})
	}

	v := &recordingVerifier{}
	require.NoError(t, receive(t, verifying(newPlatform(), v, evidenceSchemas(t)),
		member(t, "a", claim("MODEL_GENERATED", "present", evidenceObject(refOne, 1, 0, 2, "等待")), refOne)))
	require.Len(t, v.calls, 1, "evidence a model-generated member does cite is verified too")
}

func TestEvidenceFailsClosedWithoutAVerifierOrItsContract(t *testing.T) {
	withEvidence := member(t, "a", claim("SOURCE_SUPPORTED", "present", evidenceObject(refOne, 1, 0, 2, "等待")), refOne)

	err := receive(t, verifying(newPlatform(), nil, evidenceSchemas(t)), withEvidence)
	require.Equal(t, release.ErrorEvidenceUnverifiable, codeOf(t, err))

	v := &recordingVerifier{}
	err = receive(t, verifying(newPlatform(), v, schemas()), withEvidence)
	require.Equal(t, release.ErrorEvidenceUnverifiable, codeOf(t, err))
	require.Empty(t, v.calls)

	require.NoError(t, receive(t, verifying(newPlatform(), nil, schemas()),
		member(t, "b", claim("MODEL_GENERATED", "present"))), "members without evidence need no verifier")
}

func TestEvidenceAtOpensOneEvidenceOfAnExplicitRelease(t *testing.T) {
	p := newPlatform()
	s := verifying(p, &recordingVerifier{}, evidenceSchemas(t))
	r := publish(t, s, candidateBundle(t, "", nil,
		member(t, "1828/waiting_period", claim("SOURCE_SUPPORTED", "present",
			evidenceObject(refOne, 5, 120, 168, "等待期为90日"),
			evidenceObject(refTwo, 2, 0, 4, "等待期间")), refOne, refTwo),
		member(t, "concept/waiting_period", claim("MODEL_GENERATED", "present"))))
	ctx := context.Background()

	at, err := s.Evidence(ctx, principal(), spaceID, r.ID, "1828/waiting_period", 1)
	require.NoError(t, err)
	require.Equal(t, r.ID, at.ReleaseID)
	require.Equal(t, "1828/waiting_period", at.Slug)
	require.Equal(t, 1, at.Index)
	require.Equal(t, "SOURCE_SUPPORTED", at.Origin)
	require.Equal(t, refTwo, at.Evidence.SourceRef)
	require.Equal(t, "等待期间", at.Evidence.Quote)

	cases := []struct {
		release, slug string
		index         int
		code          string
	}{
		{"", "1828/waiting_period", 0, release.ErrorReleaseNotFound},
		{"active", "1828/waiting_period", 0, release.ErrorReleaseNotFound},
		{"release-404", "1828/waiting_period", 0, release.ErrorReleaseNotFound},
		{r.ID, "1828/unknown", 0, release.ErrorMemberNotFound},
		{r.ID, "1828/waiting_period", 2, release.ErrorEvidenceNotFound},
		{r.ID, "1828/waiting_period", -1, release.ErrorEvidenceNotFound},
		{r.ID, "concept/waiting_period", 0, release.ErrorEvidenceNotFound},
	}
	for _, c := range cases {
		_, err := s.Evidence(ctx, principal(), spaceID, c.release, c.slug, c.index)
		require.Equal(t, c.code, codeOf(t, err), fmt.Sprintf("%+v", c))
	}
	_, err = s.Evidence(ctx, release.Principal{TenantID: 7}, spaceID, r.ID, "1828/waiting_period", 0)
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
}
