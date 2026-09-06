package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"gorm.io/gorm"
)

// ConceptAgentService830G2 freezes release-managed Wiki content before an
// Agent turn registers any retrieval tool. It deliberately returns immutable
// member projections rather than the opaque release pin itself.
type ConceptAgentService830G2 struct {
	releaseAuthority     *WikiReleaseService
	knowledgeBaseService interfaces.KnowledgeBaseService
	db                   *gorm.DB
}

func NewConceptAgentService830G2(
	releaseAuthority *WikiReleaseService,
	knowledgeBaseService interfaces.KnowledgeBaseService,
	db *gorm.DB,
) *ConceptAgentService830G2 {
	return &ConceptAgentService830G2{
		releaseAuthority: releaseAuthority, knowledgeBaseService: knowledgeBaseService, db: db,
	}
}

func (s *ConceptAgentService830G2) PinConceptAgentTurn830G2(
	ctx context.Context,
	wikiScopes []interfaces.ConceptAgentWikiScope830G2,
) (*interfaces.ConceptAgentTurn830G2, error) {
	if s == nil || s.releaseAuthority == nil || s.releaseAuthority.repository == nil ||
		s.knowledgeBaseService == nil {
		return nil, fmt.Errorf("%w: concept Agent release service unavailable", ErrWikiReleaseAccessDenied)
	}
	contextTenantID, tenantOK := types.TenantIDFromContext(ctx)
	contextPrincipal, principalOK := types.PrincipalFromContext(ctx)
	if !tenantOK || contextTenantID == 0 || !principalOK {
		return nil, ErrWikiReleaseAccessDenied
	}

	turn := &interfaces.ConceptAgentTurn830G2{
		Releases: make(map[string]interfaces.ConceptAgentRelease830G2),
	}
	seen := make(map[string]uint64, len(wikiScopes))
	for _, requested := range wikiScopes {
		wikiKBID := strings.TrimSpace(requested.WikiKBID)
		tenantID := requested.TenantID
		if tenantID == 0 {
			tenantID = contextTenantID
		}
		if wikiKBID == "" || tenantID == 0 {
			continue
		}
		if existingTenant, duplicate := seen[wikiKBID]; duplicate {
			if existingTenant != tenantID {
				return nil, ErrWikiReleaseAccessDenied
			}
			continue
		}
		seen[wikiKBID] = tenantID

		head, err := s.releaseAuthority.repository.GetHeadForWikiKB(ctx, tenantID, wikiKBID)
		if errors.Is(err, wikirepository.ErrWikiReleaseNotFound) {
			managed, stateErr := s.hasConceptReleaseCustody830G2(ctx, tenantID, wikiKBID)
			if stateErr != nil || managed {
				return nil, ErrWikiReleaseAccessDenied
			}
			continue
		}
		if err != nil {
			return nil, mapWikiReleaseRepositoryError(err)
		}
		if head == nil || head.TenantID != tenantID || head.WikiKBID != wikiKBID ||
			head.SpaceID == "" || head.RawKBID == "" || head.ActiveReleaseID == "" ||
			head.ActivationEpoch == 0 {
			return nil, ErrWikiReleaseAccessDenied
		}
		// Cross-tenant managed release reads need their own current dual-ACL
		// resolver. Ordinary unmanaged shared Wikis keep the legacy path, but
		// a managed Head can never mint its own cross-tenant access proof.
		if tenantID != contextTenantID {
			return nil, ErrWikiReleaseAccessDenied
		}
		if err := s.requireOwnedConceptAgentScope830G2(ctx, tenantID, head.WikiReleaseScope); err != nil {
			return nil, err
		}
		if err := types.AuthorizeTenantAPIKeyKnowledgeBases(ctx, head.RawKBID, head.WikiKBID); err != nil {
			return nil, ErrWikiReleaseAccessDenied
		}
		principal := types.WikiReleasePrincipal{
			ID: contextPrincipal.StorageID(), TenantID: tenantID, SpaceID: head.SpaceID,
		}
		if apiKeyScope, ok := types.TenantAPIKeyScopeFromContext(ctx); ok {
			principal.APIKeyKnowledgeBaseIDs = append(
				[]string(nil), apiKeyScope.KnowledgeBaseIDs...,
			)
		}
		sealed := SealWikiReleaseAccess(ctx, principal, head.WikiReleaseScope)
		pin := WikiReleasePinnedRead{
			scope: head.WikiReleaseScope, releaseID: head.ActiveReleaseID,
			activationEpoch: head.ActivationEpoch,
		}
		pinned, err := s.pinConceptAgentRelease830G2(sealed, principal, pin)
		if err != nil {
			return nil, err
		}
		turn.Releases[wikiKBID] = pinned
	}
	return turn, nil
}

