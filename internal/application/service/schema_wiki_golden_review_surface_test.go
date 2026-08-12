package service

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// schemaWikiGoldenReviewSurfaceRED is the frozen tests-only seam for the
// worktree1 contract. It intentionally names concrete DTOs that do not exist
// before that contract lands. The production implementation must remain on
// SchemaWikiService and the existing preparation repository; a parallel store
// or caller-selected generic payload does not satisfy this seam.
type schemaWikiGoldenReviewSurfaceRED interface {
	CreateSchemaDraft(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		types.KnowledgeWikiReleaseV1,
		types.Schema67CandidateEvidenceAuthorityV1,
		types.SchemaWikiReviewBundleV1,
		types.Schema67GoldenEvaluationReviewBundleV1,
		types.Schema67GoldenReviewSuccessorMetadataV1,
	) (*types.WikiReleasePreparation, error)
	ReadSchemaPreparationGoldenQualitySummary(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
	) (*types.SchemaWikiGoldenQualitySummaryV1, error)
	ReadSchemaPreparationGoldenQualityDossier(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
	) (*types.SchemaWikiGoldenQualityDossierV2, error)
	IssueSchemaPreparationGoldenEvidencePreview(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
		string,
		string,
	) (*types.SchemaWikiGoldenEvidencePreviewAuthorityV1, error)
}

var _ schemaWikiGoldenReviewSurfaceRED = (*SchemaWikiService)(nil)

type schemaWikiGoldenEvidenceContentSpy struct {
	issueCalls int
	readCalls  int
	request    CitationRevisionReadRequestV1
	authority  *types.SchemaWikiGoldenEvidencePreviewAuthorityV1
}

func (s *schemaWikiGoldenEvidenceContentSpy) IssueExactRevision(
	context.Context, CitationRevisionReadRequestV1,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	return nil, ErrSchemaWikiCitationUnavailable
}

func (s *schemaWikiGoldenEvidenceContentSpy) ResolveOpaqueToken(
	context.Context, types.WikiReleaseScope, string,
) (*types.SchemaWikiCitationContentAuthorityV1, error) {
	return nil, ErrSchemaWikiCitationUnavailable
}

func (s *schemaWikiGoldenEvidenceContentSpy) ReadByOpaqueToken(
	context.Context, types.WikiReleaseScope, string, CitationRevisionReadRequestV1,
) ([]byte, error) {
	return nil, ErrSchemaWikiCitationUnavailable
}

func (s *schemaWikiGoldenEvidenceContentSpy) IssuePreparationExactRevision(
	_ context.Context,
	preparationID string,
	evaluationID string,
	evidenceID string,
	request CitationRevisionReadRequestV1,
) (*types.SchemaWikiGoldenEvidencePreviewAuthorityV1, error) {
	s.issueCalls++
	s.request = request
	receipt := request.CoordinateAuthorityReceipt
	authority := types.SchemaWikiGoldenEvidencePreviewAuthorityV1{
		Contract:               "schema-wiki-golden-evidence-preview-authority.v1",
		TokenKeyID:             "golden-evidence-test-key",
		PreparationID:          preparationID,
		EvaluationID:           evaluationID,
		CandidateSHA256:        request.CandidateSHA256,
		FieldID:                request.FieldID,
		EvidenceID:             evidenceID,
		RevisionSource:         receipt.LiveRevisionSourceReceipt,
		CitationSHA256:         request.Citation.CitationSHA256,
		BindingSHA256:          request.Binding.BindingSHA256,
		EvidenceReceiptSHA256:  receipt.EvidenceReceiptSHA256,
		PageNumber:             request.Citation.PageNumber,
		BBox:                   request.Citation.BBox,
		QuoteSHA256:            request.Citation.QuoteSHA256,
		ContentSnapshotSHA256:  request.Citation.ContentSnapshotSHA256,
		CoordinateSpaceVersion: receipt.TargetCoordinateSpace,
		PageWidth:              receipt.PageWidth,
		PageHeight:             receipt.PageHeight,
		RotationDegrees:        receipt.RotationDegrees,
		RetentionState:         types.KnowledgeRevisionSourcePinned,
		ExpiresAtUnix:          time.Now().Add(time.Minute).Unix(),
	}
	digest, err := types.ComputeSchemaWikiGoldenEvidencePreviewAuthoritySHA256(authority)
	if err != nil {
		return nil, err
	}
	authority.AuthoritySHA256 = digest
	authority.OpaqueToken = "opaque-test-token"
	s.authority = &authority
	return &authority, nil
}

