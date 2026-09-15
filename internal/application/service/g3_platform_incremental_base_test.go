package service

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func hashPublishedBaseBinding830G3(
	t *testing.T, binding types.PublishedBaseBinding830G3,
) string {
	t.Helper()
	raw, err := json.Marshal(binding)
	require.NoError(t, err)
	var payload map[string]json.RawMessage
	require.NoError(t, json.Unmarshal(raw, &payload))
	delete(payload, "binding_sha256")
	raw, err = json.Marshal(payload)
	require.NoError(t, err)
	canonical, err := types.CanonicalConceptMemberPayload830G2(raw)
	require.NoError(t, err)
	digest := sha256.Sum256(append(
		[]byte("schema-wiki-canonical.v1\x00"+binding.Contract+"\x00"), canonical...,
	))
	return hex.EncodeToString(digest[:])
}

func TestBatchConceptIncrementalBaseUsesSignedPublishedProjectionAndExactBinding(t *testing.T) {
	fixture, schema, parent := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-incremental-parent", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "batch-g3-incremental-parent")
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	receipt, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision,
		conceptAuthorization830G2(t, fixture, ready, decision),
	)
	require.NoError(t, err)
	release, err := fixture.repo.GetRelease(fixture.ctx, fixture.scope, receipt.ReleaseID)
	require.NoError(t, err)

	next := parent
	next.Request.BaseRequest.BaseReleaseID = receipt.ReleaseID
	next.Request.BaseRequest.BaseActivationEpoch = receipt.ActivationEpoch
	next.Request.BaseRequest.ExistingDefinitions = parent.CompileResult.Output.Definitions
	next.Request.BaseRequest.ExistingFields = parent.CompileResult.Output.Fields
	next.Request.BaseRequest.ExistingPages = parent.CompileResult.Output.Pages
	next.Request.BaseRequest.ExistingEntityVersions = map[string]string{}
	for _, binding := range parent.Request.EntityBindings {
		next.Request.BaseRequest.ExistingEntityVersions[binding.EntityID] = binding.EntityVersion
	}
	binding := types.PublishedBaseBinding830G3{
		Contract:        "published-base-binding.830.g3.v1",
		ReleaseID:       receipt.ReleaseID,
		ActivationEpoch: receipt.ActivationEpoch,
		CandidateSHA256: parent.CandidateHash,
		ManifestDigest:  release.ManifestDigest,
		EntityBindings:  parent.Request.EntityBindings,
	}
	binding.BindingSHA256 = hashPublishedBaseBinding830G3(t, binding)
	next.Request.PublishedBase = &binding

	before := batchPreparationValidations830G3.Load()
	require.NoError(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, next))
	require.Equal(t, before, batchPreparationValidations830G3.Load(), "hot parent projection must avoid replaying old C")

	// A restart reads the signed gob projection. Empty optional slices may then
	// be nil even though the exact compiler request carries explicit empty arrays.
	fixture.service.publishedBatchReuse830G3().entries = map[string]publishedBatchReadCache830G3{}
	nextBefore, err := json.Marshal(next)
	require.NoError(t, err)
	require.NoError(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, next))
	require.Equal(t, before, batchPreparationValidations830G3.Load(), "cold reuse must not replay old compilation")
	nextAfter, err := json.Marshal(next)
	require.NoError(t, err)
	require.Equal(t, nextBefore, nextAfter, "comparison cannot mutate candidate input")
	for name, mutate := range map[string]func(*types.BatchConceptCandidateBundle830G3){
		"value": func(b *types.BatchConceptCandidateBundle830G3) {
			v := "changed"
			b.Request.BaseRequest.ExistingFields[0].Value = &v
		},
		"condition": func(b *types.BatchConceptCandidateBundle830G3) {
			b.Request.BaseRequest.ExistingFields[0].Conditions = []string{"new condition"}
		},
		"evidence page": func(b *types.BatchConceptCandidateBundle830G3) {
			for i := range b.Request.BaseRequest.ExistingFields {
				if len(b.Request.BaseRequest.ExistingFields[i].Evidence) > 0 {
					b.Request.BaseRequest.ExistingFields[i].Evidence[0].PageNumber++
					return
				}
			}
			t.Fatal("fixture must contain evidenced fields")
		},
		"member order": func(b *types.BatchConceptCandidateBundle830G3) {
			rows := b.Request.BaseRequest.ExistingFields
			require.Greater(t, len(rows), 1)
			rows[0], rows[1] = rows[1], rows[0]
		},
	} {
		t.Run(name, func(t *testing.T) {
			var changed types.BatchConceptCandidateBundle830G3
			require.NoError(t, json.Unmarshal(nextBefore, &changed))
			mutate(&changed)
			require.ErrorIs(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, changed), ErrSchemaWikiPreparationInvalid)
		})
	}

	forged := next
	forgedBinding := binding
	forgedBinding.EntityBindings = append([]types.EntityCompileBinding830G3(nil), binding.EntityBindings...)
	forgedBinding.EntityBindings[0].DisplayName += " changed"
	forgedBinding.BindingSHA256 = hashPublishedBaseBinding830G3(t, forgedBinding)
	forged.Request.PublishedBase = &forgedBinding
	require.ErrorIs(t, schema.validateBatchConceptBase830G3(fixture.ctx, fixture.scope, forged), ErrSchemaWikiPreparationInvalid)
}