func (s *ConceptAgentService830G2) requireOwnedConceptAgentScope830G2(
	ctx context.Context,
	tenantID uint64,
	scope types.WikiReleaseScope,
) error {
	for _, kbID := range []string{scope.WikiKBID, scope.RawKBID} {
		kb, err := s.knowledgeBaseService.GetKnowledgeBaseByIDOnly(ctx, kbID)
		if err != nil || kb == nil || kb.ID != kbID || kb.TenantID != tenantID {
			return ErrWikiReleaseAccessDenied
		}
	}
	return nil
}

// hasConceptReleaseCustody830G2 distinguishes an ordinary mutable Wiki from a
// release-managed Wiki whose Head was lost or removed. Once any immutable
// preparation, release, or receipt exists, missing Head must fail closed.
func (s *ConceptAgentService830G2) hasConceptReleaseCustody830G2(
	ctx context.Context,
	tenantID uint64,
	wikiKBID string,
) (bool, error) {
	if s.db == nil {
		return false, errors.New("concept Agent release database unavailable")
	}
	models := []any{
		&types.WikiReleasePreparation{},
		&types.WikiRelease{},
		&types.WikiReleaseReceipt{},
	}
	for _, model := range models {
		var count int64
		if err := s.db.WithContext(ctx).Model(model).
			Where("tenant_id = ? AND wiki_kb_id = ?", tenantID, wikiKBID).
			Limit(1).Count(&count).Error; err != nil {
			return false, err
		}
		if count > 0 {
			return true, nil
		}
	}
	return false, nil
}