func (s *schemaWikiGoldenEvidenceContentSpy) ResolvePreparationOpaqueToken(
	context.Context, types.WikiReleaseScope, string,
) (*types.SchemaWikiGoldenEvidencePreviewAuthorityV1, error) {
	if s.authority == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	copy := *s.authority
	return &copy, nil
}

func (s *schemaWikiGoldenEvidenceContentSpy) ReadPreparationByOpaqueToken(
	context.Context,
	types.WikiReleaseScope,
	string,
	string,
	string,
	string,
	CitationRevisionReadRequestV1,
) ([]byte, error) {
	s.readCalls++
	return []byte("%PDF-1.7\nreview-only\n%%EOF"), nil
}

func (s *schemaWikiGoldenEvidenceContentSpy) ResolveRouteAuthority(
	context.Context,
	string,
) (*SchemaWikiCitationContentRouteAuthorityV1, error) {
	if s.authority == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return &SchemaWikiCitationContentRouteAuthorityV1{
		Kind: "preparation",
		Scope: types.WikiReleaseScope{
			TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
		},
		PreparationID: s.authority.PreparationID,
	}, nil
}

func TestSchemaWikiGoldenEvaluationBundlePersistsInExistingPreparationCustody(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	bundle := reviewed.EvaluationBundle

	created, err := fixture.adapter.CreateSchemaDraft(
		fixture.ctx,
		principal,
		scope,
		reviewed.PreparationID,
		reviewed.Release,
		reviewed.EvidenceAuthority,
		reviewed.ReviewBundle,
		bundle,
		reviewed.ReviewSuccessor,
	)
	require.NoError(t, err)
	require.NotNil(t, created)
	require.Equal(t, int64(1), fixture.storedCount(t))
	heads, releases, receipts := fixture.stateCounts(t)
	require.Zero(t, heads)
	require.Zero(t, releases)
	require.Zero(t, receipts)

	stored := fixture.storedPreparation(t, created.ID)
	var custody map[string]json.RawMessage
	require.NoError(t, json.Unmarshal(stored.Manifest, &custody))
	require.Contains(t, custody, "evaluation_bundle")
	require.NotEmpty(t, custody["evaluation_bundle"])

	normalizeSchemaWikiPreparationAsPostgresJSONB(t, fixture, created.ID)
	public, err := fixture.adapter.ReadSchemaPreparationGoldenQualitySummary(
		fixture.ctx, principal, scope, created.ID, bundle.EvaluationID,
	)
	require.NoError(t, err)
	private, err := fixture.adapter.ReadSchemaPreparationGoldenQualityDossier(
		fixture.ctx, principal, scope, created.ID, bundle.EvaluationID,
	)
	require.NoError(t, err)
	require.Equal(t, bundle.PublicAggregate, public.PublicAggregate)
	require.Equal(t, bundle.PrivateDossier, private.PrivateDossier)
	require.Equal(t, reviewed.ReviewSuccessor, private.ReviewSuccessor)
	require.Equal(t, "schema-wiki-golden-quality-dossier.v2", private.Version)
	require.False(t, public.WikiAdmissionAllowed)
	require.Equal(t, "NONE", public.ServingEffect)
	require.Equal(t, "NONE", private.ServingEffect)
}

