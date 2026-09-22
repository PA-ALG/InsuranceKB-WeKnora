package service

import (
	"context"
	"encoding/json"
	"sort"

	"github.com/Tencent/WeKnora/internal/types"
)

const (
	G3PlatformBaseSnapshotContractV1        = "g3-platform-base-snapshot.830.v1"
	G3PlatformBaseSnapshotSigningDomainV1   = "weknora.g3-platform-base-snapshot.830.v1"
	G3PlatformSignedBaseSnapshotContractV1  = "g3-platform-signed-base-snapshot.830.v1"
	G3PlatformPublishedProjectionContractV1 = "g3-platform-published-projection.830.v1"
)

type G3PlatformBaseSnapshotAuthorizer interface {
	AuthorizeG3PlatformBaseSnapshot(
		context.Context, types.WikiReleaseScope, string, uint64,
	) error
}

type G3PlatformBaseMemberDigestV1 struct {
	Kind         string `json:"kind"`
	LogicalSlug  string `json:"logical_slug"`
	RevisionID   string `json:"revision_id"`
	MemberDigest string `json:"member_digest"`
}

type G3PlatformPublishedParentV1 struct {
	ReleaseID       string `json:"release_id"`
	ActivationEpoch uint64 `json:"activation_epoch"`
}

type G3PlatformPublishedCatalogIdentityV1 struct {
	CatalogID      string `json:"catalog_id"`
	CatalogVersion string `json:"catalog_version"`
	CatalogSHA256  string `json:"catalog_sha256"`
}

// G3PlatformPublishedProjectionV1 contains only the signed data required to
// carry an existing published base into the next compile. It is not a candidate
// bundle and contains no model execution, review decision, admission, or raw output.
type G3PlatformPublishedProjectionV1 struct {
	Contract              string                               `json:"contract"`
	OriginContract        string                               `json:"origin_contract"`
	Parent                G3PlatformPublishedParentV1          `json:"parent"`
	Sources               []types.ConceptSourceBlock830G2      `json:"sources"`
	Catalog               G3PlatformPublishedCatalogIdentityV1 `json:"catalog"`
	EntityBindings        []types.EntityCompileBinding830G3    `json:"entity_bindings"`
	EntityVersions        map[string]string                    `json:"entity_versions"`
	Definitions           []types.ConceptDefinition830G2       `json:"definitions"`
	Fields                []types.ConceptFieldAssertion830G2   `json:"fields"`
	Pages                 []types.ConceptFreeWikiPage830G2     `json:"pages"`
	PageMembers           []types.ConceptPageMember830G2       `json:"page_members"`
	NavigationAssignments []types.NavigationAssignment830G3    `json:"navigation_assignments"`
	CandidateHash         string                               `json:"candidate_hash"`
}

// G3PlatformBaseSnapshotV1 is the complete incremental-base closure retained
// by the signed published projection. It is deliberately not represented as a
// replayable copy of the original candidate: model and review raw outputs are
// absent from the published projection by design.
type G3PlatformBaseSnapshotV1 struct {
	Contract                    string                          `json:"contract"`
	Scope                       types.WikiReleaseScope          `json:"scope"`
	ReleaseID                   string                          `json:"release_id"`
	ActivationEpoch             uint64                          `json:"activation_epoch"`
	PreparationID               string                          `json:"preparation_id"`
	CandidateSHA256             string                          `json:"candidate_sha256"`
	ManifestDigest              string                          `json:"manifest_digest"`
	PublishedProjectionContract string                          `json:"published_projection_contract"`
	PublishedProjection         G3PlatformPublishedProjectionV1 `json:"published_projection"`
	Members                     []G3PlatformBaseMemberDigestV1  `json:"members"`
	SnapshotSHA256              string                          `json:"snapshot_sha256"`
}

type G3PlatformSignedBaseSnapshotV1 struct {
	Contract  string                        `json:"contract"`
	Snapshot  G3PlatformBaseSnapshotV1      `json:"snapshot"`
	Authority G3PlatformSnapshotAuthorityV1 `json:"authority"`
}