func (s *ConceptAgentService830G2) pinConceptAgentRelease830G2(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	pin WikiReleasePinnedRead,
) (interfaces.ConceptAgentRelease830G2, error) {
	if err := s.releaseAuthority.verifyAccess(ctx, principal, pin.scope, "agent-pinned-release"); err != nil {
		return interfaces.ConceptAgentRelease830G2{}, err
	}
	members, err := s.releaseAuthority.repository.GetReleaseMembers(ctx, pin.scope, pin.releaseID)
	if err != nil {
		return interfaces.ConceptAgentRelease830G2{}, mapWikiReleaseRepositoryError(err)
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, pin.scope, pin.releaseID)
	if err != nil {
		return interfaces.ConceptAgentRelease830G2{}, mapWikiReleaseRepositoryError(err)
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(
		ctx, pin.scope, release.PreparationID,
	)
	if err != nil {
		return interfaces.ConceptAgentRelease830G2{}, mapWikiReleaseRepositoryError(err)
	}
	if release.WikiReleaseScope != pin.scope || release.ID != pin.releaseID ||
		release.PreparationID != preparation.ID ||
		release.BaseReleaseID != preparation.ExpectedReleaseID ||
		release.BaseActivationEpoch != preparation.ExpectedActivationEpoch ||
		release.BaseActivationEpoch == ^uint64(0) ||
		pin.activationEpoch != release.BaseActivationEpoch+1 ||
		release.ManifestDigest != preparation.ManifestDigest {
		return interfaces.ConceptAgentRelease830G2{}, ErrSchemaWikiPreparationInvalid
	}
	bundle, expected, conceptErr := validateConceptPreparation830G2(
		preparation, types.WikiReleasePreparationReady, pin.scope,
	)
	if conceptErr == nil && release.CandidateDigest == bundle.CandidateHash &&
		conceptMemberSnapshotSetsEqual830G2(expected, members) {
		return projectConceptAgentRelease830G2(bundle, members, pin), nil
	}
	manifest, expected, g1Err := validateEntityPageGraphPreparation830G1(
		preparation, types.WikiReleasePreparationReady, pin.scope,
	)
	if g1Err == nil && release.CandidateDigest == manifest.InputAuthority.CandidateSHA256 &&
		wikiReleaseMemberSnapshotsEqual(expected, members) {
		return projectEntityPageAgentRelease830G1(manifest, members, pin), nil
	}
	return interfaces.ConceptAgentRelease830G2{}, ErrSchemaWikiPreparationInvalid
}

func projectEntityPageAgentRelease830G1(
	manifest types.EntityPageManifest830G1,
	snapshots []types.WikiReleaseMemberSnapshot,
	pin WikiReleasePinnedRead,
) interfaces.ConceptAgentRelease830G2 {
	digests := make(map[string]string, len(snapshots))
	for _, snapshot := range snapshots {
		digests[snapshot.LogicalSlug] = snapshot.MemberDigest
	}
	directSources := entityPageAgentDirectSources830G1(manifest)
	result := interfaces.ConceptAgentRelease830G2{
		WikiKBID: pin.scope.WikiKBID, SpaceID: pin.scope.SpaceID, RawKBID: pin.scope.RawKBID,
		ReleaseID: pin.releaseID, ActivationEpoch: pin.activationEpoch,
		Members: make([]interfaces.ConceptAgentMember830G2, 0, len(manifest.Members)),
	}
	for _, member := range manifest.Members {
		sources := append([]interfaces.ConceptAgentSource830G2(nil), directSources[member.PageID]...)
		switch member.PageKind {
		case "overview":
			if payload, err := member.OverviewPayload(); err == nil {
				for _, reference := range payload.FieldAssertions {
					sources = append(sources, directSources[reference.PageID]...)
				}
			}
		case "section":
			if payload, err := member.SectionPayload(); err == nil {
				for _, reference := range payload.FieldAssertions {
					sources = append(sources, directSources[reference.PageID]...)
				}
			}
		}
		result.Members = append(result.Members, interfaces.ConceptAgentMember830G2{
			Kind: member.PageKind, MemberID: member.PageID, OwnerID: manifest.EntityID,
			Title: member.ShortTitle, Content: string(member.Payload),
			MemberDigest: digests[member.PageID], Sources: dedupConceptAgentSources830G2(sources),
		})
	}
	return result
}

func entityPageAgentDirectSources830G1(
	manifest types.EntityPageManifest830G1,
) map[string][]interfaces.ConceptAgentSource830G2 {
	attempts := make(map[string]int64, len(manifest.InputAuthority.SourceAuthorities))
	for _, source := range manifest.InputAuthority.SourceAuthorities {
		attempts[source.KnowledgeID+"\x00"+source.RevisionSourceID] = int64(source.WeKnoraParseAttempt)
	}
	result := make(map[string][]interfaces.ConceptAgentSource830G2)
	for _, member := range manifest.Members {
		if member.PageKind != "field" {
			continue
		}
		payload, err := member.FieldAssertionPayload()
		if err != nil {
			continue
		}
		for _, citation := range payload.Citations {
			result[member.PageID] = append(result[member.PageID], interfaces.ConceptAgentSource830G2{
				SourceType: "DOCUMENT", KnowledgeID: citation.KnowledgeID,
				RevisionID:   citation.SourceRevisionID,
				ParseAttempt: attempts[citation.KnowledgeID+"\x00"+citation.SourceRevisionID],
				BlockID:      citation.LocatorRef, PageNumber: citation.PageNumber,
				SourceHash: citation.SourceSHA256, ParseHash: citation.ParseManifestSHA256,
				QuoteHash: schemaWikiStringSHA256(citation.QuoteSnapshot),
			})
		}
		result[member.PageID] = dedupConceptAgentSources830G2(result[member.PageID])
	}
	return result
}

func projectConceptAgentRelease830G2(
	bundle types.ConceptCandidateBundle830G2,
	snapshots []types.WikiReleaseMemberSnapshot,
	pin WikiReleasePinnedRead,
) interfaces.ConceptAgentRelease830G2 {
	digests := make(map[string]string, len(snapshots))
	for _, snapshot := range snapshots {
		digests[snapshot.LogicalSlug] = snapshot.MemberDigest
	}
	directSources := conceptAgentDirectSources830G2(bundle)
	result := interfaces.ConceptAgentRelease830G2{
		WikiKBID: pin.scope.WikiKBID, SpaceID: pin.scope.SpaceID, RawKBID: pin.scope.RawKBID,
		ReleaseID: pin.releaseID, ActivationEpoch: pin.activationEpoch,
		Members: make([]interfaces.ConceptAgentMember830G2, 0, len(bundle.PageManifest.Members)),
	}
	for _, member := range bundle.PageManifest.Members {
		sources := append([]interfaces.ConceptAgentSource830G2(nil), directSources[member.MemberID]...)
		if member.Kind == "entity_overview" || member.Kind == "free_wiki" {
			var navigation struct {
				MemberIDs []string `json:"member_ids"`
			}
			if json.Unmarshal(member.Payload, &navigation) == nil {
				for _, childID := range navigation.MemberIDs {
					sources = append(sources, directSources[childID]...)
				}
			}
		}
		result.Members = append(result.Members, interfaces.ConceptAgentMember830G2{
			Kind: member.Kind, MemberID: member.MemberID, OwnerID: member.OwnerID,
			Title: member.Title, Content: member.Content, MemberDigest: digests[member.MemberID],
			Sources: dedupConceptAgentSources830G2(sources),
		})
	}
	return result
}

func conceptAgentDirectSources830G2(
	bundle types.ConceptCandidateBundle830G2,
) map[string][]interfaces.ConceptAgentSource830G2 {
	result := make(map[string][]interfaces.ConceptAgentSource830G2)
	for _, definition := range bundle.CompileResult.Output.Definitions {
		id, _ := definition.DefinitionID()
		result[id] = conceptAgentSources830G2(definition.Evidence)
	}
	for _, field := range bundle.CompileResult.Output.Fields {
		id, _ := field.FieldAssertionID()
		result[id] = conceptAgentSources830G2(field.Evidence)
	}
	for _, page := range bundle.CompileResult.Output.Pages {
		id, _ := page.FreeWikiPageID()
		result[id] = conceptAgentSources830G2(page.Evidence)
	}
	return result
}

func conceptAgentSources830G2(
	evidence []types.ConceptEvidence830G2,
) []interfaces.ConceptAgentSource830G2 {
	result := make([]interfaces.ConceptAgentSource830G2, 0, len(evidence))
	for _, item := range evidence {
		result = append(result, interfaces.ConceptAgentSource830G2{
			SourceType: item.SourceType, KnowledgeID: item.KnowledgeID,
			RevisionID: item.RevisionID, ParseAttempt: item.ParseAttempt,
			BlockID: item.BlockID, PageNumber: item.PageNumber,
			SourceHash: item.SourceHash, ParseHash: item.ParseHash, QuoteHash: item.QuoteHash,
		})
	}
	return dedupConceptAgentSources830G2(result)
}

func dedupConceptAgentSources830G2(
	sources []interfaces.ConceptAgentSource830G2,
) []interfaces.ConceptAgentSource830G2 {
	byKey := make(map[string]interfaces.ConceptAgentSource830G2, len(sources))
	for _, source := range sources {
		key := fmt.Sprintf("%s\x00%s\x00%s\x00%d\x00%s\x00%d\x00%s",
			source.SourceType, source.KnowledgeID, source.RevisionID, source.ParseAttempt,
			source.BlockID, source.PageNumber, source.QuoteHash,
		)
		byKey[key] = source
	}
	keys := make([]string, 0, len(byKey))
	for key := range byKey {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	result := make([]interfaces.ConceptAgentSource830G2, 0, len(keys))
	for _, key := range keys {
		result = append(result, byKey[key])
	}
	return result
}

var _ interfaces.ConceptAgentTurnProvider830G2 = (*ConceptAgentService830G2)(nil)
