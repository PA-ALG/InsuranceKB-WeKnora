package service

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestActivateConceptReleaseChecksCurrentAccessBeforeSourceIO830G2(t *testing.T) {
	fixture, schema := conceptReleaseFixture830G2(t)
	draft, err := schema.CreateConceptFreeWikiDraft830G2(fixture.ctx, fixture.principal1, fixture.scope, "g2-access-before-source", conceptBundleVector830G2(t))
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "g2-access-before-source")
	ready, err := schema.ReviewSchemaDraft(fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision)
	require.NoError(t, err)
	verifier := fixture.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
	require.Len(t, verifier.requests, 1)
	delete(fixture.access.allowed, fixture.principal1.ID)

	_, err = fixture.service.ActivateReviewed(fixture.ctx, fixture.principal1, rawDecision, conceptAuthorization830G2(t, fixture, ready, decision))
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
	require.Len(t, verifier.requests, 1)
}