func TestSchemaWikiGoldenMetadataIncompleteOrEvidenceSubstitutedCannotCreateDraft(t *testing.T) {
	t.Parallel()
	for _, testCase := range []struct {
		name   string
		mutate func(*testing.T, *types.Schema67GoldenReviewSuccessorMetadataV1)
	}{
		{
			name: "metadata incomplete unsigned",
			mutate: func(t *testing.T, value *types.Schema67GoldenReviewSuccessorMetadataV1) {
				value.HumanReviewLayer.ReviewedAt = ""
				value.HumanReviewLayer.ReceiptStatus = "UNVERIFIED"
				value.MetadataSHA256 = schemaWikiTestHashWithout(
					t, value.Contract, *value, "metadata_sha256",
				)
			},
		},
		{
			name: "candidate evidence substitution",
			mutate: func(t *testing.T, value *types.Schema67GoldenReviewSuccessorMetadataV1) {
				for fieldIndex := range value.OrderedFields {
					field := &value.OrderedFields[fieldIndex]
					if len(field.EvidenceChanges) == 0 {
						continue
					}
					foreign := strings.Repeat("f", 64)
					field.EvidenceChanges[0].CandidateEvidenceID = &foreign
					field.EvidenceChanges[0].ChangeSHA256 = schemaWikiTestHashWithout(
						t, "schema67-golden-evidence-change.v1",
						field.EvidenceChanges[0], "change_sha256",
					)
					field.FieldMetadataSHA256 = schemaWikiTestHashWithout(
						t, "schema67-golden-review-field-metadata.v1",
						*field, "field_metadata_sha256",
					)
					break
				}
				value.MetadataSHA256 = schemaWikiTestHashWithout(
					t, value.Contract, *value, "metadata_sha256",
				)
			},
		},
		{
			name: "candidate value substitution",
			mutate: func(t *testing.T, value *types.Schema67GoldenReviewSuccessorMetadataV1) {
				for fieldIndex := range value.OrderedFields {
					field := &value.OrderedFields[fieldIndex]
					if field.CandidateValue.Mode != "LITERAL" {
						continue
					}
					foreign := "caller-selected-value"
					digest := schemaWikiTestHash(
						t, "schema67-golden-review-value.v1", map[string]string{"literal": foreign},
					)
					field.CandidateValue.Literal = &foreign
					field.CandidateValue.SHA256 = &digest
					field.FieldMetadataSHA256 = schemaWikiTestHashWithout(
						t, "schema67-golden-review-field-metadata.v1",
						*field, "field_metadata_sha256",
					)
					break
				}
				value.MetadataSHA256 = schemaWikiTestHashWithout(
					t, value.Contract, *value, "metadata_sha256",
				)
			},
		},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			raw, err := json.Marshal(reviewed.ReviewSuccessor)
			require.NoError(t, err)
			var forged types.Schema67GoldenReviewSuccessorMetadataV1
			require.NoError(t, json.Unmarshal(raw, &forged))
			testCase.mutate(t, &forged)

			created, err := fixture.adapter.CreateSchemaDraft(
				fixture.ctx, principal, scope, reviewed.PreparationID,
				reviewed.Release, reviewed.EvidenceAuthority, reviewed.ReviewBundle,
				reviewed.EvaluationBundle, forged,
			)
			require.Nil(t, created)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
			require.Zero(t, fixture.storedCount(t))
			heads, releases, receipts := fixture.stateCounts(t)
			require.Zero(t, heads)
			require.Zero(t, releases)
			require.Zero(t, receipts)
		})
	}
}

func TestSchemaWikiGoldenFailOrFixtureCannotCreateDraft(t *testing.T) {
	t.Parallel()
	for _, status := range []string{"FAIL", "FIXTURE_ONLY", "INCONCLUSIVE"} {
		t.Run(status, func(t *testing.T) {
			principal, scope, reviewed := schemaWikiReviewedDraft(t)
			fixture := newSchemaWikiPrepareFixture(t, principal, scope)
			bundle := reviewed.EvaluationBundle
			bundle.QualityGateReceipt.Status = status

			created, err := fixture.adapter.CreateSchemaDraft(
				fixture.ctx,
				principal,
				scope,
				reviewed.PreparationID,
				reviewed.Release,
				reviewed.EvidenceAuthority,
				reviewed.ReviewBundle,
				bundle,
				reviewed.ReviewSuccessor,
			)
			require.Nil(t, created)
			require.ErrorIs(t, err, ErrSchemaWikiPreparationInvalid)
			require.Zero(t, fixture.storedCount(t))
			heads, releases, receipts := fixture.stateCounts(t)
			require.Zero(t, heads)
			require.Zero(t, releases)
			require.Zero(t, receipts)
		})
	}
}

