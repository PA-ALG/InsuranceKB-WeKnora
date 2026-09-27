package service

import (
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestBatchProductBindingsReopenStoredCandidateWithoutPublishing(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(fixture.ctx, fixture.principal1, fixture.scope,
		"g3-bindings-restart", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	headBefore, err := fixture.repo.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, err)
	// A new service instance must derive its bindings from stored authority.
	reopened := NewSchemaWikiService(fixture.service, nil)
	got, err := reopened.ReadBatchProductBindings830G3(fixture.ctx, fixture.principal1,
		fixture.scope, draft.ID)
	require.NoError(t, err)
	require.Equal(t, "CANDIDATE", got.BindingState)
	require.Empty(t, got.ReleaseID)
	require.Equal(t, bundle.CandidateHash, got.CandidateSHA256)
	require.Equal(t, bundle.Request.EntityBindings, got.Bindings)
	require.NotEmpty(t, got.ReadSHA256)
	require.Equal(t, types.WikiReleasePreparationDraft, draft.Status)
	headAfter, err := fixture.repo.GetHead(fixture.ctx, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, headBefore, headAfter)
	denied := fixture.scope
	denied.TenantID++
	_, err = reopened.ReadBatchProductBindings830G3(fixture.ctx, fixture.principal1, denied, draft.ID)
	require.Error(t, err)
}

func TestBatchProductBindingsCurrentUsesPublishedAuthorityAndExactVersion(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(fixture.ctx, fixture.principal1, fixture.scope,
		"g3-bindings-current", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	_, err = schema.ReadBatchProductBindings830G3(fixture.ctx, fixture.principal1, fixture.scope, "")
	require.Error(t, err) // An unpublished candidate must not become current.
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "g3-bindings-current")
	ready, err := schema.ReviewSchemaDraft(fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision)
	require.NoError(t, err)
	published, err := fixture.service.ActivateReviewed(fixture.ctx, fixture.principal1, rawDecision,
		conceptAuthorization830G2(t, fixture, ready, decision))
	require.NoError(t, err)
	reopened := NewSchemaWikiService(fixture.service, nil)
	got, err := reopened.ReadBatchProductBindings830G3(fixture.ctx, fixture.principal1, fixture.scope, "")
	require.NoError(t, err)
	require.Equal(t, "PUBLISHED", got.BindingState)
	require.Equal(t, published.ReleaseID, got.ReleaseID)
	require.Equal(t, bundle.Request.EntityBindings, got.Bindings)
	require.Equal(t, bundle.Request.Catalog.CatalogSHA256, got.CatalogSHA256)
}