type G3PlatformBaseSnapshotService struct {
	releases   *WikiReleaseService
	authorizer G3PlatformBaseSnapshotAuthorizer
	signer     G3PlatformSnapshotSigner
}

func NewG3PlatformBaseSnapshotService(
	releases *WikiReleaseService,
	authorizer G3PlatformBaseSnapshotAuthorizer,
	signer G3PlatformSnapshotSigner,
) *G3PlatformBaseSnapshotService {
	return &G3PlatformBaseSnapshotService{
		releases: releases, authorizer: authorizer, signer: signer,
	}
}

func (s *G3PlatformBaseSnapshotService) Read(
	ctx context.Context,
	scope types.WikiReleaseScope,
	releaseID string,
	activationEpoch uint64,
) (*G3PlatformSignedBaseSnapshotV1, error) {
	if s == nil || s.releases == nil || s.releases.repository == nil ||
		s.authorizer == nil || s.signer == nil || !validG3PlatformScope(scope) ||
		releaseID == "" || activationEpoch == 0 {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	if err := s.authorizer.AuthorizeG3PlatformBaseSnapshot(
		ctx, scope, releaseID, activationEpoch,
	); err != nil {
		return nil, ErrG3PlatformSnapshotUnauthorized
	}
	snapshot, err := s.releases.loadG3PlatformBaseSnapshot(ctx, scope, releaseID, activationEpoch)
	if err != nil {
		return nil, err
	}

	authority, err := signG3PlatformSnapshot(
		ctx, s.signer, G3PlatformBaseSnapshotSigningDomainV1, snapshot.SnapshotSHA256,
	)
	if err != nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	return &G3PlatformSignedBaseSnapshotV1{
		Contract: G3PlatformSignedBaseSnapshotContractV1,
		Snapshot: *snapshot, Authority: authority,
	}, nil
}

// Both signed reads and candidate transfer resolve the same immutable base.
// Callers authorize scope before entry and recheck current policy at write time.
func (s *WikiReleaseService) loadG3PlatformBaseSnapshot(ctx context.Context, scope types.WikiReleaseScope, releaseID string, activationEpoch uint64) (*G3PlatformBaseSnapshotV1, error) {
	if s == nil || s.repository == nil || !validG3PlatformScope(scope) || releaseID == "" || activationEpoch == 0 {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	head, err := s.repository.GetHead(ctx, scope)
	if err != nil || head == nil || head.WikiReleaseScope != scope ||
		head.ActiveReleaseID != releaseID || head.ActivationEpoch != activationEpoch {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	release, err := s.repository.GetRelease(ctx, scope, releaseID)
	if err != nil || release == nil || release.ID != releaseID ||
		release.WikiReleaseScope != scope || release.BaseActivationEpoch == ^uint64(0) ||
		release.BaseActivationEpoch+1 != activationEpoch || release.PreparationID == "" {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	preparation, projection, expectedMembers, projectedG3, err :=
		s.loadPublishedBatchReadProjection830G3(ctx, scope, release.PreparationID)
	if err != nil || !projectedG3 || preparation == nil ||
		preparation.ID != release.PreparationID ||
		preparation.Status != types.WikiReleasePreparationReady ||
		preparation.CandidateDigest != release.CandidateDigest ||
		preparation.ManifestDigest != release.ManifestDigest ||
		preparation.ExpectedReleaseID != release.BaseReleaseID ||
		preparation.ExpectedActivationEpoch != release.BaseActivationEpoch ||
		projection.CandidateHash != release.CandidateDigest ||
		batchConceptScope830G3(projection) != scope {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	storedMembers, err := s.repository.GetReleaseMembers(ctx, scope, releaseID)
	if err != nil || !publishedBatchMemberIdentitiesEqual830G3(expectedMembers, storedMembers) {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	members := make([]G3PlatformBaseMemberDigestV1, 0, len(expectedMembers))
	for _, member := range expectedMembers {
		if member.Kind == "" || member.LogicalSlug == "" || member.RevisionID == "" ||
			member.MemberDigest == "" {
			return nil, ErrG3PlatformSnapshotUnavailable
		}
		members = append(members, G3PlatformBaseMemberDigestV1{
			Kind: member.Kind, LogicalSlug: member.LogicalSlug,
			RevisionID: member.RevisionID, MemberDigest: member.MemberDigest,
		})
	}
	sort.Slice(members, func(i, j int) bool {
		if members[i].Kind == members[j].Kind {
			return members[i].LogicalSlug < members[j].LogicalSlug
		}
		return members[i].Kind < members[j].Kind
	})
	for index := 1; index < len(members); index++ {
		if members[index-1].Kind == members[index].Kind &&
			members[index-1].LogicalSlug == members[index].LogicalSlug {
			return nil, ErrG3PlatformSnapshotUnavailable
		}
	}
	publishedProjection, err := g3PlatformPublishedProjectionFromBundle(scope, projection)
	if err != nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	snapshot := G3PlatformBaseSnapshotV1{
		Contract: G3PlatformBaseSnapshotContractV1, Scope: scope,
		ReleaseID: releaseID, ActivationEpoch: activationEpoch,
		PreparationID: release.PreparationID, CandidateSHA256: release.CandidateDigest,
		ManifestDigest:              release.ManifestDigest,
		PublishedProjectionContract: G3PlatformPublishedProjectionContractV1,
		PublishedProjection:         publishedProjection, Members: members,
	}
	snapshot.SnapshotSHA256, err = g3PlatformSnapshotDigest(
		snapshot.Contract, snapshot, "snapshot_sha256",
	)
	if err != nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	return &snapshot, nil
}

func g3PlatformPublishedProjectionFromBundle(
	scope types.WikiReleaseScope,
	bundle types.BatchConceptCandidateBundle830G3,
) (G3PlatformPublishedProjectionV1, error) {
	var empty G3PlatformPublishedProjectionV1
	if batchConceptScope830G3(bundle) != scope || !validServiceSHA256(bundle.CandidateHash) {
		return empty, ErrG3PlatformSnapshotUnavailable
	}
	entityVersions := make(map[string]string, len(bundle.Request.EntityBindings))
	for _, binding := range bundle.Request.EntityBindings {
		if binding.EntityID == "" || binding.EntityVersion == "" {
			return empty, ErrG3PlatformSnapshotUnavailable
		}
		if _, duplicate := entityVersions[binding.EntityID]; duplicate {
			return empty, ErrG3PlatformSnapshotUnavailable
		}
		entityVersions[binding.EntityID] = binding.EntityVersion
	}
	projection := G3PlatformPublishedProjectionV1{
		Contract:       G3PlatformPublishedProjectionContractV1,
		OriginContract: publishedBatchReadProjectionContract830G3,
		Parent: G3PlatformPublishedParentV1{
			ReleaseID:       bundle.Request.BaseRequest.BaseReleaseID,
			ActivationEpoch: bundle.Request.BaseRequest.BaseActivationEpoch,
		},
		Sources: bundle.Request.BaseRequest.Sources,
		Catalog: G3PlatformPublishedCatalogIdentityV1{
			CatalogID:      bundle.Request.Catalog.CatalogID,
			CatalogVersion: bundle.Request.Catalog.CatalogVersion,
			CatalogSHA256:  bundle.Request.Catalog.CatalogSHA256,
		},
		EntityBindings:        bundle.Request.EntityBindings,
		EntityVersions:        entityVersions,
		Definitions:           bundle.CompileResult.Output.Definitions,
		Fields:                bundle.CompileResult.Output.Fields,
		Pages:                 bundle.CompileResult.Output.Pages,
		PageMembers:           bundle.PageManifest.Members,
		NavigationAssignments: bundle.NavigationAssignments,
		CandidateHash:         bundle.CandidateHash,
	}
	// The signed service envelope must not alias the read-projection cache.
	raw, err := json.Marshal(projection)
	if err != nil || json.Unmarshal(raw, &projection) != nil {
		return empty, ErrG3PlatformSnapshotUnavailable
	}
	return projection, nil
}