func TestSchemaWikiGoldenPrivateDossierRequiresNamedHumanReviewer(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	bundle := reviewed.EvaluationBundle
	created, err := fixture.adapter.CreateSchemaDraft(
		fixture.ctx,
		principal,
		scope,
		reviewed.PreparationID,
		reviewed.Release,
		reviewed.EvidenceAuthority,
		reviewed.ReviewBundle,
		bundle,
		reviewed.ReviewSuccessor,
	)
	require.NoError(t, err)

	apiKey := types.WikiReleasePrincipal{
		ID: "api-key-reviewer", TenantID: scope.TenantID, SpaceID: scope.SpaceID,
		APIKeyKnowledgeBaseIDs: []string{scope.WikiKBID, scope.RawKBID},
	}
	dossier, err := fixture.adapter.ReadSchemaPreparationGoldenQualityDossier(
		fixture.ctx, apiKey, scope, created.ID, bundle.EvaluationID,
	)
	require.Nil(t, dossier)
	require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
}

func TestSchemaWikiGoldenEvidencePreviewSelectsStoredJoinOnly(t *testing.T) {
	t.Parallel()
	principal, scope, reviewed := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	content := &schemaWikiGoldenEvidenceContentSpy{}
	fixture.adapter = NewSchemaWikiService(fixture.authority, nil, content)
	created := createSchemaWikiDraft(t, fixture, principal, scope, reviewed)
	join := reviewed.EvidenceAuthority.JoinReceipts[0]
	var selectedDecision *types.Schema67GoldenFieldDecisionV1
	for index := range reviewed.EvaluationBundle.PrivateDossier.FieldDecisions {
		decision := &reviewed.EvaluationBundle.PrivateDossier.FieldDecisions[index]
		if decision.FieldID == join.FieldID {
			selectedDecision = decision
			break
		}
	}
	require.NotNil(t, selectedDecision)
	require.Positive(t, selectedDecision.EvidenceFragments)
	request, requestErr := schemaWikiPreparationCitationRequest(
		validatedSchemaWikiCustody{
			release:                    reviewed.Release,
			candidateEvidenceAuthority: reviewed.EvidenceAuthority,
		},
		scope,
		created.ID,
		reviewed.EvaluationBundle.EvaluationID,
		join.ReceiptSHA256,
		"field:"+join.FieldID,
		"citation-"+join.ReceiptSHA256[:24],
	)
	require.NoError(t, requestErr)
	require.Equal(t, join.ReceiptSHA256, request.CoordinateAuthorityReceipt.ReceiptSHA256)

	authority, err := fixture.adapter.IssueSchemaPreparationGoldenEvidencePreview(
		fixture.ctx,
		principal,
		scope,
		created.ID,
		reviewed.EvaluationBundle.EvaluationID,
		join.FieldID,
		join.ReceiptSHA256,
	)
	require.NoError(t, err)
	require.NotNil(t, authority)
	require.Equal(t, created.ID, authority.PreparationID)
	require.Equal(t, join.FieldID, authority.FieldID)
	require.Equal(t, join.ReceiptSHA256, authority.EvidenceID)
	require.Equal(t, join.LiveRevisionSourceReceipt, authority.RevisionSource)
	require.NotEmpty(t, authority.OpaqueToken)
	require.Equal(t, 1, content.issueCalls)
	require.Equal(t, join.ReceiptSHA256, content.request.CoordinateAuthorityReceipt.ReceiptSHA256)
	opened, err := fixture.adapter.ReadSchemaCitationContent(
		fixture.ctx, principal, scope, authority.OpaqueToken,
	)
	require.NoError(t, err)
	require.Equal(t, []byte("%PDF-1.7\nreview-only\n%%EOF"), opened)
	require.Equal(t, 1, content.readCalls)

	foreign, err := fixture.adapter.IssueSchemaPreparationGoldenEvidencePreview(
		fixture.ctx,
		principal,
		scope,
		created.ID,
		reviewed.EvaluationBundle.EvaluationID,
		join.FieldID,
		"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
	)
	require.Nil(t, foreign)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Equal(t, 1, content.issueCalls, "foreign Evidence must fail before token issuance")
}
